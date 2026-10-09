"""Lookups: ``/v1/organisations/{organisation_id}/lookups/...``.

Nothing is saved here. The web app uses the answers to fill in the property and vessel
forms, which the customer checks and saves as usual.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import LimiterDep, OrgContext, require_org_permission
from app.core.errors import ApiError, not_found, rate_limited
from app.core.ratelimit import Limit
from app.modules.lookups.amsa import normalise_uvi
from app.modules.lookups.client import LookupUnavailable, unavailable
from app.modules.lookups.qld import CADASTRE_SOURCE, ParcelReport, lga_answer, parse_lot_plan
from app.modules.lookups.schemas import (
    AddressMatchOut,
    AddressSearchOut,
    NotCheckedOut,
    OverlayOut,
    ParcelOut,
    VesselLookupOut,
)
from app.modules.lookups.service import Lookups
from app.modules.tenancy.rbac import Perm

router = APIRouter(prefix="/v1/organisations/{organisation_id}/lookups", tags=["lookups"])

Read = Annotated[OrgContext, Depends(require_org_permission(Perm.PROJECT_READ))]
LOOKUP_LIMIT = Limit("lookup", max_hits=120, window_seconds=60)
AMSA_SOURCE = (
    "Australian Maritime Safety Authority: list of commercial vessels with a vessel permission"
)


def get_lookups(request: Request) -> Lookups:
    lookups: Lookups = request.app.state.lookups
    if not lookups.enabled:
        raise ApiError(503, "lookups_disabled", "Lookups are turned off. Type the details in.")
    return lookups


LookupsDep = Annotated[Lookups, Depends(get_lookups)]


async def _throttle(ctx: OrgContext, limiter: LimiterDep) -> None:
    subject = str(ctx.auth.user.id)
    if await limiter.hit(LOOKUP_LIMIT, subject) > LOOKUP_LIMIT.max_hits:
        raise rate_limited(await limiter.retry_after(LOOKUP_LIMIT, subject))


def parcel_out(p: ParcelReport) -> ParcelOut:
    return ParcelOut(
        lot=p.lot,
        plan=p.plan,
        lot_plan=p.lot_plan,
        lot_plan_label=p.lot_plan_label,
        tenure=p.tenure,
        land_area_m2=p.land_area_m2,
        locality=p.locality,
        local_authority=p.local_authority,
        lga=p.lga,
        parcel_type=p.parcel_type,
        overlays=[
            OverlayOut(
                key=o.key,
                label=o.label,
                group=o.group,
                constraint=o.constraint,
                source_url=o.source_url,
            )
            for o in p.overlays
        ],
        overlays_checked=p.overlays_checked,
        overlays_failed=p.overlays_failed,
        not_checked=[
            NotCheckedOut(label=n.label, why=n.why, where_to_check=n.where_to_check)
            for n in p.not_checked
        ],
        source=p.source,
        source_url=p.source_url,
        retrieved_at=p.retrieved_at,
    )


@router.get("/addresses", response_model=AddressSearchOut)
async def search_addresses(
    ctx: Read,
    limiter: LimiterDep,
    lookups: LookupsDep,
    q: Annotated[str, Query(min_length=3, max_length=200)],
) -> AddressSearchOut:
    """Queensland addresses matching what was typed, each with its lot and plan."""
    await _throttle(ctx, limiter)
    try:
        matches = await lookups.qld.search_addresses(q)
    except LookupUnavailable as exc:
        raise unavailable("The Queensland address service") from exc
    return AddressSearchOut(
        matches=[
            AddressMatchOut(
                address_pid=m.address_pid,
                label=m.label,
                line1=m.line1,
                suburb=m.suburb,
                state=m.state,
                lot_plan=m.lot_plan,
                lot_plan_label=f"Lot {m.lot} on {m.plan}" if m.lot and m.plan else None,
                local_authority=m.local_authority,
                lga=lga_answer(m.local_authority),
                latitude=m.latitude,
                longitude=m.longitude,
            )
            for m in matches
        ],
        source=CADASTRE_SOURCE,
        note="Queensland addresses only. Postcodes aren't in this data, so add yours.",
    )


@router.get("/parcels/{lot_plan}", response_model=ParcelOut)
async def get_parcel(
    lot_plan: str, ctx: Read, limiter: LimiterDep, lookups: LookupsDep
) -> ParcelOut:
    """A Queensland lot and plan: area, tenure, council and the state-mapped overlays it
    touches, and what to check elsewhere (zone, bushfire, flooding, heritage)."""
    await _throttle(ctx, limiter)
    parsed = parse_lot_plan(lot_plan)
    if parsed is None:
        raise ApiError(422, "invalid_lot_plan", "Enter a lot and plan like 'Lot 12 on RP123456'.")
    try:
        report = await lookups.qld.parcel(parsed)
    except LookupUnavailable as exc:
        raise unavailable("The Queensland cadastre service") from exc
    if report is None:
        raise not_found("Lot and plan")
    return parcel_out(report)


@router.get("/vessels/{uvi}", response_model=VesselLookupOut)
async def get_vessel(
    uvi: str, ctx: Read, limiter: LimiterDep, lookups: LookupsDep
) -> VesselLookupOut:
    """A domestic commercial vessel by its UVI, from AMSA's published list."""
    await _throttle(ctx, limiter)
    normalised = normalise_uvi(uvi)
    if normalised is None:
        raise ApiError(422, "invalid_uvi", "A UVI is the letters and numbers AMSA issued.")
    try:
        record, vessels = await lookups.amsa.find(normalised)
    except LookupUnavailable as exc:
        raise unavailable("AMSA's vessel list") from exc
    if record is None:
        raise ApiError(
            404,
            "not_found",
            "That UVI isn't in AMSA's list of vessels with a vessel permission. Check the "
            "number, or enter the vessel's details yourself.",
        )
    return VesselLookupOut(
        uvi=record.uvi,
        name=record.name,
        displayed_identifier=record.displayed_identifier,
        length_m=record.length_m,
        fields=record.fields,
        source=AMSA_SOURCE,
        source_url=vessels.source_url,
        list_retrieved_at=vessels.retrieved_at,
        note="AMSA's list doesn't include certificates of operation. Check the details "
        "against your certificate of survey.",
    )
