"""Matching a lead to partners, ranking them, and releasing the lead in waves.

**Hard filters** (eligibility; never bought):

* the partner is ``ACTIVE`` and not paused;
* ``partners.entitlements.standing(...).can(Action.RECEIVE_REFERRALS, category)``: the
  category is approved, its licence is checked and current, and it is within the plan;
* one of the partner's counted service areas covers the lead (its postcode, its council
  area or its whole state);
* the partner has room: fewer claimed referrals in progress than its ``max_open_leads``;
* the customer is not a member of the partner's organisation.

**Ranking** (explainable; stored on each match as ``score_breakdown``), out of 100: how
closely the area fits (postcode 40, council area 30, state 15), how specialised the partner
is (20 for one category, 14 for two or three, 8 for more), checked and current insurance
(10), how often the partner answers offers within 48 hours (up to 20; new partners get 10)
and spare capacity (up to 10). The plan a partner pays for is not a factor. Ties are broken
by a hash of the lead and partner ids, so the same partners don't always win a tie.

**Release**: the best-ranked ``first_wave`` partners are offered the lead at once; then
``wave_size`` more every ``wave_hours`` while the lead has room, and one more straight away
whenever a partner declines and fewer partners hold an open offer than claims remain.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tenant import bind_tenant
from app.modules.leads.models import (
    OPEN_MATCH,
    WORKING,
    Lead,
    LeadMatch,
    LeadMatchStatus,
    LeadStatus,
)
from app.modules.leads.policy import of_lead
from app.modules.marketplace.models import MarketplaceCategory
from app.modules.partners import entitlements
from app.modules.partners.models import (
    PartnerCategory,
    PartnerCategoryStatus,
    PartnerCredential,
    PartnerCredentialKind,
    PartnerOrganisation,
    PartnerServiceArea,
    PartnerStatus,
    ServiceAreaKind,
)
from app.modules.tenancy.models import MemberStatus, OrganisationMember

GEOGRAPHY_POINTS = {
    ServiceAreaKind.POSTCODE: 40,
    ServiceAreaKind.LGA: 30,
    ServiceAreaKind.STATE: 15,
}
GEOGRAPHY_WHY = {
    ServiceAreaKind.POSTCODE: "Works in this postcode",
    ServiceAreaKind.LGA: "Works in this council area",
    ServiceAreaKind.STATE: "Works across the state",
}
RESPONSE_WINDOW = timedelta(hours=48)
# Fewer offers than this and the partner is treated as new (a neutral score).
RESPONSE_MIN_OFFERS = 5
MAX_SCORE = 100

_COUNCIL_WORDS = re.compile(r"\b(regional|city|shire|town|municipal|aboriginal)?\s*council\b")


def normalise_area(value: str | None) -> str:
    """A council area name as both sides write it: "Cairns Regional Council", "cairns" and
    "City of Cairns" all become "cairns"."""
    if not value:
        return ""
    s = value.casefold().strip()
    s = re.sub(r"^city of\s+", "", s)
    s = _COUNCIL_WORDS.sub("", s)
    s = re.sub(r"\b(regional|shire)$", "", s.strip())
    return re.sub(r"\s+", " ", s).strip()


def area_fit(area: PartnerServiceArea, lead: Lead) -> ServiceAreaKind | None:
    if area.state != lead.state:
        return None
    if area.kind == ServiceAreaKind.STATE:
        return ServiceAreaKind.STATE
    if area.kind == ServiceAreaKind.POSTCODE and area.value == lead.postcode:
        return ServiceAreaKind.POSTCODE
    if (
        area.kind == ServiceAreaKind.LGA
        and lead.lga
        and normalise_area(area.value) == normalise_area(lead.lga)
    ):
        return ServiceAreaKind.LGA
    return None


def _factor(factor: str, points: int, maximum: int, why: str) -> dict[str, Any]:
    return {"factor": factor, "points": points, "max": maximum, "why": why}


def tie_break(lead_id: uuid.UUID, partner_id: uuid.UUID) -> str:
    return hashlib.sha256(f"{lead_id}:{partner_id}".encode()).hexdigest()


@dataclass(frozen=True)
class Candidate:
    partner: PartnerOrganisation
    score: int
    breakdown: list[dict[str, Any]]


async def working_count(db: AsyncSession, partner_id: uuid.UUID) -> int:
    """Claimed referrals the partner is still working on."""
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(LeadMatch)
                .where(
                    LeadMatch.partner_organisation_id == partner_id,
                    LeadMatch.status.in_(WORKING),
                )
            )
        ).scalar_one()
    )


async def _responsiveness(
    db: AsyncSession, partner_id: uuid.UUID, lead_id: uuid.UUID
) -> tuple[int, int]:
    """(offers made, offers answered within 48 hours), other leads only."""
    answered = case(
        (
            and_(
                LeadMatch.responded_at.is_not(None),
                LeadMatch.responded_at - LeadMatch.offered_at <= RESPONSE_WINDOW,
            ),
            1,
        ),
        else_=0,
    )
    row = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(answered), 0)).where(
                LeadMatch.partner_organisation_id == partner_id,
                LeadMatch.offered_at.is_not(None),
                LeadMatch.lead_id != lead_id,
            )
        )
    ).one()
    return int(row[0]), int(row[1])


async def _excluded_partners(db: AsyncSession, lead: Lead) -> set[uuid.UUID]:
    """Partner organisations any member of the customer's organisation belongs to."""
    customer_members = select(OrganisationMember.user_id).where(
        OrganisationMember.organisation_id == lead.organisation_id,
        OrganisationMember.status == MemberStatus.ACTIVE,
    )
    rows = await db.execute(
        select(PartnerOrganisation.id)
        .join(
            OrganisationMember,
            OrganisationMember.organisation_id == PartnerOrganisation.organisation_id,
        )
        .where(
            OrganisationMember.status == MemberStatus.ACTIVE,
            OrganisationMember.user_id.in_(customer_members),
        )
    )
    return set(rows.scalars())


