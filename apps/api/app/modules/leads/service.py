"""The lead engine: customers asking to be introduced, partners claiming referrals, lead
fees and credits, and the staff tools around them.

Tenant binding: customer routes run bound to the customer's organisation (the consent is
their row); partner routes run bound to the partner's organisation (credits and the plan are
its rows). Leads, matches and claims are platform rows, always filtered here by the caller's
organisation or partner. Anything shown to a partner before a claim goes through
``public_view``; contact details only through ``claim_out``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, not_found
from app.modules.assessments import service as assessments
from app.modules.assessments.models import Assessment
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.billing import service as billing
from app.modules.entities.models import Address, BusinessProfile, Property
from app.modules.identity.models import AppUser
from app.modules.leads import consent, matching
from app.modules.leads.models import (
    OPEN_MATCH,
    CreditKind,
    CreditLedgerEntry,
    Lead,
    LeadClaim,
    LeadContact,
    LeadMatch,
    LeadMatchStatus,
    LeadPrice,
    LeadStatus,
    LeadStatusEvent,
    ReferralConsent,
)
from app.modules.leads.policy import for_category
from app.modules.leads.schemas import (
    ClaimOut,
    FeeOut,
    LeadPreferencesIn,
    LeadPublicView,
    ReferralIn,
    ScoreFactorOut,
)
from app.modules.marketplace import service as marketplace
from app.modules.marketplace.models import MarketplaceCategory
from app.modules.notifications.reminders import BRISBANE
from app.modules.partners import entitlements
from app.modules.partners.models import PartnerOrganisation, PartnerStatus
from app.modules.projects.models import Project
from app.modules.rules.payload import parse_payload
from app.modules.tenancy.models import Organisation

LEADS_FEATURE = entitlements.LEADS_FEATURE
CREDIT_PACK_PRODUCT = "lead.credits"
CREDIT_PACK_SUBJECT = "lead_credits"
REQUIREMENTS_SHOWN = 8

# What a partner may record after claiming, from each status.
OUTCOMES: dict[LeadMatchStatus, tuple[LeadMatchStatus, ...]] = {
    LeadMatchStatus.CLAIMED: (
        LeadMatchStatus.CONTACTED,
        LeadMatchStatus.QUOTED,
        LeadMatchStatus.WON,
        LeadMatchStatus.LOST,
    ),
    LeadMatchStatus.CONTACTED: (LeadMatchStatus.QUOTED, LeadMatchStatus.WON, LeadMatchStatus.LOST),
    LeadMatchStatus.QUOTED: (LeadMatchStatus.WON, LeadMatchStatus.LOST),
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def _conflict(code: str, message: str) -> ApiError:
    return ApiError(status.HTTP_409_CONFLICT, code, message)


def month_start(now: datetime) -> datetime:
    """The start of the current calendar month in Brisbane (included referrals reset)."""
    local = now.astimezone(BRISBANE)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def _transition(
    db: AsyncSession,
    match: LeadMatch,
    to: LeadMatchStatus,
    *,
    actor_id: uuid.UUID | None,
    note: str | None = None,
) -> None:
    db.add(
        LeadStatusEvent(
            lead_match_id=match.id,
            from_status=match.status,
            to_status=to,
            actor_id=actor_id,
            note=note,
        )
    )
    match.status = to


# --- Customer: options, asking, withdrawing ---------------------------------------------


@dataclass(frozen=True)
class ReferralOptions:
    assessment: Assessment
    categories: list[tuple[MarketplaceCategory, bool]]  # (category, open request exists)
    max_providers: int
    contact: dict[str, str | None]
    location: dict[str, str | None]


async def _assessment_categories(
    db: AsyncSession, organisation_id: uuid.UUID, project: Project, assessment_id: uuid.UUID
) -> tuple[Assessment, list[MarketplaceCategory]]:
    assessment, owner, findings = await assessments.get(db, organisation_id, assessment_id)
    if owner.id != project.id:
        raise not_found("Assessment")
    keys: list[str] = []
    for f in findings:
        for key in parse_payload(f.payload).referral_categories:
            if key not in keys:
                keys.append(key)
    found = await marketplace.by_keys(db, keys)
    return assessment, [found[k] for k in keys if k in found and found[k].active]


async def _open_categories(db: AsyncSession, project: Project) -> set[uuid.UUID]:
    return set(
        (
            await db.execute(
                select(Lead.category_id).where(
                    Lead.organisation_id == project.organisation_id,
                    Lead.project_id == project.id,
                    Lead.status == LeadStatus.OPEN,
                )
            )
        ).scalars()
    )


async def _address(db: AsyncSession, project: Project) -> Address | None:
    address_id: uuid.UUID | None = None
    if project.property_id is not None:
        prop = await db.get(Property, project.property_id)
        address_id = prop.address_id if prop else None
    elif project.business_profile_id is not None:
        profile = await db.get(BusinessProfile, project.business_profile_id)
        address_id = profile.address_id if profile else None
    return await db.get(Address, address_id) if address_id else None


async def options(
    db: AsyncSession, user: AppUser, project: Project, assessment_id: uuid.UUID
) -> ReferralOptions:
    assessment, categories = await _assessment_categories(
        db, project.organisation_id, project, assessment_id
    )
    open_ids = await _open_categories(db, project)
    address = await _address(db, project)
    location: dict[str, str | None] = {"suburb": None, "lga": None, "state": None, "postcode": None}
    contact: dict[str, str | None] = {
        "name": user.display_name,
        "email": str(user.email),
        "phone": None,
        "site_address": None,
    }
    if address is not None:
        location = {
            "suburb": address.suburb,
            "lga": address.lga_code
            if address.lga_code and not address.lga_code.isdigit()
            else None,
            "state": address.state,
            "postcode": address.postcode,
        }
        line = ", ".join(x for x in (address.line1, address.line2) if x)
        contact["site_address"] = f"{line}, {address.suburb} {address.state} {address.postcode}"
    max_providers = min((for_category(c.key).max_providers for c in categories), default=3)
    return ReferralOptions(
        assessment,
        [(c, c.id in open_ids) for c in categories],
        max_providers,
        contact,
        location,
    )


async def create_referral(
    db: AsyncSession,
    *,
    user: AppUser,
    project: Project,
    data: ReferralIn,
    meta: RequestMeta | None,
    now: datetime,
) -> tuple[ReferralConsent, list[Lead]]:
    """Record the consent and make one lead per category. Matching runs afterwards (a job)."""
    text = await consent.require_current(db)
    if data.consent_text_version_id != text.id:
        raise _conflict(
            "consent_changed", "The consent wording has changed. Read it again and agree."
        )
    assessment, available = await _assessment_categories(
        db, project.organisation_id, project, data.assessment_id
    )
    by_key = {c.key: c for c in available}
    unknown = [k for k in data.categories if k not in by_key]
    if unknown:
        raise ApiError(
            422,
            "category_not_offered",
            "Choose from the kinds of help this assessment found: "
            f"{', '.join(unknown)} isn't one of them.",
        )
    chosen = [by_key[k] for k in data.categories]
    open_ids = await _open_categories(db, project)
    already = [c.label for c in chosen if c.id in open_ids]
    if already:
        raise _conflict(
            "already_requested",
            f"You already have an introduction in progress for: {', '.join(already)}.",
        )
    policies = {c.key: for_category(c.key) for c in chosen}
    cap = min(p.max_providers for p in policies.values())
    if data.max_providers > cap:
        raise ApiError(422, "too_many_providers", f"Choose up to {cap} partners.")

    released = [f.value for f in data.fields_released]
    contact = {f: getattr(data.contact, f) for f in released}
    contact = {k: str(v) for k, v in contact.items()}
    loc = data.location
    record = ReferralConsent(
        organisation_id=project.organisation_id,
        project_id=project.id,
        assessment_id=assessment.id,
        user_id=user.id,
        consent_text_version_id=text.id,
        categories=[c.key for c in chosen],
        max_providers=data.max_providers,
        fields_released=released,
        contact=contact,
        suburb=loc.suburb,
        lga=loc.lga,
        state=loc.state,
        postcode=loc.postcode,
        timing=data.timing,
        summary=data.summary,
        ip=meta.ip if meta else None,
        user_agent=(meta.user_agent or "")[:300] if meta and meta.user_agent else None,
    )
    db.add(record)
    await db.flush()

    approvals, _ = await assessments.requirements(db, assessment)
    requirements: list[str] = []
    for a in approvals:
        if a.title not in requirements:
            requirements.append(a.title)
    requirements = requirements[:REQUIREMENTS_SHOWN]

    leads: list[Lead] = []
    for category in chosen:
        policy = policies[category.key]
        lead = Lead(
            organisation_id=project.organisation_id,
            project_id=project.id,
            referral_consent_id=record.id,
            category_id=category.id,
            vertical=project.vertical,
            suburb=loc.suburb,
            lga=loc.lga,
            state=loc.state,
            postcode=loc.postcode,
            timing=data.timing,
            summary=data.summary,
            requirements=requirements,
            max_claims=data.max_providers,
            policy=policy.model_dump(),
            status=LeadStatus.OPEN,
            expires_at=now + timedelta(days=policy.expires_after_days),
        )
        db.add(lead)
        await db.flush()
        db.add(LeadContact(lead_id=lead.id, contact=contact, fields_released=released))
        leads.append(lead)
    await db.flush()
    await audit.record(
        db,
        "referral.consented",
        actor_user_id=user.id,
        organisation_id=project.organisation_id,
        target_type="referral_consent",
        target_id=record.id,
        meta=meta,
        details={
            "project_id": str(project.id),
            "consent_version": text.version,
            "categories": record.categories,
            "max_providers": record.max_providers,
            "fields_released": released,
            "leads": [str(lead.id) for lead in leads],
        },
    )
    return record, leads


async def close_lead(
    db: AsyncSession, lead: Lead, to: LeadStatus, *, now: datetime, note: str
) -> None:
    """End a lead: offers not yet claimed expire and the contact details are deleted (each
    claim keeps the copy released to that partner)."""
    lead.status = to
    lead.closed_at = now
    for m in (
        await db.execute(
            select(LeadMatch)
            .where(LeadMatch.lead_id == lead.id, LeadMatch.status.in_(OPEN_MATCH))
            .with_for_update()
        )
    ).scalars():
        await _transition(db, m, LeadMatchStatus.EXPIRED, actor_id=None, note=note)
    await db.execute(delete(LeadContact).where(LeadContact.lead_id == lead.id))
    await db.flush()


async def get_consent(
    db: AsyncSession, organisation_id: uuid.UUID, consent_id: uuid.UUID, *, lock: bool = False
) -> ReferralConsent:
    query = select(ReferralConsent).where(
        ReferralConsent.organisation_id == organisation_id, ReferralConsent.id == consent_id
    )
    if lock:
        query = query.with_for_update()
    row = (await db.execute(query)).scalar_one_or_none()
    if row is None:
        raise not_found("Introduction request")
    return row


async def withdraw(
    db: AsyncSession,
    record: ReferralConsent,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
    now: datetime,
) -> None:
    if record.withdrawn_at is not None:
        return
    record.withdrawn_at = now
    record.withdrawn_by = actor_id
    for lead in (
        await db.execute(
            select(Lead)
            .where(Lead.referral_consent_id == record.id, Lead.status == LeadStatus.OPEN)
            .with_for_update()
        )
    ).scalars():
        await close_lead(db, lead, LeadStatus.WITHDRAWN, now=now, note="The customer withdrew.")
    await audit.record(
        db,
        "referral.withdrawn",
        actor_user_id=actor_id,
        organisation_id=record.organisation_id,
        target_type="referral_consent",
        target_id=record.id,
        meta=meta,
    )


@dataclass(frozen=True)
class CustomerClaim:
    claim: LeadClaim
    match: LeadMatch
    partner: PartnerOrganisation
    organisation: Organisation


@dataclass(frozen=True)
class CustomerLead:
    lead: Lead
    category: MarketplaceCategory
    offered: int
    claims: list[CustomerClaim]


async def referrals_for_project(
    db: AsyncSession, project: Project
) -> list[tuple[ReferralConsent, int, list[CustomerLead]]]:
    from app.modules.leads.models import ConsentTextVersion

    consents = list(
        (
            await db.execute(
                select(ReferralConsent, ConsentTextVersion.version)
                .join(
                    ConsentTextVersion,
                    ConsentTextVersion.id == ReferralConsent.consent_text_version_id,
                )
                .where(
                    ReferralConsent.organisation_id == project.organisation_id,
                    ReferralConsent.project_id == project.id,
                )
                .order_by(ReferralConsent.created_at.desc())
            )
        ).all()
    )
    out = []
    for record, version in consents:
        leads: list[CustomerLead] = []
        for lead, category in await db.execute(
            select(Lead, MarketplaceCategory)
            .join(MarketplaceCategory, MarketplaceCategory.id == Lead.category_id)
            .where(
                Lead.organisation_id == project.organisation_id,
                Lead.referral_consent_id == record.id,
            )
            .order_by(MarketplaceCategory.sort_order)
        ):
            offered = (
                await db.execute(
                    select(func.count())
                    .select_from(LeadMatch)
                    .where(LeadMatch.lead_id == lead.id, LeadMatch.offered_at.is_not(None))
                )
            ).scalar_one()
            claims = [
                CustomerClaim(c, m, p, o)
                for c, m, p, o in await db.execute(
                    select(LeadClaim, LeadMatch, PartnerOrganisation, Organisation)
                    .join(LeadMatch, LeadMatch.id == LeadClaim.lead_match_id)
                    .join(
                        PartnerOrganisation,
                        PartnerOrganisation.id == LeadClaim.partner_organisation_id,
                    )
                    .join(Organisation, Organisation.id == PartnerOrganisation.organisation_id)
                    .where(LeadClaim.lead_id == lead.id)
                    .order_by(LeadClaim.created_at)
                )
            ]
            leads.append(CustomerLead(lead, category, int(offered), claims))
        out.append((record, int(version), leads))
    return out


# --- Credits -----------------------------------------------------------------------------


async def balance(db: AsyncSession, organisation_id: uuid.UUID) -> tuple[int, int]:
    """(balance in cents, last sequence number). Bind the organisation first."""
    row = (
        await db.execute(
            select(CreditLedgerEntry.balance_after_cents, CreditLedgerEntry.seq)
            .where(CreditLedgerEntry.organisation_id == organisation_id)
            .order_by(CreditLedgerEntry.seq.desc())
            .limit(1)
        )
    ).one_or_none()
    return (int(row[0]), int(row[1])) if row else (0, 0)


async def add_credit_entry(
    db: AsyncSession,
    partner: PartnerOrganisation,
    *,
    kind: CreditKind,
    delta_cents: int,
    actor_id: uuid.UUID | None,
    reference_type: str | None = None,
    reference_id: uuid.UUID | None = None,
    note: str | None = None,
) -> CreditLedgerEntry:
    """Append to the partner's ledger. The caller holds the partner row lock (``FOR
    UPDATE``), which serialises writers; the unique sequence backs that up."""
    current, seq = await balance(db, partner.organisation_id)
    after = current + delta_cents
    if after < 0:
        raise ApiError(
            402,
            "insufficient_credit",
            "Not enough credit. Buy credit in Referrals, then try again.",
        )
    entry = CreditLedgerEntry(
        organisation_id=partner.organisation_id,
        seq=seq + 1,
        kind=kind,
        delta_cents=delta_cents,
        balance_after_cents=after,
        reference_type=reference_type,
        reference_id=reference_id,
        note=note,
        created_by=actor_id,
    )
    db.add(entry)
    await db.flush()
    return entry


async def ledger(db: AsyncSession, organisation_id: uuid.UUID, limit: int = 100) -> list[Any]:
    return list(
        (
            await db.execute(
                select(CreditLedgerEntry)
                .where(CreditLedgerEntry.organisation_id == organisation_id)
                .order_by(CreditLedgerEntry.seq.desc())
                .limit(limit)
            )
        ).scalars()
    )


async def credits_purchased(db: AsyncSession, payment: Any) -> None:
    """A paid credit pack (from the Stripe webhook, the partner organisation bound): credit
    what was paid, once."""
    already = (
        await db.execute(
            select(CreditLedgerEntry.id).where(
                CreditLedgerEntry.organisation_id == payment.organisation_id,
                CreditLedgerEntry.reference_type == "payment",
                CreditLedgerEntry.reference_id == payment.id,
            )
        )
    ).scalar_one_or_none()
    if already is not None:
        return
    partner = (
        await db.execute(
            select(PartnerOrganisation)
            .where(PartnerOrganisation.organisation_id == payment.organisation_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if partner is None:
        return
    entry = await add_credit_entry(
        db,
        partner,
        kind=CreditKind.PURCHASE,
        delta_cents=payment.amount_cents,
        actor_id=None,
        reference_type="payment",
        reference_id=payment.id,
        note="Credit bought",
    )
    await audit.record(
        db,
        "credits.purchased",
        organisation_id=payment.organisation_id,
        target_type="credit_ledger_entry",
        target_id=entry.id,
        details={"amount_cents": payment.amount_cents, "payment_id": str(payment.id)},
    )


# --- Partner: offers, fees, claiming ---------------------------------------------------


async def active_price(db: AsyncSession, category_id: uuid.UUID) -> LeadPrice | None:
    return (
        await db.execute(
            select(LeadPrice).where(
                LeadPrice.category_id == category_id, LeadPrice.deactivated_at.is_(None)
            )
        )
    ).scalar_one_or_none()


async def included_used(db: AsyncSession, partner_id: uuid.UUID, now: datetime) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(LeadClaim)
                .where(
                    LeadClaim.partner_organisation_id == partner_id,
                    LeadClaim.included.is_(True),
                    LeadClaim.created_at >= month_start(now),
                )
            )
        ).scalar_one()
    )


async def included_limit(db: AsyncSession, organisation_id: uuid.UUID) -> int | None:
    """Referrals the plan includes each month. Unlike other limits this applies whether or
    not a plan is on sale: buying credit is always the way past it, and fees only apply in
    categories staff have priced."""
    return (await billing.allowance(db, organisation_id, LEADS_FEATURE)).limit


async def fee_for(
    db: AsyncSession,
    partner: PartnerOrganisation,
    category: MarketplaceCategory,
    *,
    now: datetime,
) -> FeeOut:
    used = await included_used(db, partner.id, now)
    limit = await included_limit(db, partner.organisation_id)
    bal, _ = await balance(db, partner.organisation_id)

    def out(included: bool, fee: int, why: str) -> FeeOut:
        return FeeOut(
            included=included,
            fee_cents=fee,
            included_used=used,
            included_limit=limit,
            balance_cents=bal,
            can_afford=fee <= bal,
            explanation=why,
        )

    if category.restricted:
        return out(False, 0, "No fee: we don't charge for referrals in this kind of work.")
    if limit is None or used < limit:
        left = "unlimited" if limit is None else f"{limit - used} of {limit} left"
        return out(True, 0, f"Included in your plan this month ({left}).")
    price = await active_price(db, category.id)
    if price is None:
        return out(False, 0, "No fee: this kind of work has no lead fee.")
    return out(
        False,
        price.amount_cents,
        f"You've used this month's {limit} included referrals: this one costs "
        f"${price.amount_cents / 100:,.2f} from your credit.",
    )


def public_view(match: LeadMatch, lead: Lead, category: MarketplaceCategory) -> LeadPublicView:
    """The whitelisted projection. Built field by field: never pass a row through."""
    assert match.offered_at is not None
    return LeadPublicView(
        match_id=match.id,
        lead_id=lead.id,
        category_key=category.key,
        category_label=category.label,
        vertical=lead.vertical,
        suburb=lead.suburb,
        lga=lead.lga,
        state=lead.state,
        postcode=lead.postcode,
        timing=lead.timing,
        summary=lead.summary,
        requirements=list(lead.requirements),
        max_claims=lead.max_claims,
        claims_left=max(0, lead.max_claims - lead.claimed_count),
        lead_status=lead.status,
        status=match.status,
        offered_at=match.offered_at,
        expires_at=lead.expires_at,
        score=float(match.score),
        score_breakdown=[ScoreFactorOut(**f) for f in match.score_breakdown],
    )


def claim_out(
    match: LeadMatch, lead: Lead, category: MarketplaceCategory, claim: LeadClaim
) -> ClaimOut:
    return ClaimOut(
        match_id=match.id,
        lead=public_view(match, lead, category),
        claimed_at=claim.created_at,
        fee_cents=claim.fee_cents,
        included=claim.included,
        refunded_at=claim.refunded_at,
        released_fields=list(claim.released_fields),
        contact=dict(claim.released_contact),
    )


@dataclass(frozen=True)
class Offer:
    match: LeadMatch
    lead: Lead
    category: MarketplaceCategory
    claim: LeadClaim | None


async def offers(
    db: AsyncSession, partner: PartnerOrganisation, *, statuses: list[LeadMatchStatus] | None = None
) -> list[Offer]:
    query = (
        select(LeadMatch, Lead, MarketplaceCategory, LeadClaim)
        .join(Lead, Lead.id == LeadMatch.lead_id)
        .join(MarketplaceCategory, MarketplaceCategory.id == Lead.category_id)
        .outerjoin(LeadClaim, LeadClaim.lead_match_id == LeadMatch.id)
        .where(
            LeadMatch.partner_organisation_id == partner.id,
            LeadMatch.offered_at.is_not(None),
        )
        .order_by(LeadMatch.offered_at.desc())
        .limit(200)
    )
    if statuses:
        query = query.where(LeadMatch.status.in_(statuses))
    return [Offer(m, lead, c, claim) for m, lead, c, claim in await db.execute(query)]


async def get_offer(
    db: AsyncSession, partner: PartnerOrganisation, match_id: uuid.UUID, *, lock: bool = False
) -> Offer:
    row = (
        await db.execute(
            select(LeadMatch, Lead, MarketplaceCategory)
            .join(Lead, Lead.id == LeadMatch.lead_id)
            .join(MarketplaceCategory, MarketplaceCategory.id == Lead.category_id)
            .where(
                LeadMatch.id == match_id,
                LeadMatch.partner_organisation_id == partner.id,
                LeadMatch.offered_at.is_not(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise not_found("Referral")
    match, lead, category = row
    if lock:
        # Lead first, then the match: every writer takes them in this order.
        lead = (
            await db.execute(
                select(Lead)
                .where(Lead.id == lead.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        match = (
            await db.execute(
                select(LeadMatch)
                .where(LeadMatch.id == match.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
    claim = (
        await db.execute(select(LeadClaim).where(LeadClaim.lead_match_id == match.id))
    ).scalar_one_or_none()
    return Offer(match, lead, category, claim)


async def mark_viewed(
    db: AsyncSession, offer: Offer, *, actor_id: uuid.UUID, now: datetime
) -> None:
    if offer.match.status == LeadMatchStatus.MATCHED and offer.lead.status == LeadStatus.OPEN:
        await _transition(db, offer.match, LeadMatchStatus.VIEWED, actor_id=actor_id)
        offer.match.viewed_at = now
        await db.flush()


async def _lock_partner(db: AsyncSession, partner_id: uuid.UUID) -> PartnerOrganisation:
    return (
        await db.execute(
            select(PartnerOrganisation)
            .where(PartnerOrganisation.id == partner_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def claim(
    db: AsyncSession,
    partner: PartnerOrganisation,
    match_id: uuid.UUID,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
    now: datetime,
    on: date,
) -> Offer:
    """Accept a referral: in one transaction, lock the lead (then the match and the
    partner), check the partner may still receive it and the lead has room, charge the fee
    and release the consented contact details."""
    offer = await get_offer(db, partner, match_id, lock=True)
    match, lead, category = offer.match, offer.lead, offer.category
    if match.status not in OPEN_MATCH:
        if match.status == LeadMatchStatus.DECLINED:
            raise _conflict("declined", "You declined this referral.")
        if match.status == LeadMatchStatus.EXPIRED:
            raise _conflict("lead_closed", "This referral is no longer available.")
        raise _conflict("already_claimed", "You already accepted this referral.")
    if lead.status != LeadStatus.OPEN or now >= lead.expires_at:
        raise _conflict("lead_closed", "This referral is no longer available.")
    if lead.claimed_count >= lead.max_claims:
        raise _conflict("lead_full", "Enough partners have already accepted this referral.")
    partner = await _lock_partner(db, partner.id)
    plan = await entitlements.plan(db, partner.organisation_id)
    standing = await entitlements.standing(db, partner, on=on, plan_view=plan)
    if not standing.can(entitlements.Action.RECEIVE_REFERRALS, category.key):
        problems = standing.problems or next(
            (c.problems for c in standing.categories if c.category.key == category.key),
            ["Your account can't receive referrals in this kind of work."],
        )
        raise ApiError(403, "not_eligible", " ".join(problems))

    fee = await fee_for(db, partner, category, now=now)
    entry: CreditLedgerEntry | None = None
    if fee.fee_cents > 0:
        if not fee.can_afford:
            raise ApiError(
                402,
                "insufficient_credit",
                f"This referral costs ${fee.fee_cents / 100:,.2f} and your credit is "
                f"${fee.balance_cents / 100:,.2f}. Buy credit, then accept it.",
            )
        entry = await add_credit_entry(
            db,
            partner,
            kind=CreditKind.LEAD_CHARGE,
            delta_cents=-fee.fee_cents,
            actor_id=actor_id,
            reference_type="lead_match",
            reference_id=match.id,
            note=f"Referral: {category.label}, {lead.postcode}",
        )

    contact_row = await db.get(LeadContact, lead.id)
    if contact_row is None:
        raise _conflict("lead_closed", "This referral is no longer available.")
    released_fields = list(contact_row.fields_released)
    released = {k: contact_row.contact[k] for k in released_fields if k in contact_row.contact}
    record = LeadClaim(
        lead_match_id=match.id,
        lead_id=lead.id,
        partner_organisation_id=partner.id,
        claimed_by=actor_id,
        included=fee.included,
        fee_cents=fee.fee_cents,
        credit_ledger_entry_id=entry.id if entry else None,
        released_fields=released_fields,
        released_contact=released,
        entitlement_snapshot={
            "plan": plan.name,
            "included_used": fee.included_used,
            "included_limit": fee.included_limit,
            "fee_cents": fee.fee_cents,
            "balance_before_cents": fee.balance_cents,
            "explanation": fee.explanation,
        },
    )
    db.add(record)
    await _transition(db, match, LeadMatchStatus.CLAIMED, actor_id=actor_id)
    match.responded_at = now
    lead.claimed_count += 1
    await db.flush()
    if lead.claimed_count >= lead.max_claims:
        await close_lead(
            db, lead, LeadStatus.FILLED, now=now, note="Enough partners accepted this referral."
        )
    for action, details in (
        (
            "lead.claimed",
            {"lead_id": str(lead.id), "fee_cents": fee.fee_cents, "included": fee.included},
        ),
        ("contact.released", {"lead_id": str(lead.id), "fields": released_fields}),
    ):
        await audit.record(
            db,
            action,
            actor_user_id=actor_id,
            organisation_id=partner.organisation_id,
            target_type="lead_match",
            target_id=match.id,
            meta=meta,
            details=details,
        )
    await db.flush()
    return Offer(match, lead, category, record)


async def decline(
    db: AsyncSession,
    partner: PartnerOrganisation,
    match_id: uuid.UUID,
    reason: str | None,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
    now: datetime,
) -> tuple[Offer, list[LeadMatch]]:
    """Turn a referral down; the next partner in line may be offered it straight away."""
    offer = await get_offer(db, partner, match_id, lock=True)
    if offer.match.status not in OPEN_MATCH:
        raise _conflict("not_open", "This referral can't be declined now.")
    await _transition(db, offer.match, LeadMatchStatus.DECLINED, actor_id=actor_id, note=reason)
    offer.match.responded_at = now
    await db.flush()
    await audit.record(
        db,
        "lead.declined",
        actor_user_id=actor_id,
        organisation_id=partner.organisation_id,
        target_type="lead_match",
        target_id=offer.match.id,
        meta=meta,
    )
    return offer, await matching.release(db, offer.lead, now=now)


async def record_outcome(
    db: AsyncSession,
    partner: PartnerOrganisation,
    match_id: uuid.UUID,
    to: LeadMatchStatus,
    note: str | None,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> Offer:
    offer = await get_offer(db, partner, match_id, lock=True)
    allowed = OUTCOMES.get(LeadMatchStatus(offer.match.status), ())
    if to not in allowed:
        raise _conflict(
            "invalid_outcome",
            "Record contacted, quoted, won or lost after accepting, in that order.",
        )
    previous = offer.match.status
    await _transition(db, offer.match, to, actor_id=actor_id, note=note)
    if to == LeadMatchStatus.LOST:
        from app.modules.leads import quotes

        await quotes.withdraw_waiting(
            db, offer.match, actor_id=actor_id, now=utcnow(), note="The job was recorded as lost."
        )
    await db.flush()
    await audit.record(
        db,
        "lead.outcome",
        actor_user_id=actor_id,
        organisation_id=partner.organisation_id,
        target_type="lead_match",
        target_id=offer.match.id,
        meta=meta,
        details={"from": previous, "to": to},
    )
    return offer


async def set_preferences(
    db: AsyncSession,
    partner: PartnerOrganisation,
    data: LeadPreferencesIn,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> None:
    changes: dict[str, Any] = {}
    if data.paused is not None and data.paused != partner.paused:
        partner.paused = data.paused
        changes["paused"] = data.paused
    if data.clear_max_open_leads:
        if partner.max_open_leads is not None:
            partner.max_open_leads = None
            changes["max_open_leads"] = None
    elif data.max_open_leads is not None and data.max_open_leads != partner.max_open_leads:
        partner.max_open_leads = data.max_open_leads
        changes["max_open_leads"] = data.max_open_leads
    if changes:
        await db.flush()
        await audit.record(
            db,
            "partner.lead_preferences",
            actor_user_id=actor_id,
            organisation_id=partner.organisation_id,
            target_type="partner",
            target_id=partner.id,
            meta=meta,
            details=changes,
        )


# --- Staff -------------------------------------------------------------------------------


async def prices(db: AsyncSession) -> list[tuple[MarketplaceCategory, LeadPrice | None]]:
    rows = await db.execute(
        select(MarketplaceCategory, LeadPrice)
        .outerjoin(
            LeadPrice,
            (LeadPrice.category_id == MarketplaceCategory.id) & LeadPrice.deactivated_at.is_(None),
        )
        .where(MarketplaceCategory.active.is_(True))
        .order_by(MarketplaceCategory.sort_order)
    )
    return [(c, p) for c, p in rows.all()]


async def _category(db: AsyncSession, key: str) -> MarketplaceCategory:
    category = (
        await db.execute(select(MarketplaceCategory).where(MarketplaceCategory.key == key))
    ).scalar_one_or_none()
    if category is None or not category.active:
        raise not_found("Category")
    return category


async def set_price(
    db: AsyncSession,
    key: str,
    amount_cents: int | None,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
    now: datetime,
) -> None:
    """Replace a category's lead price (``None`` removes it: no fee)."""
    category = await _category(db, key)
    if amount_cents is not None and category.restricted:
        raise ApiError(
            422, "restricted_category", "Referrals in regulated advice are never charged."
        )
    await db.execute(
        update(LeadPrice)
        .where(LeadPrice.category_id == category.id, LeadPrice.deactivated_at.is_(None))
        .values(deactivated_at=now)
    )
    if amount_cents is not None:
        db.add(LeadPrice(category_id=category.id, amount_cents=amount_cents, created_by=actor_id))
    await db.flush()
    await audit.record(
        db,
        "lead.price_set",
        actor_user_id=actor_id,
        target_type="marketplace_category",
        target_id=category.id,
        meta=meta,
        details={"category": key, "amount_cents": amount_cents},
    )


