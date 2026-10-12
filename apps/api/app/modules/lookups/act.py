"""ACT addresses, blocks, Territory Plan zones and overlays, from the ACT Government's open
spatial data on ACTmapi (free, no key, Creative Commons Attribution 4.0).

* Address search reads the ACT Government's address points (``ACTGOV_ADDRESSES``) by
  street number, street name and type ("1", "LONDON", "CIRCUIT"), and the suburb when one
  is typed. Each address carries its block: district, division (suburb), section and block.
* A block is named the ACT way, "Block 1 Section 7 City", and read from ``ACTGOV_BLOCKS``
  with its area, title (volume and folio) and the Territory Plan zone and overlays already
  on it.
* Over the block we also check the ACT Heritage Register, the 2026 bushfire prone area and
  the modelled 1% AEP flood extent.

The ACT has no councils: the ACT Government is the planning and municipal authority, so
every address's council is the one ACT Government entry. Designated land ("DES") is
National Capital Plan land, where the National Capital Authority approves works.

What this does **not** tell you, and says so: easements and lease conditions (the Crown
lease and a title search), and the Territory Plan's own rules for the zone. A layer found
means "the mapping shows this"; not found means "not shown on this map".
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from app.modules.lookups.client import TtlCache
from app.modules.lookups.spatial import (
    AddressMatch,
    NotChecked,
    Overlay,
    ParcelReport,
    _decimal,
    _str,
    arcgis_json,
    rings_area_m2,
)

ADDRESSES = "ACTGOV_ADDRESSES/FeatureServer/0"
BLOCKS = "ACTGOV_BLOCKS/FeatureServer/0"
HERITAGE = "ACTGOV_Heritage_Register/FeatureServer/1"
BUSHFIRE = "Bushfire_Prone_Area_Details_2026/FeatureServer/0"
FLOOD = "ACTGOV_FLOOD_EXTENT/FeatureServer/0"
# The ACT's one entry in the council directory (``spatial_name``).
ACT_GOVERNMENT = "UNINCORPORATED ACT"
SOURCE = (
    "ACTGOV Addresses, ACTGOV Block, Territory Plan zones and overlays, ACT Heritage Register, "
    "Bushfire Prone Area 2026 and ACTGOV Flood Extent Model from ACTmapi © Australian Capital "
    "Territory (CC BY 4.0)"
)
ACTMAPI = "https://www.actmapi.act.gov.au/"

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
    "CIR": "CIRCUIT",
    "WY": "WAY",
    "GR": "GROVE",
    "SQ": "SQUARE",
    "GDNS": "GARDENS",
    "LOOP": "LOOP",
    "VIEW": "VIEW",
}
FULL_TYPES = set(STREET_TYPES.values()) | {
    "CIRCUIT",
    "MEWS",
    "RISE",
    "ROW",
    "WALK",
    "VISTA",
    "CHASE",
    "GLEN",
    "PROMENADE",
    "TRACK",
    "RIDGE",
    "PLAZA",
}
_NOISE = {"ACT", "CANBERRA", "AUSTRALIA", "AUSTRALIAN", "CAPITAL", "TERRITORY"}
_TOKEN = re.compile(r"[A-Z0-9'-]+")
_BLOCK = re.compile(r"^BLOCK\s+(\d{1,5})\s+SECTION\s+(\d{1,4})\s+([A-Z][A-Z' -]{1,40})$")

# Territory Plan overlay codes that support a ``planning.known_constraints`` option.
OVERLAY_CONSTRAINTS = {"Pa": "vegetation", "Pb": "vegetation", "Pc": "vegetation"}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().upper())


def parse_address(query: str) -> tuple[str | None, str, str | None, str | None] | None:
    """ "1 London Cct, City ACT 2601" to ("1", "LONDON", "CIRCUIT", "CITY"): the street
    number, the start of the street name, the street type and the suburb, each safe in a
    where clause, or None when there isn't a street name to search on."""
    tokens = [
        t
        for t in _TOKEN.findall(query.upper().replace(",", " "))
        if t not in _NOISE and not re.fullmatch(r"2\d{3}", t)
    ]
    number = None
    if tokens and re.fullmatch(r"\d+[A-Z]?", tokens[0]):
        number = tokens.pop(0)
    kind = None
    suburb = None
    for i, token in enumerate(tokens):
        full = STREET_TYPES.get(token, token)
        if i and full in FULL_TYPES:
            kind = full
            suburb = " ".join(tokens[i + 1 :]) or None
            tokens = tokens[:i]
            break
    name = " ".join(tokens)
    if len(name) < 3:
        return None

    def q(text: str | None) -> str | None:
        return text.replace("'", "''") if text else None

    return number, q(name) or "", kind, q(suburb)


