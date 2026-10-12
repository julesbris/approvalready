"""Queensland addresses, lots and plans and state-mapped overlays, from the Queensland
Government's open spatial services (free, no key, ``spatial-gis.information.qld.gov.au``).

* Addresses come from the Queensland Address Management Framework and parcels from the
  Digital Cadastral Database (``PlanningCadastre/LandParcelPropertyFramework``, both
  updated nightly). An address gives its lot and plan and council; the parcel gives its
  area and tenure.
* Address search asks the state's address locator for type-ahead suggestions
  (``Location/QldLocator/GeocodeServer/suggest``, built for search-as-you-type), then
  reads those exact addresses from the address data in one query. Only if that finds
  nothing does it fall back to a pattern search of the address data, which is much slower
  because it scans every address in the state.
* Overlays are checked by intersecting the parcel with state layers: storm tide and
  erosion prone areas (``PlanningCadastre/CoastalManagement``), the regulated
  vegetation management map (``Biota/VegetationManagement``), and World Heritage Areas
  (including the Wet Tropics) and the Queensland Heritage Register
  (``Environment/EnvironmentallySensitiveAreasCategoryB``). All layers are queried at once.

What this does **not** tell you, and says so: the zone and local overlays under a
council's planning scheme (Cairns publishes them only in its own map viewer, not as a
service), bushfire prone areas, river and creek flooding, local heritage listing, Wet
Tropics zoning (its data licence rules out commercial use) and easements.
A layer found means "the mapping shows this", not a determination; a layer not found means
"not shown on this map", never "does not apply".
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from typing import Any

import httpx

from app.modules.councils.directory import for_local_authority
from app.modules.lookups.client import LookupUnavailable, TtlCache
from app.modules.lookups.spatial import (
    AddressMatch,
    NotChecked,
    Overlay,
    OverlayCheck,
    ParcelReport,
    _decimal,
    _str,
    arcgis_json,
)
from app.modules.lookups.spatial import lga_answer as _lga_answer

ADDRESS_SERVICE = "PlanningCadastre/LandParcelPropertyFramework/MapServer"
ADDRESS_LAYER = 0
LOCATOR_SERVICE = "Location/QldLocator/GeocodeServer"
PARCEL_LAYER = 4
CADASTRE_SOURCE = "Queensland Government: Digital Cadastral Database and Queensland address data"

# Words people abbreviate in street addresses, mapped to the form the address data uses.
STREET_TYPES = {
    "ST": "STREET",
    "RD": "ROAD",
    "AV": "AVENUE",
    "AVE": "AVENUE",
    "DR": "DRIVE",
    "DVE": "DRIVE",
    "CRES": "CRESCENT",
    "CR": "CRESCENT",
    "CT": "COURT",
    "PL": "PLACE",
    "PDE": "PARADE",
    "HWY": "HIGHWAY",
    "TCE": "TERRACE",
    "CL": "CLOSE",
    "BVD": "BOULEVARD",
    "BLVD": "BOULEVARD",
    "ESP": "ESPLANADE",
    "LN": "LANE",
    "CCT": "CIRCUIT",
    "WY": "WAY",
    "GR": "GROVE",
    "GDNS": "GARDENS",
    "SQ": "SQUARE",
    "HTS": "HEIGHTS",
}
_NOISE = {"QLD", "QUEENSLAND", "AUSTRALIA", "UNIT", "LOT"}
_TOKEN = re.compile(r"[A-Z0-9/'-]+")
_LOT_PLAN = re.compile(
    r"^(?:LOT\s*)?([A-Z0-9]{1,6})\s*(?:ON\s*)?(?:PLAN\s*)?([A-Z]{1,4})\s*(\d{1,8})$"
)


def _tokens(text: str) -> list[str]:
    return [STREET_TYPES.get(t, t) for t in _TOKEN.findall(text.upper().replace(",", " "))]


def address_pattern(query: str) -> str | None:
    """A ``LIKE`` pattern for the ``address`` field ("119 Spencer Street Gatton QLD") from
    what someone typed, or None when there isn't enough to search on. Tokens come from a
    fixed character set, so the pattern is safe to put in a where clause."""
    tokens = _tokens(query)
    kept = [
        t
        for i, t in enumerate(tokens)
        if t not in _NOISE and not (i > 0 and re.fullmatch(r"\d{4}", t))  # postcodes
    ]
    if len(kept) < 2 or sum(len(t) for t in kept) < 4:
        return None
    # Units are "U1/34 Gilmore Street ...", so a leading "1/34" can't anchor the start.
    lead = "%" if "/" in kept[0] or not kept[0][0].isdigit() else ""
    return (lead + "%".join(kept) + "%").replace("'", "''")


def normalise_line(text: str) -> str:
    return " ".join(t for t in _tokens(text) if t not in _NOISE)


def parse_lot_plan(text: str) -> str | None:
    """ "Lot 12 on RP123456", "12RP123456" or "12 RP 123456" to "12RP123456"."""
    match = _LOT_PLAN.match(re.sub(r"\s+", " ", text.strip().upper()))
    if match is None:
        return None
    lot, plan_type, plan_no = match.groups()
    return f"{lot}{plan_type}{plan_no}"


def lga_answer(local_authority: str | None) -> str | None:
    """The planning questionnaire's ``property.lga`` value for a Queensland council name."""
    return _lga_answer(local_authority, "QLD")


