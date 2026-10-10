"""What a partner can do right now: one place that answers it (``standing``), for the
partner's dashboard, the staff screens and, from Milestone 15, lead matching and claiming.

Verification and payment are separate (paying is not being verified):

* the partner must be ``ACTIVE`` (approved by staff, not suspended);
* a category receives referrals only once staff approved it, it is still offered, and, when
  the category requires a credential, the credential named on it is checked and unexpired;
* the plan decides how many categories and service areas count. Every partner has a plan:
  without a paid one it is the free allowance. A paid plan that has fallen past due keeps
  working through the billing grace period (``billing.service.subscription_counts``). When a
  partner has more than the plan allows, the ones approved (or added) first count, so a plan
  ending never deletes anything: the rest wait until the partner upgrades or removes some.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.billing import service as billing
from app.modules.billing.models import Product, ProductKind, Subscription
from app.modules.marketplace.models import MarketplaceCategory
from app.modules.partners.models import (
    PartnerCategory,
    PartnerCategoryStatus,
    PartnerCredential,
    PartnerCredentialStatus,
    PartnerOrganisation,
    PartnerServiceArea,
    PartnerStatus,
)
from app.modules.tenancy.models import MemberStatus, OrganisationMember

CATEGORIES_FEATURE = "partner.categories.max"
SERVICE_AREAS_FEATURE = "partner.service_areas.max"
MEMBERS_FEATURE = "partner.members.max"
# Referrals a month without a lead fee (Milestone 15). Applies whether or not a plan is on
# sale: buying credit is always the way past it.
LEADS_FEATURE = "partner.leads.included"


class Action(StrEnum):
    RECEIVE_REFERRALS = "RECEIVE_REFERRALS"


STATUS_PROBLEMS = {
    PartnerStatus.APPLIED: "We haven't checked your application yet.",
    PartnerStatus.UNDER_REVIEW: "We are checking your application.",
    PartnerStatus.SUSPENDED: "Your partner account is suspended.",
    PartnerStatus.REJECTED: "Your application wasn't approved.",
}


def credential_current(c: PartnerCredential, on: date) -> bool:
    return c.status == PartnerCredentialStatus.VERIFIED and (
        c.expires_on is None or c.expires_on >= on
    )


@dataclass(frozen=True)
class Limit:
    feature: str
    description: str
    limit: int | None  # None: unlimited, or no limit applies yet
    in_use: int


@dataclass(frozen=True)
class Plan:
    name: str
    subscription: Subscription | None
    grace_ends_at: datetime | None
    limits: list[Limit]


@dataclass(frozen=True)
class CategoryStanding:
    row: PartnerCategory
    category: MarketplaceCategory
    counts: bool
    problems: list[str]


@dataclass(frozen=True)
class AreaStanding:
    row: PartnerServiceArea
    counts: bool


@dataclass(frozen=True)
class Standing:
    partner: PartnerOrganisation
    plan: Plan | None
    categories: list[CategoryStanding]
    areas: list[AreaStanding]
    problems: list[str]

    @property
    def receiving_referrals(self) -> bool:
        return not self.problems

    def can(self, action: Action, category_key: str | None = None) -> bool:
        if action == Action.RECEIVE_REFERRALS:
            if not self.receiving_referrals:
                return False
            return category_key is None or any(
                c.counts and c.category.key == category_key for c in self.categories
            )
        return False


async def members_in_use(db: AsyncSession, organisation_id: uuid.UUID) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(OrganisationMember)
                .where(
                    OrganisationMember.organisation_id == organisation_id,
                    OrganisationMember.status == MemberStatus.ACTIVE,
                )
            )
        ).scalar_one()
    )


async def _partner_of(db: AsyncSession, organisation_id: uuid.UUID) -> PartnerOrganisation | None:
    return (
        await db.execute(
            select(PartnerOrganisation).where(
                PartnerOrganisation.organisation_id == organisation_id
            )
        )
    ).scalar_one_or_none()


async def categories_in_use(db: AsyncSession, organisation_id: uuid.UUID) -> int:
    partner = await _partner_of(db, organisation_id)
    if partner is None:
        return 0
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(PartnerCategory)
                .where(
                    PartnerCategory.partner_organisation_id == partner.id,
                    PartnerCategory.status == PartnerCategoryStatus.APPROVED,
                )
            )
        ).scalar_one()
    )


async def areas_in_use(db: AsyncSession, organisation_id: uuid.UUID) -> int:
    partner = await _partner_of(db, organisation_id)
    if partner is None:
        return 0
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(PartnerServiceArea)
                .where(PartnerServiceArea.partner_organisation_id == partner.id)
            )
        ).scalar_one()
    )


async def leads_included_this_month(db: AsyncSession, organisation_id: uuid.UUID) -> int:
    from app.modules.leads import service as leads

    partner = await _partner_of(db, organisation_id)
    if partner is None:
        return 0
    return await leads.included_used(db, partner.id, leads.utcnow())


# Feature key -> how much of it the partner organisation uses now (also shown on the
# organisation's billing page).
USAGE = {
    CATEGORIES_FEATURE: categories_in_use,
    SERVICE_AREAS_FEATURE: areas_in_use,
    MEMBERS_FEATURE: members_in_use,
    LEADS_FEATURE: leads_included_this_month,
}


async def plan(db: AsyncSession, organisation_id: uuid.UUID) -> Plan:
    """The partner organisation's plan and limits. Needs the organisation bound as the
    tenant (subscriptions are tenant rows)."""
    limits: list[Limit] = []
    for key, used in USAGE.items():
        a = await billing.allowance(db, organisation_id, key)
        limit = a.limit if a.enforced or key == LEADS_FEATURE else None
        limits.append(Limit(key, a.description, limit, await used(db, organisation_id)))
    sub = await billing.live_subscription(db, organisation_id)
    name = None
    if sub is not None:
        product = await db.get(Product, sub.product_id)
        if product is not None and product.kind == ProductKind.PARTNER_PLAN:
            name = product.name
        else:
            sub = None
    grace = (
        sub.past_due_since + billing.PAST_DUE_GRACE
        if sub is not None and sub.past_due_since is not None
        else None
    )
    return Plan(name or "Free", sub, grace, limits)


def _limit(p: Plan | None, feature: str) -> int | None:
    if p is None:
        return None
    return next((x.limit for x in p.limits if x.feature == feature), None)


async def standing(
    db: AsyncSession,
    partner: PartnerOrganisation,
    *,
    on: date,
    plan_view: Plan | None,
) -> Standing:
    """Whether the partner receives referrals, category by category. ``plan_view`` is the
    partner's ``plan`` (None when the caller can't read it: no plan limits are applied)."""
    credentials = {
        c.id: c
        for c in (
            await db.execute(
                select(PartnerCredential).where(
                    PartnerCredential.partner_organisation_id == partner.id
                )
            )
        ).scalars()
    }
    rows = list(
        await db.execute(
            select(PartnerCategory, MarketplaceCategory)
            .join(MarketplaceCategory, MarketplaceCategory.id == PartnerCategory.category_id)
            .where(PartnerCategory.partner_organisation_id == partner.id)
            .order_by(
                PartnerCategory.reviewed_at.asc().nulls_last(),
                PartnerCategory.created_at,
            )
        )
    )
    category_limit = _limit(plan_view, CATEGORIES_FEATURE)
    counted = 0
    categories: list[CategoryStanding] = []
    for row, category in rows:
        problems: list[str] = []
        if row.status == PartnerCategoryStatus.PENDING:
            problems.append("Waiting for our check.")
        elif row.status == PartnerCategoryStatus.REJECTED:
            problems.append("Not approved.")
        if not category.active:
            problems.append("We no longer refer this kind of work.")
        if category.requires_credential:
            credential = credentials.get(row.credential_id) if row.credential_id else None
            if credential is None:
                problems.append("Needs a licence or accreditation.")
            elif not credential_current(credential, on):
                problems.append(
                    "Its licence or accreditation has expired."
                    if credential.status == PartnerCredentialStatus.VERIFIED
                    else "Its licence or accreditation hasn't been checked."
                )
        if not problems:
            if category_limit is not None and counted >= category_limit:
                problems.append("Your plan doesn't cover this many categories.")
            else:
                counted += 1
        categories.append(CategoryStanding(row, category, not problems, problems))

    area_rows = list(
        (
            await db.execute(
                select(PartnerServiceArea)
                .where(PartnerServiceArea.partner_organisation_id == partner.id)
                .order_by(PartnerServiceArea.created_at)
            )
        ).scalars()
    )
    area_limit = _limit(plan_view, SERVICE_AREAS_FEATURE)
    areas = [AreaStanding(a, area_limit is None or i < area_limit) for i, a in enumerate(area_rows)]

    blockers: list[str] = []
    if partner.verification_status != PartnerStatus.ACTIVE:
        blockers.append(STATUS_PROBLEMS[PartnerStatus(partner.verification_status)])
    if not any(c.counts for c in categories):
        blockers.append("None of your categories can receive referrals yet.")
    if not any(a.counts for a in areas):
        blockers.append("Add at least one service area.")
    return Standing(partner, plan_view, categories, areas, blockers)
