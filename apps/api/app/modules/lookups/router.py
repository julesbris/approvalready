"""Lookups: ``/v1/organisations/{organisation_id}/lookups/...``.

Nothing is saved here. The web app uses the answers to fill in the property and vessel
forms, which the customer checks and saves as usual.
"""

from __future__ import annotations

import asyncio
import re
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import LimiterDep, OrgContext, require_org_permission
from app.core.errors import ApiError, not_found, rate_limited
from app.core.ratelimit import Limit
from app.modules.lookups.abs import POSTCODE_SOURCE
from app.modules.lookups.amsa import normalise_uvi
from app.modules.lookups.client import LookupUnavailable, unavailable
from app.modules.lookups.listing import ListingDetails, parse_listing_url
from app.modules.lookups.schemas import (
    AddressMatchOut,
    AddressSearchOut,
    ListingDetailsOut,
    ListingImportOut,
    ListingIn,
    NotCheckedOut,
    OverlayOut,
    ParcelOut,
    VesselLookupOut,
)
from app.modules.lookups.service import Lookups
from app.modules.lookups.spatial import STATES, AddressMatch, ParcelReport, StateSpatial
from app.modules.lookups.which_state import state_in_text
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


async def _postcode(lookups: Lookups, m: AddressMatch) -> str | None:
    if m.postcode:
        return m.postcode
    if m.latitude is None or m.longitude is None:
        return None
    return await lookups.postcodes.postcode_at(m.latitude, m.longitude)


async def _matches_out(lookups: Lookups, matches: list[AddressMatch]) -> list[AddressMatchOut]:
    """Matches with their postcode: the state's own where its address data has one, else
    the ABS postal area each one sits in."""
    postcodes = await asyncio.gather(*(_postcode(lookups, m) for m in matches))
    return [
        AddressMatchOut(
            address_pid=m.address_pid,
            label=m.label,
            line1=m.line1,
            suburb=m.suburb,
            state=m.state,
            postcode=postcode,
            lot_plan=m.lot_plan,
            lot_plan_label=m.lot_plan_label,
            local_authority=m.local_authority,
            lga=m.lga,
            latitude=m.latitude,
            longitude=m.longitude,
        )
        for m, postcode in zip(matches, postcodes, strict=True)
    ]


