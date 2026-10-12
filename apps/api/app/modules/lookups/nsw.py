"""New South Wales addresses, lots and plans, zoning and state-mapped overlays, from the NSW
Government's open spatial services (free, no key, Creative Commons Attribution).

* Addresses come from NSW Spatial Services' address points
  (``NSW_Geocoded_Addressing_Theme`` layer 1), searched by the start of the address
  ("25 SMITH STREET PARR..."): the service can't search the middle of an address. Each
  match's lot, council and suburb and postcode come from the point: the cadastre's lots
  (``NSW_Land_Parcel_Property_Theme`` layer 8) and the administrative boundaries' council
  areas (layer 8) and suburbs (layer 2) of ``NSW_Administrative_Boundaries_Theme``.
* A parcel is a lot in the cadastre, named by its ``lotidstring`` ("200//DP1287229",
  lot/section/plan). Its area is the plan's (``planlotarea``), not the map's.
* Zoning comes from the Department of Planning's Local Environmental Plan layers
  (``Planning/EPI_Primary_Planning_Layers`` layer 2), so we can tell people their zone
  ("R2 Low Density Residential"). Overlays: LEP heritage items (layer 0), the State
  Heritage Register (``HMS/Heritage`` layer 6), bush fire prone land and LEP flood planning
  areas (``ePlanning/Planning_Portal_Hazard`` layers 229 and 230) and the coastal use area
  (``Planning/SEPP_Resilience_and_Hazards_2021`` layer 7).

What this does **not** tell you, and says so: flooding that councils map only in flood
studies or development control plans, the development control plan's own rules,
easements and covenants (a title search), and what the council's planning certificate
(section 10.7) says. A layer found means "the mapping shows this"; not found means "not
shown on this map", never "does not apply".
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from typing import Any

import httpx

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

ADDRESS_SERVICE = "NSW_Geocoded_Addressing_Theme/MapServer"
ADDRESS_LAYER = 1
LOT_SERVICE = "NSW_Land_Parcel_Property_Theme/MapServer"
LOT_LAYER = 8
BOUNDARIES_SERVICE = "NSW_Administrative_Boundaries_Theme/MapServer"
LGA_LAYER = 8
SUBURB_LAYER = 2
EPI_SERVICE = "Planning/EPI_Primary_Planning_Layers/MapServer"
ZONING_LAYER = 2
SOURCE = (
    "NSW Government: Spatial Services address and cadastre data, and Department of Planning, "
    "Housing and Infrastructure planning maps (CC BY)"
)
ATTRIBUTION = (
    "© State of New South Wales (Spatial Services, a business unit of the Department of "
    "Customer Service NSW) and NSW Department of Planning, Housing and Infrastructure"
)
SPATIAL_VIEWER = "https://www.planningportal.nsw.gov.au/spatialviewer/"

STREET_TYPES = {
    "ST": "STREET",
    "RD": "ROAD",
    "AV": "AVENUE",
    "AVE": "AVENUE",
    "DR": "DRIVE",
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
    "SQ": "SQUARE",
    "HWAY": "HIGHWAY",
}
_NOISE = {"NSW", "AUSTRALIA"}
_TOKEN = re.compile(r"[A-Z0-9/'-]+")
_LOT = re.compile(
    r"^(?:LOT\s*)?([A-Z0-9]{1,6})(?:\s*/\s*|\s+)(?:(?:SEC(?:TION)?\s*([A-Z0-9]{1,6})|"
    r"([A-Z0-9]{1,6})?\s*/)\s*)?(?:ON\s+)?(DP|SP|CP|PP|CA|LT|MPS)\s*(\d{1,8})$"
)


def address_prefix(query: str) -> str | None:
    """The start of an address as the address points write it ("25 SMITH STREET PARR"),
    from what someone typed, or None when there isn't enough to search on. Tokens come from
    a fixed character set, so the result is safe in a where clause."""
    tokens = [STREET_TYPES.get(t, t) for t in _TOKEN.findall(query.upper().replace(",", " "))]
    kept = [t for t in tokens if t not in _NOISE and not re.fullmatch(r"\d{4}", t)]
    if len(kept) < 2 or sum(len(t) for t in kept) < 5:
        return None
    return " ".join(kept).replace("'", "''")


def parse_lot(text: str) -> str | None:
    """ "Lot 200 DP 1287229", "200/DP1287229", "Lot 3 Sec 2 DP 758" to the cadastre's
    ``lotidstring`` ("200//DP1287229", "3/2/DP758")."""
    cleaned = re.sub(r"\s+", " ", text.strip().upper())
    if re.fullmatch(r"[A-Z0-9]{1,6}/[A-Z0-9]{0,6}/[A-Z]{2,3}\d{1,8}", cleaned):
        return cleaned
    match = _LOT.match(cleaned)
    if match is None:
        return None
    lot, section, slash_section, plan_type, plan_no = match.groups()
    return f"{lot}/{section or slash_section or ''}/{plan_type}{plan_no}"


def lot_label(lotidstring: str) -> str:
    """ "200//DP1287229" to "Lot 200 DP1287229"; "3/2/DP758" to "Lot 3 Section 2 DP758"."""
    lot, section, plan = [*lotidstring.split("/"), "", ""][:3]
    return f"Lot {lot}" + (f" Section {section}" if section else "") + f" {plan}"


OVERLAY_CHECKS: tuple[OverlayCheck, ...] = (
    OverlayCheck(
        "lep_heritage",
        "Heritage item or conservation area in the Local Environmental Plan",
        EPI_SERVICE,
        (0,),
        "heritage",
        "Local Environmental Plan maps",
    ),
    OverlayCheck(
        "state_heritage_register",
        "State Heritage Register item",
        "HMS/Heritage/MapServer",
        (6,),
        "heritage",
        "State Heritage Register",
    ),
    OverlayCheck(
        "bush_fire_prone",
        "Bush fire prone land",
        "ePlanning/Planning_Portal_Hazard/MapServer",
        (229,),
        "bushfire",
        "Bush fire prone land and flood planning maps",
    ),
    OverlayCheck(
        "flood_planning",
        "Flood planning area in the Local Environmental Plan",
        "ePlanning/Planning_Portal_Hazard/MapServer",
        (230,),
        "flooding",
        "Bush fire prone land and flood planning maps",
    ),
    OverlayCheck(
        "coastal_use_area",
        "Coastal use area (State Environmental Planning Policy (Resilience and Hazards) 2021)",
        "Planning/SEPP_Resilience_and_Hazards_2021/MapServer",
        (7,),
        None,
        "Coastal management maps",
    ),
)


def not_checked(council_website: str | None = None) -> list[NotChecked]:
    return [
        NotChecked(
            "Planning certificate (section 10.7)",
            "The council's planning certificate is the official statement of the zone, "
            "hazards and other planning rules for the land. Anyone can order one.",
            council_website,
        ),
        NotChecked(
            "Development control plan",
            "Councils' detailed design rules (setbacks, parking, landscaping) are in their "
            "development control plans, which aren't published as maps we can read.",
            council_website,
        ),
        NotChecked(
            "Flooding in council flood studies",
            "Many councils map flooding only in their own flood studies, not in the Local "
            "Environmental Plan maps we check.",
            "https://flooddata.ses.nsw.gov.au/",
        ),
        NotChecked(
            "Easements and covenants",
            "Only a title search shows these.",
            "https://www.nswlrs.com.au/Land-Titles/Searching-the-Register",
        ),
    ]


def _ring_centre(rings: list[list[list[float]]]) -> tuple[float, float]:
    """A point inside a lot, close enough for finding its council and suburb: the middle of
    its outer ring's bounding box."""
    xs = [p[0] for p in rings[0]]
    ys = [p[1] for p in rings[0]]
    return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2


