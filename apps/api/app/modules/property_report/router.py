"""``/v1/organisations/{organisation_id}/properties/{property_id}/report[.pdf]``: the free
property report for a saved property. Free on every account; nothing is stored."""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.api.deps import DbDep, LimiterDep, OrgContext, require_org_permission
from app.modules.entities import service as entities
from app.modules.entities.models import Property
from app.modules.lookups.router import LookupsDep, _throttle
from app.modules.property_report.render import report_pdf
from app.modules.property_report.schemas import PropertyReportOut
from app.modules.property_report.service import Subject, build_report
from app.modules.tenancy.rbac import Perm

router = APIRouter(
    prefix="/v1/organisations/{organisation_id}/properties/{property_id}",
    tags=["property-report"],
)

Read = Annotated[OrgContext, Depends(require_org_permission(Perm.PROJECT_READ))]


async def _report(
    property_id: uuid.UUID, ctx: OrgContext, db: DbDep, lookups: LookupsDep
) -> PropertyReportOut:
    prop = await entities.get_entity(db, Property, ctx.organisation.id, property_id)
    address = (await entities.addresses(db, [prop.address_id]))[prop.address_id]
    subject = Subject(
        property_id=prop.id,
        line1=address.line1,
        line2=address.line2,
        suburb=address.suburb,
        state=address.state,
        postcode=address.postcode,
        latitude=float(address.latitude) if address.latitude is not None else None,
        longitude=float(address.longitude) if address.longitude is not None else None,
        lot_plan=prop.lot_plan,
        land_area_m2=prop.land_area_m2,
        bedrooms=prop.bedrooms,
        bathrooms=prop.bathrooms,
        car_spaces=prop.car_spaces,
        property_type=prop.property_type,
    )
    # Release the database connection before the slow outside lookups.
    await db.commit()
    return await build_report(lookups, subject)


@router.get("/report", response_model=PropertyReportOut)
async def property_report(
    property_id: uuid.UUID, ctx: Read, db: DbDep, limiter: LimiterDep, lookups: LookupsDep
) -> PropertyReportOut:
    """Everything free public data says about the property and its suburb, each figure
    with its source."""
    await _throttle(ctx, limiter)
    return await _report(property_id, ctx, db, lookups)


@router.get("/report.pdf", response_class=Response)
async def property_report_pdf(
    property_id: uuid.UUID, ctx: Read, db: DbDep, limiter: LimiterDep, lookups: LookupsDep
) -> Response:
    await _throttle(ctx, limiter)
    report = await _report(property_id, ctx, db, lookups)
    pdf = await asyncio.to_thread(report_pdf, report)
    name = re.sub(r"[^A-Za-z0-9]+", "-", report.address).strip("-").lower()[:80]
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"content-disposition": f'attachment; filename="property-report-{name}.pdf"'},
    )
