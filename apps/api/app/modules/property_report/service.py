"""The free property report: everything free public data says about a property and its
suburb, well beyond prices and comparable sales.

It is built on request from the saved property (address, lot and plan, bedrooms) and the
sources in ``sources.py``, all fetched at once. Each section says where its figures come
from and how current they are; a source that doesn't answer leaves its section marked
"couldn't be checked" without stopping the rest. Prices and comparable sales are the one
thing we don't copy: the listing sites' terms forbid it, so the report links to the free
places to look them up instead.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.modules.councils.directory import for_local_authority
from app.modules.lookups.client import LookupUnavailable
from app.modules.lookups.service import Lookups
from app.modules.lookups.spatial import AddressMatch, NotChecked, ParcelReport
from app.modules.property_report.schemas import (
    PropertyReportOut,
    ReportFact,
    ReportItem,
    ReportLink,
    ReportSection,
    ReportSource,
)
from app.modules.property_report.sources import (
    QLD_CENSUS,
    CrimeRates,
    Place,
    School,
    Suburb,
)

DISCLAIMER = (
    "This report gathers free public information about the property and its area. It is "
    "general information, not financial, legal or planning advice, and not a valuation. "
    "Mapping shows what a government map says, not a final determination: check anything "
    "important with the council, a solicitor or conveyancer, or a building inspector "
    "before you buy, sell or rent."
)
ABS_QUICKSTATS = "https://abs.gov.au/census/find-census-data/quickstats/2021/SAL{code}"
ABS_SOURCE = "Australian Bureau of Statistics, Census of Population and Housing 2021"
SCHOOLS_SOURCE = (
    "Queensland Department of Education school catchments and school locations; "
    "Non-State Schools Accreditation Board"
)
SCHOOLS_URL = "https://schoolsdirectory.eq.edu.au/"
CATCHMENT_URL = "https://www.qld.gov.au/education/schools/find/enrolment/catchment"
FLOOD_URL = "https://floodcheck.information.qld.gov.au/"
QPS_SOURCE = "Queensland Police Service, reported offence rates by council area (open data)"
QPS_URL = "https://www.police.qld.gov.au/maps-and-statistics"
OSM_SOURCE = "OpenStreetMap (© OpenStreetMap contributors, ODbL)"
OSM_URL = "https://www.openstreetmap.org/copyright"
CADASTRE_URL = "https://qldglobe.information.qld.gov.au/"
# Where anyone can see a state's land and planning maps, for the states we look up.
STATE_MAP_URLS = {
    "QLD": CADASTRE_URL,
    "NSW": "https://www.planningportal.nsw.gov.au/spatialviewer/",
}
STATE_HAZARDS_INTRO = {
    "NSW": "Zoning, heritage, bush fire prone land, flood planning areas and the coastal "
    "use area mapped by the NSW Government over this land.",
}


@dataclass(frozen=True)
class Subject:
    """The property the report is about, from the saved property record."""

    property_id: uuid.UUID
    line1: str
    line2: str | None
    suburb: str
    state: str
    postcode: str
    latitude: float | None
    longitude: float | None
    lot_plan: str | None
    land_area_m2: Decimal | None
    bedrooms: int | None
    bathrooms: int | None
    car_spaces: int | None
    property_type: str | None

    @property
    def address(self) -> str:
        return ", ".join(
            p for p in (self.line1, self.line2, f"{self.suburb} {self.state} {self.postcode}") if p
        )


def money(value: float | None, per: str) -> str | None:
    return f"${value:,.0f} {per}" if value else None


def _vs(value: float | None, qld: float | None, unit: str = "") -> str | None:
    if not value or not qld:
        return None
    diff = round(100 * (value - qld) / qld)
    if abs(diff) < 3:
        return f"About the same as Queensland ({unit}{qld:,.0f})"
    word = "above" if diff > 0 else "below"
    return f"{abs(diff)}% {word} Queensland ({unit}{qld:,.0f})"


def _pct_vs(value: float | None, qld: float | None) -> str | None:
    if value is None or qld is None:
        return None
    return f"Queensland: {qld:g}%"


def distance_words(metres: int) -> str:
    if metres < 1000:
        return f"{round(metres / 10) * 10} m"
    return f"{metres / 1000:.1f} km"


def _today() -> str:
    return datetime.now(UTC).strftime("checked %d %B %Y").replace(" 0", " ")


def land_section(
    subject: Subject, parcel: ParcelReport | None, council: str | None
) -> ReportSection:
    facts = [ReportFact(label="Address", value=subject.address)]
    lot_plan = parcel.lot_plan_label if parcel else subject.lot_plan
    if lot_plan:
        facts.append(ReportFact(label="Lot and plan", value=lot_plan))
    area = parcel.land_area_m2 if parcel and parcel.land_area_m2 else subject.land_area_m2
    if area:
        facts.append(ReportFact(label="Land area", value=f"{Decimal(area).normalize():,f} m²"))
    if parcel and parcel.tenure:
        facts.append(ReportFact(label="Tenure", value=parcel.tenure))
    if parcel and parcel.zone:
        facts.append(
            ReportFact(
                label="Zone",
                value=parcel.zone,
                note="From the state's planning maps. The council's planning certificate is "
                "the official statement.",
            )
        )
    if council:
        facts.append(ReportFact(label="Council", value=council))
    home = [
        f"{subject.bedrooms} bed" if subject.bedrooms is not None else None,
        f"{subject.bathrooms} bath" if subject.bathrooms is not None else None,
        f"{subject.car_spaces} car" if subject.car_spaces is not None else None,
    ]
    if subject.property_type or any(home):
        value = ", ".join(p for p in home if p)
        if subject.property_type:
            value = f"{subject.property_type}{': ' + value if value else ''}"
        facts.append(ReportFact(label="The home", value=value))
    sources = []
    if parcel:
        url = STATE_MAP_URLS.get(parcel.state, CADASTRE_URL)
        sources.append(ReportSource(name=parcel.source, url=url, as_at=_today()))
    return ReportSection(
        key="land",
        title="The land",
        intro="The property as the state's land records describe it.",
        status="ok" if parcel or subject.state not in STATE_MAP_URLS else "partial",
        facts=facts,
        sources=sources,
    )


def hazards_section(
    parcel: ParcelReport | None, parcel_failed: bool, flood: bool | None, state: str = "QLD"
) -> ReportSection:
    items = []
    if parcel:
        items = [
            ReportItem(label=o.label, detail=o.group, url=o.source_url) for o in parcel.overlays
        ]
    if flood:
        items.append(
            ReportItem(
                label="Inside the 1% annual chance flood extent of a state basin flood study",
                detail="A 1 in 100 chance each year of a flood this big. Ask the council for "
                "its own flood mapping and flood levels.",
                url=FLOOD_URL,
            )
        )
    not_checked: list[NotChecked] = list(parcel.not_checked) if parcel else []
    facts = []
    if parcel is not None or flood is not None:
        facts.append(
            ReportFact(
                label="State mapping",
                value=f"{len(items)} found" if items else "Nothing found on the state maps checked",
                note="Not shown on a map doesn't mean it can't apply.",
            )
        )
    status = "ok"
    qld = state == "QLD"
    if parcel_failed or (parcel and parcel.overlays_failed) or (flood is None and qld):
        status = "partial"
    if parcel is None and (flood is None or not qld):
        status = "unavailable"
    if not qld:
        return ReportSection(
            key="hazards",
            title="Planning and hazards",
            intro=STATE_HAZARDS_INTRO.get(state, "Hazards mapped by the state over this land."),
            status=status,
            facts=facts,
            items=items,
            links=[
                ReportLink(label=n.label, url=n.where_to_check, why=n.why)
                for n in not_checked
                if n.where_to_check
            ],
            sources=[
                ReportSource(name=parcel.source, url=STATE_MAP_URLS.get(state, ""), as_at=_today())
            ]
            if parcel
            else [],
        )
    return ReportSection(
        key="hazards",
        title="Planning and hazards",
        intro="Flooding, storm tide, erosion, protected vegetation and heritage mapped by "
        "the Queensland Government over this land.",
        status=status,
        facts=facts,
        items=items,
        links=[
            ReportLink(label=n.label, url=n.where_to_check, why=n.why)
            for n in not_checked
            if n.where_to_check
        ],
        sources=[
            ReportSource(
                name="Queensland Government spatial mapping (coastal hazards, vegetation, "
                "heritage) and FloodCheck basin flood studies",
                url=FLOOD_URL,
                as_at=_today(),
            )
        ],
    )


def schools_section(
    catchments: list[tuple[str, str]] | None, schools: list[School] | None
) -> ReportSection:
    facts = [
        ReportFact(label=f"{level} state school catchment", value=name)
        for level, name in catchments or []
    ]
    if catchments == []:
        facts.append(
            ReportFact(
                label="State school catchments",
                value="Not inside a mapped catchment",
                note="Many schools have no catchment: they take local children first.",
            )
        )
    items = [
        ReportItem(
            label=s.name,
            detail=s.kind + (f", years {s.years}" if s.years else ""),
            distance_m=s.distance_m,
        )
        for s in (schools or [])[:12]
    ]
    status = "ok"
    if catchments is None or schools is None:
        status = "partial" if (catchments is not None or schools is not None) else "unavailable"
    return ReportSection(
        key="schools",
        title="Schools",
        intro="The state school catchments this address is in, and schools within 3 km "
        "(straight-line distance).",
        status=status,
        facts=facts,
        items=items,
        links=[
            ReportLink(
                label="Check catchments and enrolment",
                url=CATCHMENT_URL,
                why="Catchments change; confirm with the school before you rely on one.",
            ),
            ReportLink(
                label="Queensland schools directory",
                url=SCHOOLS_URL,
                why="Each state school's contacts, year levels and programs.",
            ),
            ReportLink(
                label="My School",
                url="https://www.myschool.edu.au/",
                why="NAPLAN results, enrolments and funding for every school.",
            ),
        ],
        sources=[ReportSource(name=SCHOOLS_SOURCE, url=CATCHMENT_URL, as_at=_today())],
    )


def places_section(places: list[Place] | None) -> ReportSection:
    items = [
        ReportItem(
            label=p.label,
            detail=(f"Nearest: {p.nearest_name}. " if p.nearest_name else "")
            + f"{p.count} within 2 km",
            distance_m=p.nearest_m,
        )
        for p in sorted(places or [], key=lambda p: p.nearest_m)
    ]
    return ReportSection(
        key="nearby",
        title="Getting around and nearby",
        intro="Shops, transport, health, parks and more within 2 km (straight-line "
        "distance to the nearest of each).",
        status="ok" if places is not None else "unavailable",
        facts=[]
        if places is None or items
        else [ReportFact(label="Within 2 km", value="Nothing mapped")],
        items=items,
        links=[
            ReportLink(
                label="Translink journey planner",
                url="https://jp.translink.com.au/plan-your-journey/journey-planner",
                why="Public transport times from the address (South East Queensland and "
                "regional services).",
            )
        ],
        sources=[ReportSource(name=OSM_SOURCE, url=OSM_URL, as_at=_today())],
    )


def people_section(suburb: Suburb | None, census: dict[str, Any] | None) -> ReportSection:
    c = census or {}
    facts: list[ReportFact] = []

    def add(
        label: str, value: str | None, compare: str | None = None, note: str | None = None
    ) -> None:
        if value:
            facts.append(ReportFact(label=label, value=value, compare=compare, note=note))

    if c.get("population"):
        density = None
        if suburb and suburb.area_km2:
            density = f"{c['population'] / suburb.area_km2:,.0f} people per km²"
        add("People", f"{c['population']:,}", None, density)
    if c.get("median_age"):
        add("Median age", f"{c['median_age']:g}", f"Queensland: {QLD_CENSUS['median_age']}")
    add(
        "Median household income",
        money(c.get("household_income"), "a week"),
        _vs(c.get("household_income"), QLD_CENSUS["household_income"], "$"),
    )
    add(
        "Median personal income",
        money(c.get("personal_income"), "a week"),
        _vs(c.get("personal_income"), QLD_CENSUS["personal_income"], "$"),
    )
    if c.get("household_size"):
        add(
            "Average household",
            f"{c['household_size']:g} people",
            f"Queensland: {QLD_CENSUS['household_size']}",
        )
    for key, label in (
        ("owned_outright", "Homes owned outright"),
        ("owned_mortgage", "Homes owned with a mortgage"),
        ("rented", "Homes rented"),
        ("separate_house", "Separate houses"),
        ("semi_detached", "Townhouses, terraces and semis"),
        ("flat", "Units and apartments"),
    ):
        if c.get(key) is not None:
            add(label, f"{c[key]:g}%", _pct_vs(c[key], QLD_CENSUS[key]))
    items = [
        ReportItem(label=f"Aged {label}", detail=f"{share:g}% of people")
        for label, share in c.get("age_groups") or []
    ]
    links = []
    sources = []
    if suburb:
        url = ABS_QUICKSTATS.format(code=suburb.code)
        links.append(
            ReportLink(
                label=f"Census QuickStats for {suburb.name}",
                url=url,
                why="Everything else the census says: jobs, travel to work, languages, "
                "family types and more.",
            )
        )
        sources.append(ReportSource(name=ABS_SOURCE, url=url, as_at="Census 2021"))
    return ReportSection(
        key="people",
        title=f"Who lives in {suburb.name}" if suburb else "Who lives here",
        intro="The suburb at the 2021 Census (the latest; the next is in 2026), compared "
        "with Queensland.",
        status="ok" if census else "unavailable",
        facts=facts,
        items=items,
        links=links,
        sources=sources,
    )


def _slug(text: str) -> str:
    return "-".join(text.lower().split())


def market_section(subject: Subject, census: dict[str, Any] | None) -> ReportSection:
    c = census or {}
    facts = []
    if c.get("rent"):
        facts.append(
            ReportFact(
                label="Median rent (Census 2021)",
                value=money(c["rent"], "a week") or "",
                compare=_vs(c["rent"], QLD_CENSUS["rent"], "$"),
                note="Rents have risen since 2021: check today's in the RTA's median rents.",
            )
        )
    if c.get("mortgage"):
        facts.append(
            ReportFact(
                label="Median mortgage repayment (Census 2021)",
                value=money(c["mortgage"], "a month") or "",
                compare=_vs(c["mortgage"], QLD_CENSUS["mortgage"], "$"),
            )
        )
    if c.get("persons_per_bedroom"):
        facts.append(ReportFact(label="People per bedroom", value=f"{c['persons_per_bedroom']:g}"))
    place = f"{_slug(subject.suburb)}-{subject.state.lower()}-{subject.postcode}"
    links = [
        ReportLink(
            label="Domain suburb profile",
            url=f"https://www.domain.com.au/suburb-profile/{place}",
            why="Median prices, days on market and recent sales for the suburb.",
        ),
        ReportLink(
            label="realestate.com.au suburb profile",
            url=f"https://www.realestate.com.au/neighbourhoods/"
            f"{_slug(subject.suburb)}-{subject.postcode}-{subject.state.lower()}",
            why="Median prices, rental yield and sold properties nearby.",
        ),
        ReportLink(
            label="Sold prices at this address and nearby",
            url="https://www.propertyvalue.com.au/",
            why="Free sale history and a price estimate (CoreLogic data).",
        ),
        ReportLink(
            label="RTA median rents",
            url="https://www.rta.qld.gov.au/forms-resources/median-rents-quick-finder",
            why="Today's median weekly rent by postcode and number of bedrooms, from bonds "
            "lodged in Queensland.",
        ),
        ReportLink(
            label="SQM Research vacancy rates",
            url=f"https://sqmresearch.com.au/graph_vacancy.php?postcode={subject.postcode}",
            why="How many rentals are empty in the postcode, and asking rents.",
        ),
    ]
    if subject.state == "QLD":
        links.append(
            ReportLink(
                label="Land valuation (Queensland Valuer-General)",
                url="https://www.qld.gov.au/landvaluation",
                why="The site value the council's rates and land tax are based on.",
            )
        )
    return ReportSection(
        key="market",
        title="Prices, rent and mortgages",
        intro="What people in the suburb pay, and where to see sale prices and comparable "
        "sales free. We link to these rather than copy them: the listing sites' terms "
        "don't allow it.",
        status="ok" if census else "partial",
        facts=facts,
        links=links,
        sources=[
            ReportSource(name=ABS_SOURCE, url="https://www.abs.gov.au/census", as_at="Census 2021")
        ]
        if census
        else [],
    )


def safety_section(crime: CrimeRates | None, council: str | None) -> ReportSection:
    facts = []
    for label, area_rate, qld_rate in crime.rates if crime else []:
        compare = None
        if qld_rate:
            diff = round(100 * (area_rate - qld_rate) / qld_rate)
            compare = (
                f"About the same as Queensland ({qld_rate:,})"
                if abs(diff) < 5
                else f"{abs(diff)}% {'above' if diff > 0 else 'below'} Queensland ({qld_rate:,})"
            )
        facts.append(
            ReportFact(label=label, value=f"{area_rate:,} per 100,000 people", compare=compare)
        )
    return ReportSection(
        key="safety",
        title="Reported crime",
        intro=(
            f"Offences reported to police in the {crime.area} area, {crime.period}, per "
            "100,000 people. These cover the whole council area, not just this street."
            if crime
            else "Offences reported to police in the council area, per 100,000 people."
        ),
        status="ok" if crime else "unavailable",
        facts=facts,
        links=[
            ReportLink(
                label="QPS online crime map",
                url="https://qps-ocm.s3-ap-southeast-2.amazonaws.com/index.html",
                why="Offences reported near the address, street by street.",
            )
        ],
        sources=[ReportSource(name=QPS_SOURCE, url=QPS_URL, as_at=crime.period)] if crime else [],
    )


def checks_section(subject: Subject, council_url: str | None) -> ReportSection:
    unit = (subject.property_type or "").lower() in {
        "unit",
        "apartment",
        "townhouse",
        "villa",
        "studio",
    }
    links = [
        ReportLink(
            label="Internet: NBN at the address",
            url="https://www.nbnco.com.au/learn/rollout-map",
            why="Which NBN connection the address has (fibre, fixed wireless or other).",
        ),
        ReportLink(
            label="Mobile coverage",
            url="https://www.telstra.com.au/coverage-networks/our-coverage",
            why="Check each carrier's coverage map for the address.",
        ),
        ReportLink(
            label="Title search",
            url="https://www.titlesqld.com.au/title-searches/",
            why="Who owns it, mortgages, easements and covenants on the title.",
        ),
        ReportLink(
            label="Building and pest inspection",
            url="https://www.qbcc.qld.gov.au/your-property/you-buy-sell",
            why="Termites, structure and defects: book a licensed inspector before you "
            "sign or make your contract subject to one.",
        ),
        ReportLink(
            label="Pool safety",
            url="https://qbcc.qld.gov.au/home-owner-hub/swimming-pools/buy-sell-lease-property-pool",
            why="A pool needs a pool safety certificate when the property is sold or leased.",
        )
        if subject.state == "QLD"
        else None,
        ReportLink(
            label="Body corporate records",
            url="https://www.qld.gov.au/housing/body-corporate/legislation-and-bccm/buying-into",
            why="Levies, sinking fund, disputes and by-laws: get a body corporate search.",
        )
        if unit and subject.state == "QLD"
        else None,
        ReportLink(
            label="Council rates, approvals and flood maps",
            url=council_url,
            why="Rates, building approvals on record, and the council's own flood and zone "
            "mapping.",
        )
        if council_url
        else None,
    ]
    return ReportSection(
        key="checks",
        title="Before you buy or rent: other checks",
        intro="Things no free data source answers. Each link goes to the official or best "
        "free place to check.",
        status="ok",
        links=[link for link in links if link is not None],
    )


def headline(
    parcel: ParcelReport | None,
    flood: bool | None,
    catchments: list[tuple[str, str]] | None,
    census: dict[str, Any] | None,
    places: list[Place] | None,
) -> list[str]:
    out = []
    if parcel and parcel.land_area_m2:
        out.append(
            f"{Decimal(parcel.land_area_m2).normalize():,f} m² of land, {parcel.lot_plan_label}."
        )
    found = [o.label for o in parcel.overlays] if parcel else []
    if flood:
        found.append("a state basin flood study's 1% flood extent")
    if found:
        out.append("State mapping shows: " + "; ".join(found) + ".")
    elif parcel is not None:
        out.append(
            "No flooding, storm tide, vegetation or heritage mapping found on the state maps."
        )
    if catchments:
        out.append("In the catchment for " + " and ".join(name for _, name in catchments) + ".")
    if census and census.get("household_income"):
        compare = _vs(census["household_income"], QLD_CENSUS["household_income"], "$")
        out.append(
            f"Median household income {money(census['household_income'], 'a week')}"
            + (f", {compare[0].lower()}{compare[1:]}" if compare else "")
            + " (Census 2021)."
        )
    near = {p.key: p for p in places or []}
    bits = [
        f"{label} {distance_words(near[key].nearest_m)}"
        for key, label in (("supermarket", "supermarket"), ("bus", "bus stop"), ("park", "park"))
        if key in near
    ]
    if bits:
        out.append("Nearest " + ", ".join(bits) + ".")
    return out


async def _parcel(
    lookups: Lookups, state: str, lot_plan: str | None
) -> tuple[ParcelReport | None, bool]:
    spatial = lookups.for_state(state)
    parsed = spatial.parse_parcel_id(lot_plan) if spatial and lot_plan else None
    if spatial is None or parsed is None:
        return None, False
    try:
        return await spatial.parcel(parsed), False
    except LookupUnavailable:
        return None, True


async def _locate(lookups: Lookups, subject: Subject) -> AddressMatch | None:
    spatial = lookups.for_state(subject.state)
    if spatial is None:
        return None
    try:
        return await spatial.match_address(subject.line1, subject.suburb)
    except LookupUnavailable:
        return None


async def _none() -> None:
    return None


# The browser's request gives up after 15 seconds, so the report never waits longer than
# this for its sources: anything slower is shown as "couldn't be checked just now".
BUDGET_SECONDS = 12.5


async def _within[T](aw: Awaitable[T], seconds: float, default: T) -> T:
    try:
        return await asyncio.wait_for(aw, max(seconds, 0.5))
    except TimeoutError:
        return default


async def build_report(lookups: Lookups, subject: Subject) -> PropertyReportOut:
    started = time.monotonic()
    qld = subject.state == "QLD"
    if qld:
        lookups.crime.warm()
    mapped = lookups.for_state(subject.state) is not None
    lat, lon, lot_plan = subject.latitude, subject.longitude, subject.lot_plan
    local_authority = None
    if mapped and (lat is None or lot_plan is None):
        match = await _within(_locate(lookups, subject), 5, None)
        if match:
            lat = lat if lat is not None else match.latitude
            lon = lon if lon is not None else match.longitude
            lot_plan = lot_plan or match.lot_plan
            local_authority = match.local_authority
    located = lat is not None and lon is not None
    y, x = (lat or 0.0), (lon or 0.0)  # only used when located
    budget = BUDGET_SECONDS - 3.5 - (time.monotonic() - started)
    (parcel, parcel_failed), suburb, catchments, schools, flood, places = await asyncio.gather(
        _within(_parcel(lookups, subject.state, lot_plan), budget, (None, True))
        if mapped
        else _none_pair(),
        _within(lookups.census.suburb_at(y, x), budget, None) if located else _none(),
        _within(lookups.schools.catchments(y, x), budget, None) if located and qld else _none(),
        _within(lookups.schools.schools_near(y, x), budget, None) if located and qld else _none(),
        _within(lookups.schools.in_basin_flood_extent(y, x), budget, None)
        if located and qld
        else _none(),
        _within(lookups.places.places(y, x), budget, None) if located else _none(),
    )
    local_authority = (parcel.local_authority if parcel else None) or local_authority
    council = for_local_authority(local_authority, subject.state)
    council_name = council.name if council else local_authority
    budget = BUDGET_SECONDS - (time.monotonic() - started)
    census, crime = await asyncio.gather(
        _within(lookups.census.profile(suburb.code), budget, None) if suburb and qld else _none(),
        _within(lookups.crime.rates(local_authority), budget, None) if qld else _none(),
    )
    sections = [
        land_section(subject, parcel, council_name),
        hazards_section(parcel, parcel_failed, flood, subject.state),
        schools_section(catchments, schools),
        places_section(places),
        people_section(suburb, census),
        market_section(subject, census),
        safety_section(crime, council_name),
        checks_section(subject, council.website if council else None),
    ]
    if not qld:
        kept = {"land", "nearby", "market", "checks"} | ({"hazards"} if mapped else set())
        sections = [s for s in sections if s.key in kept]
    return PropertyReportOut(
        property_id=subject.property_id,
        address=subject.address,
        suburb=suburb.name if suburb else subject.suburb,
        council=council_name,
        headline=headline(parcel, flood, catchments, census, places),
        sections=sections,
        generated_at=datetime.now(UTC),
        disclaimer=DISCLAIMER,
    )


async def _none_pair() -> tuple[None, bool]:
    return None, False
