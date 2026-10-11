"""Partners to call for each part of a project plan.

For every kind of help a plan's checklist names (a marketplace category), the plan shows:

* partners already introduced to this project in that category (they accepted the
  customer's introduction request), first;
* then up to ``LIMIT`` checked partners who could take it on: the same hard filters lead
  matching uses (``ACTIVE`` and not paused, the category approved with any licence checked
  and current and within the partner's plan, a counted service area covering the project),
  minus the customer's own organisations, nearest first.

Each comes with the business contact details from its partner profile, so the customer can
call them straight away, add a follow-up to the plan, or ask for an introduction through the
usual referral flow (which shares the customer's details only with their consent).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tenant import bind_tenant
from app.modules.leads.matching import normalise_area
from app.modules.leads.models import Lead, LeadClaim
from app.modules.leads.service import _address
from app.modules.marketplace import service as marketplace
from app.modules.marketplace.models import MarketplaceCategory
from app.modules.partners import entitlements
from app.modules.partners.models import (
    PartnerCategory,
    PartnerCategoryStatus,
    PartnerOrganisation,
    PartnerServiceArea,
    PartnerStatus,
    ServiceAreaKind,
)
from app.modules.projects.models import Project
from app.modules.tenancy.models import MemberStatus, Organisation, OrganisationMember

LIMIT = 3
DEFAULT_STATE = "QLD"
FIT = {
    ServiceAreaKind.POSTCODE: (40, "Works in your postcode"),
    ServiceAreaKind.LGA: (30, "Works in your council area"),
    ServiceAreaKind.STATE: (15, "Works across the state"),
}


@dataclass(frozen=True)
class Location:
    state: str
    postcode: str | None
    lga: str | None


@dataclass(frozen=True)
class Suggestion:
    partner_id: uuid.UUID
    name: str
    phone: str | None
    email: str | None
    website: str | None
    description: str | None
    why: str
    introduced: bool


@dataclass(frozen=True)
class CategorySuggestions:
    key: str
    label: str
    description: str
    partners: list[Suggestion]


async def location(db: AsyncSession, project: Project) -> Location:
    address = await _address(db, project)
    if address is None:
        return Location(DEFAULT_STATE, None, None)
    lga = address.lga_code if address.lga_code and not address.lga_code.isdigit() else None
    return Location(address.state or DEFAULT_STATE, address.postcode, lga)


def fit(area: PartnerServiceArea, where: Location) -> tuple[int, str] | None:
    if area.state != where.state:
        return None
    if area.kind == ServiceAreaKind.STATE:
        return FIT[ServiceAreaKind.STATE]
    if area.kind == ServiceAreaKind.POSTCODE and where.postcode and area.value == where.postcode:
        return FIT[ServiceAreaKind.POSTCODE]
    if (
        area.kind == ServiceAreaKind.LGA
        and where.lga
        and normalise_area(area.value) == normalise_area(where.lga)
    ):
        return FIT[ServiceAreaKind.LGA]
    if where.postcode is None and where.lga is None:
        # We don't know where the project is: anyone working in the state might suit.
        return 5, "Works in parts of the state: check they cover your area"
    return None


async def _own_partners(db: AsyncSession, organisation_id: uuid.UUID) -> set[uuid.UUID]:
    members = select(OrganisationMember.user_id).where(
        OrganisationMember.organisation_id == organisation_id,
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
            OrganisationMember.user_id.in_(members),
        )
    )
    return set(rows.scalars())


async def _introduced(db: AsyncSession, project: Project) -> dict[str, list[uuid.UUID]]:
    """Partners who accepted an introduction to this project, by category key."""
    rows = await db.execute(
        select(MarketplaceCategory.key, LeadClaim.partner_organisation_id)
        .join(Lead, Lead.id == LeadClaim.lead_id)
        .join(MarketplaceCategory, MarketplaceCategory.id == Lead.category_id)
        .where(Lead.organisation_id == project.organisation_id, Lead.project_id == project.id)
        .order_by(LeadClaim.created_at)
    )
    out: dict[str, list[uuid.UUID]] = {}
    for key, partner_id in rows.all():
        out.setdefault(key, []).append(partner_id)
    return out


def _suggestion(
    partner: PartnerOrganisation, organisation: Organisation, why: str, *, introduced: bool
) -> Suggestion:
    return Suggestion(
        partner_id=partner.id,
        name=organisation.name,
        phone=partner.phone,
        email=partner.contact_email,
        website=partner.website,
        description=partner.description,
        why=why,
        introduced=introduced,
    )


async def suggestions(
    db: AsyncSession, project: Project, category_keys: list[str], *, on: date
) -> list[CategorySuggestions]:
    """Partners for each category, in the order given. Reads each partner's plan with its
    own organisation bound, then binds the project's organisation again, so call it only
    when nothing is waiting to be written."""
    categories = await marketplace.by_keys(db, category_keys)
    wanted = [categories[k] for k in category_keys if k in categories and categories[k].active]
    if not wanted:
        return []
    where = await location(db, project)
    introduced = await _introduced(db, project)
    excluded = await _own_partners(db, project.organisation_id)
    out: list[CategorySuggestions] = []
    try:
        for category in wanted:
            shown: list[Suggestion] = []
            for partner_id in dict.fromkeys(introduced.get(category.key, [])):
                row = (
                    await db.execute(
                        select(PartnerOrganisation, Organisation)
                        .join(Organisation, Organisation.id == PartnerOrganisation.organisation_id)
                        .where(PartnerOrganisation.id == partner_id)
                    )
                ).one_or_none()
                if row is not None:
                    shown.append(
                        _suggestion(row[0], row[1], "Accepted your introduction", introduced=True)
                    )
            rows = await db.execute(
                select(PartnerOrganisation, Organisation)
                .join(Organisation, Organisation.id == PartnerOrganisation.organisation_id)
                .join(
                    PartnerCategory,
                    PartnerCategory.partner_organisation_id == PartnerOrganisation.id,
                )
                .where(
                    PartnerOrganisation.verification_status == PartnerStatus.ACTIVE,
                    PartnerOrganisation.paused.is_(False),
                    PartnerCategory.category_id == category.id,
                    PartnerCategory.status == PartnerCategoryStatus.APPROVED,
                    PartnerOrganisation.id.in_(
                        select(PartnerServiceArea.partner_organisation_id).where(
                            PartnerServiceArea.state == where.state
                        )
                    ),
                )
                .order_by(Organisation.name, PartnerOrganisation.id)
            )
            ranked: list[tuple[int, str, Suggestion]] = []
            seen = {s.partner_id for s in shown}
            for partner, organisation in rows.all():
                if partner.id in excluded or partner.id in seen:
                    continue
                await bind_tenant(db, partner.organisation_id)
                plan = await entitlements.plan(db, partner.organisation_id)
                standing = await entitlements.standing(db, partner, on=on, plan_view=plan)
                if not standing.can(entitlements.Action.RECEIVE_REFERRALS, category.key):
                    continue
                fits = [f for a in standing.areas if a.counts and (f := fit(a.row, where))]
                if not fits:
                    continue
                points, why = max(fits)
                suggestion = _suggestion(partner, organisation, why, introduced=False)
                ranked.append((-points, organisation.name, suggestion))
            ranked.sort(key=lambda r: (r[0], r[1]))
            shown += [r[2] for r in ranked[:LIMIT]]
            out.append(
                CategorySuggestions(category.key, category.label, category.description, shown)
            )
    finally:
        await bind_tenant(db, project.organisation_id)
    return out


async def partner_contact(
    db: AsyncSession, partner_id: uuid.UUID
) -> tuple[PartnerOrganisation, Organisation] | None:
    """An active partner and its organisation (for a follow-up step)."""
    row = (
        await db.execute(
            select(PartnerOrganisation, Organisation)
            .join(Organisation, Organisation.id == PartnerOrganisation.organisation_id)
            .where(
                PartnerOrganisation.id == partner_id,
                PartnerOrganisation.verification_status == PartnerStatus.ACTIVE,
            )
        )
    ).one_or_none()
    return (row[0], row[1]) if row else None