WET_TROPICS = "Wet Tropics of Queensland"
ESA_B = "Environment/EnvironmentallySensitiveAreasCategoryB/MapServer"
HERITAGE_GROUP = "State World Heritage and heritage register mapping"

OVERLAY_CHECKS: tuple[OverlayCheck, ...] = (
    OverlayCheck(
        "storm_tide_high",
        "Storm tide inundation area (high hazard)",
        "PlanningCadastre/CoastalManagement/MapServer",
        (11,),
        "flooding",
        "State coastal hazard mapping",
    ),
    OverlayCheck(
        "storm_tide_medium",
        "Storm tide inundation area (medium hazard)",
        "PlanningCadastre/CoastalManagement/MapServer",
        (12,),
        "flooding",
        "State coastal hazard mapping",
    ),
    OverlayCheck(
        "erosion_prone",
        "Erosion prone area",
        "PlanningCadastre/CoastalManagement/MapServer",
        (7, 8, 9),
        None,
        "State coastal hazard mapping",
    ),
    OverlayCheck(
        "coastal_management_district",
        "Coastal management district",
        "PlanningCadastre/CoastalManagement/MapServer",
        (5,),
        None,
        "State coastal hazard mapping",
    ),
    OverlayCheck(
        "remnant_vegetation",
        "Remnant vegetation (category B on the regulated vegetation management map)",
        "Biota/VegetationManagement/MapServer",
        (103,),
        "vegetation",
        "State vegetation management mapping",
    ),
    OverlayCheck(
        "regrowth_vegetation",
        "High-value or reef regrowth vegetation (category C or R)",
        "Biota/VegetationManagement/MapServer",
        (104, 105),
        "vegetation",
        "State vegetation management mapping",
    ),
    OverlayCheck(
        "essential_habitat",
        "Essential habitat for protected wildlife",
        "Biota/VegetationManagement/MapServer",
        (5,),
        "vegetation",
        "State vegetation management mapping",
    ),
    OverlayCheck(
        "wet_tropics_world_heritage",
        "Wet Tropics of Queensland World Heritage Area",
        ESA_B,
        (240,),
        "heritage",
        HERITAGE_GROUP,
        f"name = '{WET_TROPICS}'",
    ),
    OverlayCheck(
        "world_heritage_other",
        "Another World Heritage Area (Great Barrier Reef, K'gari, Gondwana Rainforests or "
        "Riversleigh)",
        ESA_B,
        (240,),
        None,
        HERITAGE_GROUP,
        f"name <> '{WET_TROPICS}'",
    ),
    OverlayCheck(
        "queensland_heritage_register",
        "Queensland Heritage Register place",
        ESA_B,
        (270,),
        "heritage",
        HERITAGE_GROUP,
    ),
)


CAIRNS_PLAN_URL = "https://www.cairns.qld.gov.au/property-and-business/planning-schemes/current"


WET_TROPICS_ZONING = NotChecked(
    "Wet Tropics zoning and permits",
    "The land is in or touches the Wet Tropics World Heritage Area. Its zoning decides "
    "whether you need a Wet Tropics permit, and its data licence doesn't allow us to read it.",
    "https://www.wettropics.gov.au/ZoningMap",
)