async def candidates(db: AsyncSession, lead: Lead, *, on: date) -> list[Candidate]:
    """Every partner that passes the hard filters, with its score. Binds each partner's
    organisation in turn (its plan is read from its subscriptions)."""
    category = await db.get(MarketplaceCategory, lead.category_id)
    assert category is not None
    rows = await db.execute(
        select(PartnerOrganisation)
        .join(PartnerCategory, PartnerCategory.partner_organisation_id == PartnerOrganisation.id)
        .where(
            PartnerOrganisation.verification_status == PartnerStatus.ACTIVE,
            PartnerOrganisation.paused.is_(False),
            PartnerCategory.category_id == lead.category_id,
            PartnerCategory.status == PartnerCategoryStatus.APPROVED,
            PartnerOrganisation.id.in_(
                select(PartnerServiceArea.partner_organisation_id).where(
                    PartnerServiceArea.state == lead.state
                )
            ),
        )
        .order_by(PartnerOrganisation.id)
    )
    partners = list(rows.scalars().unique())
    excluded = await _excluded_partners(db, lead)
    out: list[Candidate] = []
    for partner in partners:
        if partner.id in excluded:
            continue
        await bind_tenant(db, partner.organisation_id)
        plan = await entitlements.plan(db, partner.organisation_id)
        standing = await entitlements.standing(db, partner, on=on, plan_view=plan)
        if not standing.can(entitlements.Action.RECEIVE_REFERRALS, category.key):
            continue
        fits = [f for a in standing.areas if a.counts and (f := area_fit(a.row, lead))]
        if not fits:
            continue
        working = await working_count(db, partner.id)
        if partner.max_open_leads is not None and working >= partner.max_open_leads:
            continue
        best = max(fits, key=lambda k: GEOGRAPHY_POINTS[k])
        breakdown = [_factor("area", GEOGRAPHY_POINTS[best], 40, GEOGRAPHY_WHY[best])]

        counted = sum(1 for c in standing.categories if c.counts)
        points = 20 if counted == 1 else 14 if counted <= 3 else 8
        breakdown.append(
            _factor(
                "specialist",
                points,
                20,
                "Focuses on this kind of work"
                if counted == 1
                else f"Approved for {counted} kinds of work",
            )
        )

        insured = any(
            c.kind in (PartnerCredentialKind.PI_INSURANCE, PartnerCredentialKind.PL_INSURANCE)
            and entitlements.credential_current(c, on)
            for c in (
                await db.execute(
                    select(PartnerCredential).where(
                        PartnerCredential.partner_organisation_id == partner.id
                    )
                )
            ).scalars()
        )
        breakdown.append(
            _factor(
                "insurance",
                10 if insured else 0,
                10,
                "Insurance checked and current" if insured else "No checked insurance",
            )
        )

        offers, answered = await _responsiveness(db, partner.id, lead.id)
        if offers < RESPONSE_MIN_OFFERS:
            breakdown.append(_factor("response", 10, 20, "New to referrals"))
        else:
            share = answered / offers
            breakdown.append(
                _factor(
                    "response",
                    round(20 * share),
                    20,
                    f"Answers {round(100 * share)}% of offers within 48 hours",
                )
            )

        if partner.max_open_leads:
            spare = 1 - working / partner.max_open_leads
            breakdown.append(
                _factor(
                    "capacity",
                    round(10 * spare),
                    10,
                    f"{working} of {partner.max_open_leads} referrals in progress",
                )
            )
        else:
            breakdown.append(_factor("capacity", 10, 10, "No limit on referrals in progress"))

        score = sum(int(f["points"]) for f in breakdown)
        out.append(Candidate(partner, score, breakdown))
    out.sort(key=lambda c: (-c.score, tie_break(lead.id, c.partner.id)))
    return out