def parse_block(text: str) -> str | None:
    """ "Block 1 Section 7 City" to "BLOCK 1 SECTION 7 CITY"."""
    match = _BLOCK.match(_clean(text))
    if match is None:
        return None
    block, section, division = match.groups()
    return f"BLOCK {int(block)} SECTION {int(section)} {division.strip()}"


def _place(text: str) -> str:
    return " ".join(w.capitalize() for w in text.split())


def block_label(block_id: str) -> str:
    """ "BLOCK 1 SECTION 7 CITY" to "Block 1 Section 7 City"."""
    return _place(block_id)


def zone_labels(text: str | None) -> str | None:
    """ "NUZ3: HILLS, RIDGES AND BUFFER AREAS; RZ1: SUBURBAN" to "NUZ3 Hills, Ridges and
    Buffer Areas; RZ1 Suburban"."""
    if not text:
        return None
    labels = []
    for part in text.split(";"):
        code, _, desc = part.strip().partition(":")
        if not code:
            continue
        words = [
            w.lower() if i and w in {"AND", "OF", "THE"} else w.capitalize()
            for i, w in enumerate(desc.strip().split())
        ]
        labels.append(" ".join([code.strip(), *words]).strip())
    return "; ".join(labels) or None


def overlay_codes(text: str | None) -> list[tuple[str, str]]:
    """ "Pc: Nature Reserve.;\\nPUBLAN: Public Land" to [("Pc", "Nature Reserve"),
    ("PUBLAN", "Public Land")]."""
    found = []
    for part in (text or "").split(";"):
        code, _, desc = part.strip().partition(":")
        if code.strip():
            found.append((code.strip(), desc.strip().rstrip(".") or code.strip()))
    return found


def not_checked() -> list[NotChecked]:
    return [
        NotChecked(
            "What the Territory Plan allows in the zone",
            "The zone's policy and development codes in the Territory Plan set what you can "
            "build. Designated land (DES) is under the National Capital Plan instead.",
            "https://www.planning.act.gov.au/applications-and-assessments/territory-plan",
        ),
        NotChecked(
            "Lease purpose clause, easements and covenants",
            "Your Crown lease says what the block may be used for. Only the lease and a "
            "title search show these.",
            "https://www.accesscanberra.act.gov.au/",
        ),
    ]


def _centre(rings: list[list[list[float]]]) -> tuple[float, float]:
    xs = [p[0] for p in rings[0]]
    ys = [p[1] for p in rings[0]]
    return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2