def not_checked(
    local_authority: str | None, overlays: tuple[str, ...] | list[str] = ()
) -> list[NotChecked]:
    council = for_local_authority(local_authority, "QLD")
    cairns = council is not None and council.key == "cairns"
    scheme = council.planning_scheme if council else None
    extra = [WET_TROPICS_ZONING] if "wet_tropics_world_heritage" in overlays else []
    return [
        *extra,
        NotChecked(
            "Zone and local overlays under the council's planning scheme",
            "Cairns Regional Council publishes zoning only in its own map viewer, not as a "
            "service we can read."
            if cairns
            else "Councils publish their own planning scheme mapping; we don't read it yet.",
            CAIRNS_PLAN_URL if cairns else (scheme.url if scheme else None),
        ),
        NotChecked(
            "Bushfire prone area",
            "Published by Queensland Fire Department as downloads and map viewers only.",
            "https://www.fire.qld.gov.au/compliance-and-planning/bushfire-planning/brc",
        ),
        NotChecked(
            "River and creek flooding",
            "Flood mapping is held by each council.",
            "https://floodcheck.information.qld.gov.au/",
        ),
        NotChecked(
            "Local heritage listing",
            "We check the Queensland Heritage Register; councils keep their own local "
            "heritage lists in their planning schemes.",
            scheme.url if scheme else "https://apps.des.qld.gov.au/heritage-register/",
        ),
        NotChecked(
            "Easements and registered interests",
            "Only a title search shows these.",
            "https://www.titlesqld.com.au/",
        ),
    ]