async def staff_leads(
    db: AsyncSession, status_filter: LeadStatus | None, limit: int = 100
) -> list[tuple[Lead, MarketplaceCategory]]:
    query = (
        select(Lead, MarketplaceCategory)
        .join(MarketplaceCategory, MarketplaceCategory.id == Lead.category_id)
        .order_by(Lead.created_at.desc())
        .limit(limit)
    )
    if status_filter is not None:
        query = query.where(Lead.status == status_filter)
    return [(lead, c) for lead, c in await db.execute(query)]


async def staff_matches(
    db: AsyncSession, lead_id: uuid.UUID
) -> list[tuple[LeadMatch, PartnerOrganisation, Organisation, LeadClaim | None]]:
    rows = await db.execute(
        select(LeadMatch, PartnerOrganisation, Organisation, LeadClaim)
        .join(PartnerOrganisation, PartnerOrganisation.id == LeadMatch.partner_organisation_id)
        .join(Organisation, Organisation.id == PartnerOrganisation.organisation_id)
        .outerjoin(LeadClaim, LeadClaim.lead_match_id == LeadMatch.id)
        .where(LeadMatch.lead_id == lead_id)
        .order_by(LeadMatch.rank)
    )
    return [(m, p, o, c) for m, p, o, c in rows.all()]