class ActSpatial:
    state = "ACT"
    source = SOURCE

    def __init__(self, http: httpx.AsyncClient, base_url: str) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")
        self._cache = TtlCache()

    def parse_parcel_id(self, text: str) -> str | None:
        return parse_block(text)

    def _layer(self, path: str) -> str:
        return f"{self.base_url}/{path}"

    async def _query(self, path: str, params: dict[str, Any], *, post: bool = False) -> Any:
        return await arcgis_json(self.http, self._layer(path) + "/query", params, post=post)

    async def _addresses(self, where: str, limit: int) -> list[AddressMatch]:
        body = await self._query(
            ADDRESSES,
            {
                "where": where,
                "outFields": "ADDRESS_ID,STREET_NUMBER,STREET_NAME,STREET_TYPE,DIVISION,"
                "DISTRICT,SECTION,BLOCK,UNIT_TITLE,DOOR_NO",
                "returnGeometry": "true",
                "outSR": "4326",
                "resultRecordCount": str(limit * 3),
            },
        )
        found: dict[str, AddressMatch] = {}
        for feature in body.get("features") or []:
            a = feature.get("attributes") or {}
            g = feature.get("geometry") or {}
            street = " ".join(
                p for p in (_str(a.get("STREET_NAME")), _str(a.get("STREET_TYPE"))) if p
            )
            if not street:
                continue
            number = _str(a.get("STREET_NUMBER")) or ""
            if door := _str(a.get("DOOR_NO")):
                number = f"{door}/{number}"
            line1 = _place(f"{number} {street}".strip())
            division = _str(a.get("DIVISION"))
            suburb = _place(division or _str(a.get("DISTRICT")) or "")
            if line1 + suburb in found:
                continue
            block, section = a.get("BLOCK"), a.get("SECTION")
            block_id = (
                f"BLOCK {int(block)} SECTION {int(section)} {division}"
                if isinstance(block, int | float) and isinstance(section, int | float) and division
                else None
            )
            found[line1 + suburb] = AddressMatch(
                address_pid=_str(a.get("ADDRESS_ID")) or line1,
                label=f"{line1}, {suburb} ACT",
                line1=line1,
                suburb=suburb,
                state="ACT",
                lot=str(int(block)) if block_id and isinstance(block, int | float) else None,
                plan=f"Section {int(section)} {suburb}"
                if block_id and isinstance(section, int | float)
                else None,
                lot_plan=block_id,
                local_authority=ACT_GOVERNMENT,
                latitude=g.get("y"),
                longitude=g.get("x"),
                parcel_label=block_label(block_id) if block_id else None,
            )
        return list(found.values())[:limit]

    async def search_addresses(self, query: str, limit: int = 6) -> list[AddressMatch]:
        parsed = parse_address(query)
        if parsed is None:
            return []
        number, name, kind, suburb = parsed
        cache_key = f"addr:{parsed}:{limit}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return list(cached)
        clauses = [f"STREET_NAME LIKE '{name}%'"]
        if number:
            clauses.append(f"STREET_NUMBER = '{number}'")
        if kind:
            clauses.append(f"STREET_TYPE = '{kind}'")
        if suburb:
            clauses.append(f"DIVISION LIKE '{suburb}%'")
        found = await self._addresses(" AND ".join(clauses), limit)
        if not found and not kind and " " in name:
            # "1 London Cir": the last word may be the start of the street type.
            head, _, tail = name.rpartition(" ")
            clauses[0] = f"STREET_NAME LIKE '{head}%' AND STREET_TYPE LIKE '{tail}%'"
            found = await self._addresses(" AND ".join(clauses), limit)
        self._cache.put(cache_key, tuple(found))
        return found

    async def _hits(self, path: str, polygon: dict[str, Any], fields: str) -> list[dict[str, Any]]:
        body = await self._query(
            path,
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

    async def parcel(self, parcel_id: str) -> ParcelReport | None:
        """The block, its area, zone and overlays, or None when it isn't a registered
        block."""
        cached = self._cache.get(f"parcel:{parcel_id}")
        if cached is not None:
            report: ParcelReport = cached
            return report
        match = _BLOCK.match(parcel_id)
        if match is None:
            return None
        block, section, division = match.groups()
        place = division.strip().replace("'", "''")
        body = await self._query(
            BLOCKS,
            {
                "where": f"BLOCK_NUMBER = {int(block)} AND SECTION_NUMBER = {int(section)} AND "
                f"(DIVISION_NAME = '{place}' OR (DIVISION_NAME IS NULL AND "
                f"DISTRICT_NAME = '{place}')) AND CURRENT_LIFECYCLE_STAGE = 'REGISTERED'",
                "outFields": "BLOCK_NUMBER,SECTION_NUMBER,DIVISION_NAME,DISTRICT_NAME,"
                "BLOCK_DERIVED_AREA,LAND_USE_POLICY_ZONES,"
                "OVERLAY_PROVISION_ZONES,TYPE",
                "returnGeometry": "true",
                "outSR": "4326",
                "geometryPrecision": "7",
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
        zone = zone_labels(_str(a.get("LAND_USE_POLICY_ZONES")))
        group = "Territory Plan overlays"
        for code, desc in overlay_codes(_str(a.get("OVERLAY_PROVISION_ZONES"))):
            overlays.append(
                Overlay(
                    f"overlay_{code.lower()}",
                    f"{code} {desc}",
                    group,
                    OVERLAY_CONSTRAINTS.get(code),
                    self._layer(BLOCKS),
                )
            )
        checked.append(group)
        if zone and re.search(r"(^|; )DES\b", zone):
            overlays.append(
                Overlay(
                    "designated_land",
                    "Designated land under the National Capital Plan (works approval from "
                    "the National Capital Authority)",
                    group,
                    None,
                    self._layer(BLOCKS),
                )
            )
        if rings:
            polygon = {"rings": rings, "spatialReference": {"wkid": 4326}}
            results: tuple[Any, ...] = await asyncio.gather(
                self._hits(HERITAGE, polygon, "HRcategory,DataRestrictions"),
                self._hits(BUSHFIRE, polygon, "Hazard_Category"),
                self._hits(FLOOD, polygon, "OBJECTID"),
                return_exceptions=True,
            )
            for result, key, label, grp, constraint, path in (
                (
                    results[0],
                    "act_heritage_register",
                    "ACT Heritage Register place",
                    "Heritage registers",
                    "heritage",
                    HERITAGE,
                ),
                (
                    results[1],
                    "bushfire_prone_area",
                    "Bushfire prone area",
                    "Bushfire prone areas",
                    "bushfire",
                    BUSHFIRE,
                ),
                (
                    results[2],
                    "flood_extent",
                    "Modelled 1% AEP (1 in 100 year) flood extent",
                    "Flooding",
                    "flooding",
                    FLOOD,
                ),
            ):
                if isinstance(result, BaseException):
                    failed.append(grp)
                    continue
                checked.append(grp)
                if result:
                    overlays.append(Overlay(key, label, grp, constraint, self._layer(path)))
        area = _decimal(_str(a.get("BLOCK_DERIVED_AREA")))
        if area is None and rings:
            area = rings_area_m2(rings)
        block_id = (
            f"BLOCK {a.get('BLOCK_NUMBER') or block} SECTION {a.get('SECTION_NUMBER') or section}"
            f" {_str(a.get('DIVISION_NAME')) or _str(a.get('DISTRICT_NAME')) or division}"
        )
        report = ParcelReport(
            lot=str(a.get("BLOCK_NUMBER") or block),
            plan=f"Section {a.get('SECTION_NUMBER') or section}",
            lot_plan=block_id,
            tenure=None,
            land_area_m2=area.quantize(Decimal("1")) if area is not None else None,
            locality=_place(_str(a.get("DIVISION_NAME")) or "") or None,
            local_authority=ACT_GOVERNMENT,
            parcel_type=None,
            overlays=overlays,
            overlays_checked=checked,
            overlays_failed=failed,
            not_checked=not_checked(),
            source=SOURCE,
            source_url=self._layer(BLOCKS),
            retrieved_at=datetime.now(UTC),
            has_geometry=bool(rings),
            state="ACT",
            parcel_label=block_label(block_id),
            zone=zone,
        )
        if not failed:
            self._cache.put(f"parcel:{parcel_id}", report)
        return report

    async def match_address(self, line1: str, suburb: str) -> AddressMatch | None:
        candidates = [
            m
            for m in await self.search_addresses(f"{line1} {suburb}", limit=6)
            if m.suburb.upper() == suburb.strip().upper()
        ]
        if len(candidates) != 1 or candidates[0].lot_plan is None:
            return None
        return candidates[0]