async def match(db: AsyncSession, lead: Lead, *, on: date, now: datetime) -> int:
    """Add a match for every eligible partner not matched yet. Returns how many were added.
    Safe to run again (new partners are added after the existing ones)."""
    if lead.status != LeadStatus.OPEN:
        return 0
    found = await candidates(db, lead, on=on)
    existing = set(
        (
            await db.execute(
                select(LeadMatch.partner_organisation_id).where(LeadMatch.lead_id == lead.id)
            )
        ).scalars()
    )
    last_rank = (
        await db.execute(select(func.max(LeadMatch.rank)).where(LeadMatch.lead_id == lead.id))
    ).scalar_one() or 0
    added = 0
    for c in found:
        if c.partner.id in existing:
            continue
        last_rank += 1
        result = await db.execute(
            insert(LeadMatch)
            .values(
                id=uuid.uuid4(),
                lead_id=lead.id,
                partner_organisation_id=c.partner.id,
                score=c.score,
                score_breakdown=c.breakdown,
                rank=last_rank,
                status=LeadMatchStatus.MATCHED,
            )
            .on_conflict_do_nothing(index_elements=["lead_id", "partner_organisation_id"])
        )
        added += result.rowcount or 0  # type: ignore[attr-defined]
    lead.matched_at = now
    await db.flush()
    return added


async def release(db: AsyncSession, lead: Lead, *, now: datetime) -> list[LeadMatch]:
    """Offer the lead to the next partners due to see it. Returns the newly offered matches."""
    if lead.status != LeadStatus.OPEN or now >= lead.expires_at:
        return []
    policy = of_lead(lead.policy)
    matches = list(
        (
            await db.execute(
                select(LeadMatch)
                .where(LeadMatch.lead_id == lead.id)
                .order_by(LeadMatch.rank)
                .with_for_update()
            )
        ).scalars()
    )
    waiting = [m for m in matches if m.offered_at is None and m.status == LeadMatchStatus.MATCHED]
    if not waiting:
        return []
    remaining = lead.max_claims - lead.claimed_count
    if remaining <= 0:
        return []
    holding = sum(1 for m in matches if m.offered_at is not None and m.status in OPEN_MATCH)
    wave = False
    if lead.last_wave_at is None:
        count, wave = policy.first_wave, True
    elif now - lead.last_wave_at >= timedelta(hours=policy.wave_hours):
        count, wave = policy.wave_size, True
    else:
        count = max(0, remaining - holding)  # top up after declines
    offered = waiting[:count]
    for m in offered:
        m.offered_at = now
    if wave:
        lead.last_wave_at = now
    await db.flush()
    return offered