class NswSpatial:
    state = "NSW"
    source = SOURCE

    def __init__(self, http: httpx.AsyncClient, spatial_base: str, planning_base: str) -> None:
        self.http = http
        self.spatial_base = spatial_base.rstrip("/")
        self.planning_base = planning_base.rstrip("/")
        self._cache = TtlCache()

    def parse_parcel_id(self, text: str) -> str | None:
        return parse_lot(text)

    def _spatial(self, service: str, layer: int) -> str:
        return f"{self.spatial_base}/{service}/{layer}"

    def _planning(self, service: str, layer: int) -> str:
        return f"{self.planning_base}/{service}/{layer}"

    async def _query(self, url: str, params: dict[str, Any], *, post: bool = False) -> Any:
        return await arcgis_json(self.http, url + "/query", params, post=post)

    async def _at_point(
        self, url: str, x: float, y: float, fields: str, *, geometry: bool = False
    ) -> list[dict[str, Any]]:
        body = await self._query(
            url,
            {
                "geometry": f"{x},{y}",
                "geometryType": "esriGeometryPoint",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": fields,
                "returnGeometry": "true" if geometry else "false",
                "outSR": "4326",
            },
        )
        return list(body.get("features") or [])

    async def _place(self, x: float, y: float) -> tuple[str | None, str | None, str | None]:
        """Council name, suburb and postcode at a point."""
        key = f"place:{x:.6f},{y:.6f}"
        cached = self._cache.get(key)
        if cached is not None:
            found: tuple[str | None, str | None, str | None] = cached
            return found
        lgas, suburbs = await asyncio.gather(
            self._at_point(self._spatial(BOUNDARIES_SERVICE, LGA_LAYER), x, y, "lganame"),
            self._at_point(
                self._spatial(BOUNDARIES_SERVICE, SUBURB_LAYER), x, y, "suburbname,postcode"
            ),
        )
        lga = _str((lgas[0].get("attributes") or {}).get("lganame")) if lgas else None
        suburb = (suburbs[0].get("attributes") or {}) if suburbs else {}
        postcode = suburb.get("postcode")
        place = (
            lga,
            _str(suburb.get("suburbname")),
            f"{int(postcode):04d}" if isinstance(postcode, int | float) else _str(postcode),
        )
        self._cache.put(key, place)
        return place

    async def _lot_at(self, x: float, y: float) -> str | None:
        lots = await self._at_point(self._spatial(LOT_SERVICE, LOT_LAYER), x, y, "lotidstring")
        ids = [_str((f.get("attributes") or {}).get("lotidstring")) for f in lots]
        return next((i for i in ids if i), None)

    async def _enrich(self, attrs: dict[str, Any], x: float, y: float) -> AddressMatch:
        (lga, suburb, postcode), lot = await asyncio.gather(self._place(x, y), self._lot_at(x, y))
        address = _str(attrs.get("address")) or ""
        line1 = address
        if suburb and address.endswith(" " + suburb):
            line1 = address[: -len(suburb) - 1]
        parts = lot.split("/") if lot else []
        return AddressMatch(
            address_pid=int(attrs["gurasid"]) if attrs.get("gurasid") else address,
            label=f"{line1}, {suburb or ''} NSW".replace(",  NSW", " NSW"),
            line1=line1,
            suburb=suburb or "",
            state="NSW",
            lot=parts[0] if parts else None,
            plan=parts[2] if len(parts) > 2 else None,
            lot_plan=lot,
            local_authority=lga,
            latitude=y,
            longitude=x,
            parcel_label=lot_label(lot) if lot else None,
            postcode=postcode,
        )

    async def search_addresses(self, query: str, limit: int = 6) -> list[AddressMatch]:
        prefix = address_prefix(query)
        if prefix is None:
            return []
        cache_key = f"addr:{prefix}:{limit}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return list(cached)
        body = await self._query(
            self._spatial(ADDRESS_SERVICE, ADDRESS_LAYER),
            {
                "where": f"address LIKE '{prefix}%'",
                "outFields": "address,gurasid,housenumber",
                "returnGeometry": "true",
                "outSR": "4326",
                "orderByFields": "address",
                "resultRecordCount": str(limit),
            },
        )
        points: list[tuple[dict[str, Any], float, float]] = []
        seen: set[str] = set()
        for feature in body.get("features") or []:
            attrs = feature.get("attributes") or {}
            geometry = feature.get("geometry") or {}
            address = _str(attrs.get("address"))
            if not address or address in seen or "x" not in geometry or "y" not in geometry:
                continue
            seen.add(address)
            points.append((attrs, float(geometry["x"]), float(geometry["y"])))
        results = await asyncio.gather(
            *(self._enrich(a, x, y) for a, x, y in points[:limit]), return_exceptions=True
        )
        found = [r for r in results if isinstance(r, AddressMatch)]
        if points and not found:
            raise LookupUnavailable("NSW boundaries didn't answer")
        self._cache.put(cache_key, tuple(found))
        return found

    async def _features(
        self, check_url: str, polygon: dict[str, Any], fields: str
    ) -> list[dict[str, Any]]:
        body = await self._query(
            check_url,
            {
                "geometry": json.dumps(polygon),
                "geometryType": "esriGeometryPolygon",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": fields,
                "returnGeometry": "false",
            },
            post=True,
        )
        return [f.get("attributes") or {} for f in body.get("features") or []]

    async def _zone(self, polygon: dict[str, Any]) -> str | None:
        rows = await self._features(
            self._planning(EPI_SERVICE, ZONING_LAYER), polygon, "SYM_CODE,LAY_CLASS"
        )
        zones = list(
            dict.fromkeys(
                f"{_str(r.get('SYM_CODE')) or ''} {_str(r.get('LAY_CLASS')) or ''}".strip()
                for r in rows
            )
        )
        zones = [z for z in zones if z]
        return "; ".join(zones) if zones else None

    async def _overlay(self, check: OverlayCheck, polygon: dict[str, Any]) -> bool:
        results = await asyncio.gather(
            *(
                self._features(self._planning(check.service, layer), polygon, "OBJECTID")
                for layer in check.layers
            )
        )
        return any(results)

    async def parcel(self, parcel_id: str) -> ParcelReport | None:
        """The lot, its area, council, zone and the state overlays it touches, or None when
        the lot isn't in the cadastre."""
        cached = self._cache.get(f"parcel:{parcel_id}")
        if cached is not None:
            report: ParcelReport = cached
            return report
        body = await self._query(
            self._spatial(LOT_SERVICE, LOT_LAYER),
            {
                "where": f"lotidstring = '{parcel_id.replace(chr(39), '')}'",
                "outFields": "lotidstring,lotnumber,sectionnumber,planlabel,planlotarea,"
                "planlotareaunits",
                "returnGeometry": "true",
                "outSR": "4326",
                "geometryPrecision": "6",
            },
        )
        features = body.get("features") or []
        if not features:
            return None
        a = features[0].get("attributes") or {}
        rings = (features[0].get("geometry") or {}).get("rings") or []
        overlays: list[Overlay] = []
        checked: list[str] = []
        failed: list[str] = []
        zone: str | None = None
        lga = suburb = None
        if rings:
            polygon = {"rings": rings, "spatialReference": {"wkid": 4326}}
            x, y = _ring_centre(rings)
            place_zone, results = await asyncio.gather(
                asyncio.gather(self._place(x, y), self._zone(polygon), return_exceptions=True),
                asyncio.gather(
                    *(self._overlay(c, polygon) for c in OVERLAY_CHECKS), return_exceptions=True
                ),
            )
            place, zone_result = place_zone
            if isinstance(place, tuple):
                lga, suburb, _ = place
            if isinstance(zone_result, BaseException):
                failed.append("Zoning")
            else:
                zone = zone_result
                checked.append("Zoning")
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
                            self._planning(check.service, check.layers[0]),
                        )
                    )
            checked += [
                g for g in dict.fromkeys(c.group for c in OVERLAY_CHECKS) if g not in failed
            ]
        area = _decimal(a.get("planlotarea"))
        units = (_str(a.get("planlotareaunits")) or "Meters").lower()
        if area is not None and units.startswith("hect"):
            area = (area * 10000).quantize(area)
        elif area is not None and not units.startswith("met"):
            area = None
        lotid = _str(a.get("lotidstring")) or parcel_id
        report = ParcelReport(
            lot=_str(a.get("lotnumber")) or lotid.split("/")[0],
            plan=_str(a.get("planlabel")) or lotid.split("/")[-1],
            lot_plan=lotid,
            tenure=None,
            land_area_m2=area,
            locality=suburb,
            local_authority=lga,
            parcel_type=None,
            overlays=overlays,
            overlays_checked=checked,
            overlays_failed=failed,
            not_checked=not_checked(),
            source=SOURCE,
            source_url=self._spatial(LOT_SERVICE, LOT_LAYER),
            retrieved_at=datetime.now(UTC),
            has_geometry=bool(rings),
            state="NSW",
            parcel_label=lot_label(lotid),
            zone=zone,
        )
        if not failed:
            self._cache.put(f"parcel:{parcel_id}", report)
        return report

    async def match_address(self, line1: str, suburb: str) -> AddressMatch | None:
        """The one address matching a street line and suburb exactly, if there is one."""
        want = " ".join(_TOKEN.findall(f"{line1} {suburb}".upper()))
        want = " ".join(STREET_TYPES.get(t, t) for t in want.split())
        candidates = [
            m
            for m in await self.search_addresses(f"{line1} {suburb}", limit=6)
            if f"{m.line1} {m.suburb}".upper() == want
        ]
        lots = {m.lot_plan for m in candidates}
        if not candidates or len(lots) != 1:
            return None
        return candidates[0]