def parcel_out(p: ParcelReport) -> ParcelOut:
    return ParcelOut(
        lot=p.lot,
        plan=p.plan,
        lot_plan=p.lot_plan,
        lot_plan_label=p.lot_plan_label,
        state=p.state,
        zone=p.zone,
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


def _states_in_reach(lookups: Lookups) -> str:
    names = [STATES[code] for code in lookups.states]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


async def search_in_states(
    lookups: Lookups, query: str, state: str | None, limit: int = 8
) -> tuple[list[AddressMatch], list[StateSpatial]]:
    """Addresses matching what was typed, in the state given or named in the text, else in
    every state we cover (best matches of each, in turn). Also returns the states that
    didn't answer; raises ``LookupUnavailable`` only when none did."""
    wanted = lookups.for_state(state or state_in_text(query))
    services = [wanted] if wanted else list(lookups.states.values())
    results = await asyncio.gather(
        *(s.search_addresses(query, limit) for s in services), return_exceptions=True
    )
    failed = [s for s, r in zip(services, results, strict=True) if isinstance(r, BaseException)]
    found = [r for r in results if not isinstance(r, BaseException)]
    if failed and not found:
        raise LookupUnavailable(f"{', '.join(s.state for s in failed)} didn't answer")
    # Interleave so the best match of each state comes first.
    merged: list[AddressMatch] = []
    for i in range(limit):
        merged += [r[i] for r in found if i < len(r)]
    return merged[:limit], failed


@router.get("/addresses", response_model=AddressSearchOut)
async def search_addresses(
    ctx: Read,
    limiter: LimiterDep,
    lookups: LookupsDep,
    q: Annotated[str, Query(min_length=3, max_length=200)],
    state: Annotated[str | None, Query(pattern=r"^[A-Za-z]{2,3}$")] = None,
) -> AddressSearchOut:
    """Addresses matching what was typed, each with its parcel (lot and plan) and council."""
    await _throttle(ctx, limiter)
    try:
        matches, failed = await search_in_states(lookups, q, state)
    except LookupUnavailable as exc:
        raise unavailable("The address service") from exc
    in_reach = {m.state for m in matches} or set(lookups.states)
    sources = "; ".join(lookups.states[c].source for c in lookups.states if c in in_reach)
    note = (
        f"{_states_in_reach(lookups)} addresses only. Postcodes come from ABS postal areas "
        "where the state's address data has none: check yours."
    )
    if failed:
        names = ", ".join(STATES[s.state] for s in failed)
        note += f" {names} didn't answer just now, so its addresses may be missing."
    return AddressSearchOut(
        matches=await _matches_out(lookups, matches),
        source=f"{sources}; postcodes: {POSTCODE_SOURCE}",
        note=note,
    )


# ``path``: NSW ("1//DP123456") and Tasmanian ("142916/1") parcel ids contain slashes.
@router.get("/parcels/{lot_plan:path}", response_model=ParcelOut)
async def get_parcel(
    lot_plan: str,
    ctx: Read,
    limiter: LimiterDep,
    lookups: LookupsDep,
    state: Annotated[str, Query(pattern=r"^[A-Za-z]{2,3}$")] = "QLD",
) -> ParcelOut:
    """A parcel (lot and plan): area, tenure, council and the state-mapped overlays it
    touches, and what to check elsewhere (zone, bushfire, flooding, heritage)."""
    await _throttle(ctx, limiter)
    spatial = lookups.for_state(state)
    if spatial is None:
        raise ApiError(
            422, "state_not_covered", f"We look up {_states_in_reach(lookups)} parcels only."
        )
    parsed = spatial.parse_parcel_id(lot_plan)
    if parsed is None:
        raise ApiError(422, "invalid_lot_plan", "Enter the lot and plan as your title shows it.")
    try:
        report = await spatial.parcel(parsed)
    except LookupUnavailable as exc:
        raise unavailable(f"The {STATES[spatial.state]} cadastre service") from exc
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


def _details_out(d: ListingDetails) -> ListingDetailsOut:
    return ListingDetailsOut(
        bedrooms=d.bedrooms,
        bathrooms=d.bathrooms,
        car_spaces=d.car_spaces,
        property_type=d.property_type,
        price_text=d.price_text,
        headline=d.headline,
        status=d.status,
        objective=d.objective,
    )


@router.post("/listing", response_model=ListingImportOut)
async def import_listing(
    body: ListingIn, ctx: Read, limiter: LimiterDep, lookups: LookupsDep
) -> ListingImportOut:
    """What a pasted listing link gives us: the address read from the link itself (no
    listing page is fetched), Queensland addresses matching it, and, for a Domain link when
    the server has a Domain API key, the listing's details from Domain's API."""
    await _throttle(ctx, limiter)
    link = parse_listing_url(body.url)
    if link is None:
        raise ApiError(422, "invalid_link", "Paste the whole link to the listing.")
    details: ListingDetails | None = None
    notes: list[str] = []
    if link.listing_id and link.site.key == "domain":
        if lookups.domain.enabled:
            try:
                details = await lookups.domain.listing(link.listing_id)
            except LookupUnavailable:
                notes.append("Domain didn't answer just now, so only the address came across.")
        else:
            notes.append("Bedrooms and price from Domain aren't switched on yet.")
    search = details.address if details and details.address else link.address_text
    link_state = link.state or (state_in_text(search) if search else None)
    street_part = re.split(r"\s(?:QLD|NSW|VIC|WA|SA|TAS|ACT|NT)\b", search or "")[0]
    has_street = bool(search and any(c.isdigit() for c in street_part))
    covered = link_state is None or lookups.for_state(link_state) is not None
    matches: list[AddressMatch] = []
    if search and has_street and covered:
        try:
            matches, _ = await search_in_states(lookups, search, link_state)
        except LookupUnavailable:
            notes.append("The address service didn't answer. Search for the address.")
    if not covered:
        notes.append(
            f"We look up {_states_in_reach(lookups)} addresses only for now. Type the address in."
        )
    elif not search:
        notes.append("This link doesn't include the address. Search for it below.")
    elif not has_street:
        notes.append(
            f"This link only gives the suburb ({link.suburb or search}). Search for the "
            "street address below."
        )
    elif not matches:
        notes.append("We couldn't match that address. Search for it below.")
    else:
        notes.append("Pick the matching address to fill in the rest.")
    return ListingImportOut(
        site=link.site.key,
        site_name=link.site.name,
        how=link.site.how.format(name=link.site.name),
        url=link.url,
        address_text=search,
        property_type=(details.property_type if details else None) or link.property_type,
        details=_details_out(details) if details else None,
        matches=await _matches_out(lookups, matches),
        note=" ".join(notes),
    )