async def refund_claim(
    db: AsyncSession,
    claim_row: LeadClaim,
    note: str,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
    now: datetime,
) -> None:
    """Give a claimed referral's fee back as credit (a bad lead, a duplicate). The partner
    organisation must be bound."""
    if claim_row.refunded_at is not None:
        raise _conflict("already_refunded", "This referral's fee was already refunded.")
    if claim_row.fee_cents <= 0:
        raise _conflict("no_fee", "This referral had no fee to refund.")
    partner = await _lock_partner(db, claim_row.partner_organisation_id)
    entry = await add_credit_entry(
        db,
        partner,
        kind=CreditKind.REFUND,
        delta_cents=claim_row.fee_cents,
        actor_id=actor_id,
        reference_type="lead_claim",
        reference_id=claim_row.id,
        note=note,
    )
    claim_row.refunded_at = now
    await db.flush()
    await audit.record(
        db,
        "lead.fee_refunded",
        actor_user_id=actor_id,
        organisation_id=partner.organisation_id,
        target_type="lead_claim",
        target_id=claim_row.id,
        meta=meta,
        details={"amount_cents": claim_row.fee_cents, "entry_id": str(entry.id)},
    )


async def adjust_credits(
    db: AsyncSession,
    partner: PartnerOrganisation,
    kind: CreditKind,
    delta_cents: int,
    note: str,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> CreditLedgerEntry:
    if kind not in (CreditKind.PROMO, CreditKind.ADJUSTMENT):
        raise ApiError(422, "invalid_kind", "Staff give credit (PROMO) or correct it (ADJUSTMENT).")
    if delta_cents == 0 or (kind == CreditKind.PROMO and delta_cents < 0):
        raise ApiError(422, "invalid_amount", "Give a positive amount (or correct either way).")
    if partner.verification_status == PartnerStatus.REJECTED and delta_cents > 0:
        raise _conflict("partner_rejected", "This partner wasn't approved.")
    partner = await _lock_partner(db, partner.id)
    entry = await add_credit_entry(
        db, partner, kind=kind, delta_cents=delta_cents, actor_id=actor_id, note=note
    )
    await audit.record(
        db,
        "credits.adjusted",
        actor_user_id=actor_id,
        organisation_id=partner.organisation_id,
        target_type="credit_ledger_entry",
        target_id=entry.id,
        meta=meta,
        details={"kind": kind, "delta_cents": delta_cents},
    )
    return entry