class QldSpatial:
    state = "QLD"
    source = CADASTRE_SOURCE

    def __init__(self, http: httpx.AsyncClient, base_url: str) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")
        self._cache = TtlCache()

    def layer_url(self, service: str, layer: int) -> str:
        return f"{self.base_url}/{service}/{layer}"

    def parse_parcel_id(self, text: str) -> str | None:
        return parse_lot_plan(text)

    async def _query(self, service: str, layer: int, params: dict[str, Any]) -> dict[str, Any]:
        # POST: overlay queries carry the parcel's boundary, too long for a URL.
        url = self.layer_url(service, layer) + "/query"
        return await arcgis_json(self.http, url, params, post=True)

    async def _suggest(self, query: str, limit: int) -> list[str]:
        """The locator's type-ahead suggestions, as the address data writes them
        ("34 Gilmore Street Bentley Park QLD")."""
        url = f"{self.base_url}/{LOCATOR_SERVICE}/suggest"
        params = {"text": query[:200], "maxSuggestions": str(limit), "f": "json"}
        try:
            response = await self.http.get(url, params=params)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LookupUnavailable(str(exc)) from exc
        if not isinstance(body, dict) or "error" in body:
            raise LookupUnavailable(json.dumps(body)[:300])
        out: list[str] = []
        for suggestion in body.get("suggestions") or []:
            text = _str((suggestion or {}).get("text"))
            if text and text.endswith(", Queensland"):
                out.append(text.removesuffix(", Queensland").replace(", ", " ") + " QLD")
        return out

    async def _addresses_where(self, where: str, limit: int) -> list[AddressMatch]:
        body = await self._query(
            ADDRESS_SERVICE,
            ADDRESS_LAYER,
            {
                "where": where,
                "outFields": "address,lot,plan,lotplan,street_full,street_number,unit_number,"
                "unit_type,locality,local_authority,state,latitude,longitude,address_pid",
                "returnGeometry": "false",
                "resultRecordCount": str(limit * 3),
            },
        )
        matches: dict[int, AddressMatch] = {}
        for feature in body.get("features") or []:
            a = feature.get("attributes") or {}
            pid = a.get("address_pid")
            address = _str(a.get("address"))
            locality = _str(a.get("locality"))
            if pid is None or address is None or locality is None or pid in matches:
                continue
            state = _str(a.get("state")) or "QLD"
            suffix = f" {locality} {state}"
            line1 = address[: -len(suffix)] if address.endswith(suffix) else address
            matches[int(pid)] = AddressMatch(
                address_pid=int(pid),
                label=f"{line1}, {locality} {state}",
                line1=line1,
                suburb=locality,
                state=state,
                lot=_str(a.get("lot")),
                plan=_str(a.get("plan")),
                lot_plan=_str(a.get("lotplan")),
                local_authority=_str(a.get("local_authority")),
                latitude=a.get("latitude"),
                longitude=a.get("longitude"),
            )
        return list(matches.values())

    async def search_addresses(self, query: str, limit: int = 8) -> list[AddressMatch]:
        pattern = address_pattern(query)
        if pattern is None:
            return []
        cache_key = f"addr:{pattern}:{limit}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return list(cached)
        found: list[AddressMatch] = []
        suggested: list[str] = []
        # The locator drops the slash in unit numbers ("2/15" becomes "215"), so units go
        # straight to the pattern search.
        if "/" not in query:
            try:
                suggested = await self._suggest(query, limit)
            except LookupUnavailable:
                suggested = []
        if suggested:
            quoted = ", ".join("'" + a.replace("'", "''") + "'" for a in suggested)
            rows = await self._addresses_where(f"address IN ({quoted})", limit)
            order = {a.upper(): i for i, a in enumerate(suggested)}
            found = sorted(
                rows,
                key=lambda m: (order.get(f"{m.line1} {m.suburb} {m.state}".upper(), 99), m.label),
            )[:limit]
        if not found:
            # The slow way: a pattern over every address in the state.
            rows = await self._addresses_where(f"upper(address) LIKE '{pattern}'", limit)
            found = sorted(rows, key=lambda m: m.label)[:limit]
        self._cache.put(cache_key, tuple(found))
        return found

    async def _layer_has(self, service: str, layer: int, params: dict[str, Any]) -> bool:
        body = await self._query(service, layer, params)
        return int(body.get("count") or 0) > 0

    async def _overlay(self, check: OverlayCheck, geometry: dict[str, Any]) -> bool:
        params = {
            "geometry": json.dumps(geometry),
            "geometryType": "esriGeometryPolygon",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "returnCountOnly": "true",
        }
        if check.where:
            params["where"] = check.where
        found = await asyncio.gather(
            *(self._layer_has(check.service, layer, params) for layer in check.layers)
        )
        return any(found)

    async def parcel(self, lot_plan: str) -> ParcelReport | None:
        """The parcel, its area and tenure and the state overlays it touches, or None when
        the lot and plan isn't in the cadastre."""
        cached = self._cache.get(f"parcel:{lot_plan}")
        if cached is not None:
            report: ParcelReport = cached
            return report
        body = await self._query(
            ADDRESS_SERVICE,
            PARCEL_LAYER,
            {
                "where": f"lotplan = '{lot_plan}'",
                "outFields": "lot,plan,lotplan,tenure,lot_area,locality,shire_name,parcel_typ",
                "returnGeometry": "true",
                "outSR": "4326",
                "geometryPrecision": "6",
                "maxAllowableOffset": "0.00001",
            },
        )
        features = body.get("features") or []
        if not features:
            return None
        feature = features[0]
        a = feature.get("attributes") or {}
        geometry = feature.get("geometry") or {}
        overlays: list[Overlay] = []
        checked: list[str] = []
        failed: list[str] = []
        has_geometry = bool(geometry.get("rings"))
        if has_geometry:
            polygon = {"rings": geometry["rings"], "spatialReference": {"wkid": 4326}}
            results = await asyncio.gather(
                *(self._overlay(c, polygon) for c in OVERLAY_CHECKS), return_exceptions=True
            )
            for check, result in zip(OVERLAY_CHECKS, results, strict=True):
                if isinstance(result, BaseException):
                    if check.group not in failed:
                        failed.append(check.group)
                    continue
                if result:
                    overlays.append(
                        Overlay(
                            check.key,
                            check.label,
                            check.group,
                            check.constraint,
                            self.layer_url(check.service, check.layers[0]),
                        )
                    )
            checked = [g for g in dict.fromkeys(c.group for c in OVERLAY_CHECKS) if g not in failed]
        local_authority = _str(a.get("shire_name"))
        report = ParcelReport(
            lot=_str(a.get("lot")) or "",
            plan=_str(a.get("plan")) or "",
            lot_plan=_str(a.get("lotplan")) or lot_plan,
            tenure=_str(a.get("tenure")),
            land_area_m2=_decimal(a.get("lot_area")),
            locality=_str(a.get("locality")),
            local_authority=local_authority,
            parcel_type=_str(a.get("parcel_typ")),
            overlays=overlays,
            overlays_checked=checked,
            overlays_failed=failed,
            not_checked=not_checked(local_authority, [o.key for o in overlays]),
            source=CADASTRE_SOURCE,
            source_url=self.layer_url(ADDRESS_SERVICE, PARCEL_LAYER),
            retrieved_at=datetime.now(UTC),
            has_geometry=has_geometry,
        )
        if not failed:
            self._cache.put(f"parcel:{lot_plan}", report)
        return report

    async def match_address(self, line1: str, suburb: str) -> AddressMatch | None:
        """The one address matching a street line and suburb exactly, if there is one."""
        want_line = normalise_line(line1)
        want_suburb = suburb.strip().upper()
        candidates = [
            m
            for m in await self.search_addresses(f"{line1} {suburb}", limit=20)
            if normalise_line(m.line1) == want_line and m.suburb.upper() == want_suburb
        ]
        lot_plans = {m.lot_plan for m in candidates}
        if len(candidates) == 0 or len(lot_plans) != 1:
            return None
        return candidates[0]
