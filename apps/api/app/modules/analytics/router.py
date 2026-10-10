"""Marketplace analytics routes (Milestone 16).

* ``GET /v1/organisations/{id}/partner/analytics``: the partner's own referrals (``lead.read``).
* ``GET /v1/organisations/{id}/partner/benchmarks``: other partners' medians, withheld below
  ``ANALYTICS_MIN_PARTNERS`` partners (``lead.read``).
* ``GET /v1/admin/analytics/marketplace``: the whole marketplace for staff (``lead.manage``).

``months`` is 1, 3, 6 or 12 calendar months (Brisbane), counting the current one.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    DbDep,
    OrgContext,
    SettingsDep,
    require_org_permission,
    require_platform_permission,
)
from app.core.errors import ApiError, not_found
from app.modules.analytics import service
from app.modules.analytics.schemas import (
    BenchmarksOut,
    MarketplaceAnalyticsOut,
    PartnerAnalyticsOut,
)
from app.modules.leads.service import utcnow
from app.modules.partners import service as partners
from app.modules.partners.models import PartnerOrganisation
from app.modules.tenancy.models import OrganisationKind
from app.modules.tenancy.rbac import Perm

partner_router = APIRouter(prefix="/v1/organisations/{organisation_id}/partner", tags=["analytics"])
admin_router = APIRouter(prefix="/v1/admin/analytics", tags=["admin: analytics"])

LeadRead = Annotated[OrgContext, Depends(require_org_permission(Perm.LEAD_READ))]
Staff = Annotated[OrgContext, Depends(require_platform_permission(Perm.LEAD_MANAGE))]
MonthsQuery = Annotated[int, Query(ge=1, le=12)]


def _months(months: MonthsQuery = 6) -> int:
    if months not in service.PERIODS:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "bad_period", "Choose 1, 3, 6 or 12 months."
        )
    return months


Months = Annotated[int, Depends(_months)]


async def _partner(ctx: OrgContext, db: DbDep) -> PartnerOrganisation:
    if ctx.organisation.kind != OrganisationKind.PARTNER:
        raise not_found("Partner account")
    return await partners.for_organisation(db, ctx.organisation.id)


@partner_router.get("/analytics", response_model=PartnerAnalyticsOut)
async def partner_analytics(ctx: LeadRead, db: DbDep, months: Months) -> PartnerAnalyticsOut:
    """This partner's referrals over the period: funnel, response, spend, by category,
    area and month."""
    partner = await _partner(ctx, db)
    report = await service.partner_report(db, partner, months=months, now=utcnow())
    return PartnerAnalyticsOut.model_validate(report)


@partner_router.get("/benchmarks", response_model=BenchmarksOut)
async def partner_benchmarks(
    ctx: LeadRead, db: DbDep, settings: SettingsDep, months: Months
) -> BenchmarksOut:
    """Other partners' medians, overall and in this partner's categories; a figure is
    withheld unless enough partners contribute."""
    partner = await _partner(ctx, db)
    out = await service.benchmarks(
        db, partner, months=months, now=utcnow(), k=settings.analytics_min_partners
    )
    return BenchmarksOut.model_validate(out)


@admin_router.get("/marketplace", response_model=MarketplaceAnalyticsOut)
async def marketplace_analytics(ctx: Staff, db: DbDep, months: Months) -> MarketplaceAnalyticsOut:
    """Leads, supply gaps, speed and fees across the marketplace (no customer details)."""
    report = await service.marketplace_report(db, months=months, now=utcnow())
    return MarketplaceAnalyticsOut.model_validate(report)
