"""Victorian addresses, parcels, planning zones and overlays, from the Victorian Government's
open spatial services (free, no key, Creative Commons Attribution 4.0).

* Address search asks the Vicmap address geocoder for type-ahead suggestions
  (``Geocoder/VMAddressEZIAdd/GeocodeServer/suggest``, "1 SPRING STREET MELBOURNE 3000"),
  then reads those addresses from VicPlan's address layer
  (``Planning/VicPlan_PropertyAndParcel`` layer 2), which gives the locality, postcode and
  council code. If the geocoder doesn't answer, the address layer is searched by the start
  of the address instead.
* A parcel is named by its standard parcel identifier (SPI, "1\\PS123456"), read from the
  parcel layer (layer 4) with its boundary. Vicmap has no area field, so the area is worked
  out from the boundary.
* The zone and overlays come from the planning scheme layers VicPlan shows
  (``Planning/Vicplan_PlanningSchemeZones`` and ``Vicplan_PlanningSchemeOverlays``, layer 0),
  so we can tell people their zone ("GRZ1 General Residential Zone - Schedule 1") and the
  overlays on the land (heritage, bushfire management, flooding, vegetation). Also checked:
  the designated bushfire prone area, the Victorian Heritage Register and areas of
  Aboriginal cultural heritage sensitivity.

What this does **not** tell you, and says so: the schedules' own requirements, easements
and covenants (a title search), and the council's own local policies. A layer found means
"the mapping shows this"; not found means "not shown on this map", never "does not apply".
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
    ParcelReport,
    _str,
    arcgis_json,
    rings_area_m2,
)

GEOCODER = "Geocoder/VMAddressEZIAdd/GeocodeServer"
PARCELS = "Planning/VicPlan_PropertyAndParcel/MapServer"
ADDRESS_LAYER = 2
PARCEL_LAYER = 4
ZONES = "Planning/Vicplan_PlanningSchemeZones/MapServer"
OVERLAYS = "Planning/Vicplan_PlanningSchemeOverlays/MapServer"
BUSHFIRE = "Planning/VicPlan_Bushfire/MapServer"
HERITAGE = "Planning/VicPlan_Heritage/MapServer"
SCHEME_BOUNDARY = "Planning/Planning_Scheme_Boundary/MapServer"
SOURCE = (
    "Victorian Government: Vicmap address and parcel data, and Vicmap Planning zones and "
    "overlays (Department of Transport and Planning, CC BY 4.0)"
)
VICPLAN = "https://mapshare.vic.gov.au/vicplan/"

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
}
_NOISE = {"VIC", "VICTORIA", "AUSTRALIA"}
_TOKEN = re.compile(r"[A-Z0-9/'-]+")
_SPI = re.compile(
    r"^(?:LOT\s*)?([A-Z0-9~]{1,8})\s*(?:\\|/|\s+)\s*(?:ON\s+)?(?:PLAN\s+)?([A-Z]{2})\s*(\d{1,8}[A-Z]?)$"
)

# Overlay families (``CODE_PARENT``) that support a ``planning.known_constraints`` option.
OVERLAY_CONSTRAINTS = {
    "HO": "heritage",
    "BMO": "bushfire",
    "WMO": "bushfire",
    "LSIO": "flooding",
    "FO": "flooding",
    "SBO": "flooding",
    "RFO": "flooding",
    "VPO": "vegetation",
    "ESO": "vegetation",
    "SLO": None,
    "EMO": "steep_slope",
}


def address_prefix(query: str) -> str | None:
    """The start of an address as VicPlan's address layer writes it ("1 SPRING STREET
    MELB"), or None when there isn't enough to search on. Safe in a where clause."""
    tokens = [STREET_TYPES.get(t, t) for t in _TOKEN.findall(query.upper().replace(",", " "))]
    kept = [t for t in tokens if t not in _NOISE]
    if len(kept) < 2 or sum(len(t) for t in kept) < 5:
        return None
    return " ".join(kept).replace("'", "''")


def parse_spi(text: str) -> str | None:
    """ "Lot 1 PS123456", "Lot 1 on PS 123456", "1/PS123456", "1\\PS123456" to "1\\PS123456"."""
    match = _SPI.match(re.sub(r"\s+", " ", text.strip().upper()))
    if match is None:
        return None
    lot, plan_type, plan_no = match.groups()
    return f"{lot}\\{plan_type}{plan_no}"


def spi_label(spi: str) -> str:
    """ "1\\PS123456" to "Lot 1 PS123456"."""
    lot, _, plan = spi.partition("\\")
    return f"Lot {lot} {plan}" if plan else spi


def _title(text: str) -> str:
    small = {"AND", "OF", "THE", "IN", "ON", "TO", "FOR"}
    words = text.split(" ")
    return " ".join(
        w.lower() if i and w in small else (w if any(c.isdigit() for c in w) else w.capitalize())
        for i, w in enumerate(words)
    )


def zone_label(code: str | None, description: str | None) -> str | None:
    """ "GRZ1", "GENERAL RESIDENTIAL ZONE - SCHEDULE 1" to "GRZ1 General Residential Zone -
    Schedule 1"."""
    if not code and not description:
        return None
    return " ".join(p for p in (code, _title(description) if description else None) if p)


def not_checked(scheme_url: str | None = None) -> list[NotChecked]:
    return [
        NotChecked(
            "What the zone and overlay schedules require",
            "Each zone and overlay has a schedule in the council's planning scheme that sets "
            "its own requirements. Read them, or ask for a planning property report.",
            scheme_url or "https://www.planning.vic.gov.au/planning-schemes",
        ),
        NotChecked(
            "Easements and covenants",
            "Only a title search shows these.",
            "https://www.landata.vic.gov.au/",
        ),
    ]


def _centre(rings: list[list[list[float]]]) -> tuple[float, float]:
    xs = [p[0] for p in rings[0]]
    ys = [p[1] for p in rings[0]]
    return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2


class VicSpatial:
    state = "VIC"
    source = SOURCE

    def __init__(self, http: httpx.AsyncClient, geocoder_base: str, planning_base: str) -> None:
        self.http = http
        self.geocoder_base = geocoder_base.rstrip("/")
        self.planning_base = planning_base.rstrip("/")
        self._cache = TtlCache()

    def parse_parcel_id(self, text: str) -> str | None:
        return parse_spi(text)

    def _layer(self, service: str, layer: int) -> str:
        return f"{self.planning_base}/{service}/{layer}"

    async def _query(self, url: str, params: dict[str, Any], *, post: bool = False) -> Any:
        return await arcgis_json(self.http, url + "/query", params, post=post)

    async def _suggest(self, query: str, limit: int) -> list[str]:
        body = await arcgis_json(
            self.http,
            f"{self.geocoder_base}/{GEOCODER}/suggest",
            {"text": query[:200], "maxSuggestions": str(limit)},
        )
        return [
            text for s in body.get("suggestions") or [] if (text := _str((s or {}).get("text")))
        ]

    async def _addresses_where(self, where: str, limit: int) -> dict[str, AddressMatch]:
        """Matches by their full Vicmap address ("1 SPRING STREET MELBOURNE 3000"), in the
        order the service gave them; one per address where several properties share it."""
        body = await self._query(
            self._layer(PARCELS, ADDRESS_LAYER),
            {
                "where": where,
                "outFields": "PROPERTY_PFI,EZI_ADDRESS,NUM_ROAD_ADDRESS,LOCALITY_NAME,POSTCODE,"
                "LGA_CODE",
                "returnGeometry": "true",
                "outSR": "4326",
                "resultRecordCount": str(limit * 3),
            },
        )
        found: dict[str, AddressMatch] = {}
        for feature in body.get("features") or []:
            a = feature.get("attributes") or {}
            g = feature.get("geometry") or {}
            address = _str(a.get("EZI_ADDRESS"))
            if not address or address in found:
                continue
            suburb = _str(a.get("LOCALITY_NAME")) or ""
            postcode = _str(a.get("POSTCODE"))
            line1 = _str(a.get("NUM_ROAD_ADDRESS")) or address
            found[address] = AddressMatch(
                address_pid=_str(a.get("PROPERTY_PFI")) or address,
                label=f"{line1}, {suburb} VIC" + (f" {postcode}" if postcode else ""),
                line1=line1,
                suburb=suburb,
                state="VIC",
                lot=None,
                plan=None,
                lot_plan=None,
                local_authority=None,
                latitude=g.get("y"),
                longitude=g.get("x"),
                postcode=postcode,
            )
        return found

    async def _parcel_at(self, x: float, y: float) -> str | None:
        body = await self._query(
            self._layer(PARCELS, PARCEL_LAYER),
            {
                "geometry": f"{x},{y}",
                "geometryType": "esriGeometryPoint",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": "PARCEL_SPI,PARCEL_ROAD",
                "returnGeometry": "false",
            },
        )
        spis = [
            _str(a.get("PARCEL_SPI"))
            for f in body.get("features") or []
            if (a := f.get("attributes") or {}).get("PARCEL_ROAD") != "Y"
        ]
        return next((s for s in spis if s), None)

    async def _council_at(self, x: float, y: float) -> str | None:
        key = f"lga:{x:.5f},{y:.5f}"
        cached = self._cache.get(key)
        if cached is not None:
            name: str = cached
            return name
        body = await self._query(
            self._layer(SCHEME_BOUNDARY, 0),
            {
                "geometry": f"{x},{y}",
                "geometryType": "esriGeometryPoint",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": "SCHEME",
                "returnGeometry": "false",
            },
        )
        rows = [f.get("attributes") or {} for f in body.get("features") or []]
        found = _str(rows[0].get("SCHEME")) if rows else None
        if found:
            self._cache.put(key, found)
        return found

    async def _enrich(self, match: AddressMatch) -> AddressMatch:
        if match.latitude is None or match.longitude is None:
            return match
        x, y = float(match.longitude), float(match.latitude)
        spi, council = await asyncio.gather(self._parcel_at(x, y), self._council_at(x, y))
        lot, _, plan = (spi or "").partition("\\")
        return AddressMatch(
            address_pid=match.address_pid,
            label=match.label,
            line1=match.line1,
            suburb=match.suburb,
            state="VIC",
            lot=lot or None,
            plan=plan or None,
            lot_plan=spi,
            local_authority=council,
            latitude=match.latitude,
            longitude=match.longitude,
            parcel_label=spi_label(spi) if spi else None,
            postcode=match.postcode,
        )

    async def search_addresses(self, query: str, limit: int = 6) -> list[AddressMatch]:
        prefix = address_prefix(query)
        if prefix is None:
            return []
        cache_key = f"addr:{prefix}:{limit}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return list(cached)
        try:
            suggested = await self._suggest(query, limit)
        except LookupUnavailable:
            suggested = []
        rows: list[AddressMatch] = []
        if suggested:
            quoted = ", ".join("'" + s.replace("'", "''") + "'" for s in suggested)
            by_address = await self._addresses_where(f"EZI_ADDRESS IN ({quoted})", limit)
            rows = [by_address[s] for s in suggested if s in by_address]
        if not rows:
            by_address = await self._addresses_where(f"EZI_ADDRESS LIKE '{prefix}%'", limit)
            rows = list(by_address.values())
        results = await asyncio.gather(
            *(self._enrich(m) for m in rows[:limit]), return_exceptions=True
        )
        found = [r for r in results if isinstance(r, AddressMatch)]
        if rows and not found:
            raise LookupUnavailable("Victorian parcels didn't answer")
        self._cache.put(cache_key, tuple(found))
        return found

    async def _features(
        self, url: str, polygon: dict[str, Any], fields: str
    ) -> list[dict[str, Any]]:
        body = await self._query(
            url,
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
        """The parcel, its area, council, zone and overlays, or None when the SPI isn't in
        the parcel data."""
        cached = self._cache.get(f"parcel:{parcel_id}")
        if cached is not None:
            report: ParcelReport = cached
            return report
        body = await self._query(
            self._layer(PARCELS, PARCEL_LAYER),
            {
                "where": f"PARCEL_SPI = '{parcel_id.replace(chr(39), '')}'",
                "outFields": "PARCEL_SPI,PARCEL_LOT_NUMBER,PARCEL_PLAN_NUMBER,PARCEL_CROWN_STATUS",
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
        zone: str | None = None
        council: str | None = None
        if rings:
            polygon = {"rings": rings, "spatialReference": {"wkid": 4326}}
            x, y = _centre(rings)
            fields = "ZONE_CODE,ZONE_DESCRIPTION,CODE_PARENT"
            results = await asyncio.gather(
                self._council_at(x, y),
                self._features(self._layer(ZONES, 0), polygon, fields),
                self._features(self._layer(OVERLAYS, 0), polygon, fields),
                self._features(self._layer(BUSHFIRE, 1), polygon, "LGA_NAME"),
                self._features(self._layer(HERITAGE, 2), polygon, "VHR_NUM,SITE_NAME"),
                self._features(self._layer(HERITAGE, 3), polygon, "SENSITIVITY"),
                return_exceptions=True,
            )
            council_r, zones_r, overlays_r, bpa_r, vhr_r, achs_r = results
            if isinstance(council_r, str):
                council = council_r
            if isinstance(zones_r, list):
                labels = list(
                    dict.fromkeys(
                        z
                        for r in zones_r
                        if (
                            z := zone_label(
                                _str(r.get("ZONE_CODE")), _str(r.get("ZONE_DESCRIPTION"))
                            )
                        )
                    )
                )
                zone = "; ".join(labels) or None
                checked.append("Planning scheme zones")
            else:
                failed.append("Planning scheme zones")
            group = "Planning scheme overlays"
            if isinstance(overlays_r, list):
                checked.append(group)
                seen: set[str] = set()
                for r in overlays_r:
                    code = _str(r.get("ZONE_CODE"))
                    if not code or code in seen:
                        continue
                    seen.add(code)
                    family = _str(r.get("CODE_PARENT")) or ""
                    overlays.append(
                        Overlay(
                            f"overlay_{code.lower()}",
                            zone_label(code, _str(r.get("ZONE_DESCRIPTION"))) or code,
                            group,
                            OVERLAY_CONSTRAINTS.get(family),
                            self._layer(OVERLAYS, 0),
                        )
                    )
            else:
                failed.append(group)
            for result, key, label, grp, constraint, url in (
                (
                    bpa_r,
                    "bushfire_prone_area",
                    "Designated bushfire prone area",
                    "Bushfire prone areas",
                    "bushfire",
                    self._layer(BUSHFIRE, 1),
                ),
                (
                    vhr_r,
                    "victorian_heritage_register",
                    "Victorian Heritage Register place",
                    "Heritage registers",
                    "heritage",
                    self._layer(HERITAGE, 2),
                ),
                (
                    achs_r,
                    "cultural_heritage_sensitivity",
                    "Area of Aboriginal cultural heritage sensitivity",
                    "Heritage registers",
                    None,
                    self._layer(HERITAGE, 3),
                ),
            ):
                if isinstance(result, BaseException):
                    if grp not in failed:
                        failed.append(grp)
                    continue
                if grp not in checked:
                    checked.append(grp)
                if result:
                    overlays.append(Overlay(key, label, grp, constraint, url))
            checked = [g for g in checked if g not in failed]
        spi = _str(a.get("PARCEL_SPI")) or parcel_id
        lot, _, plan = spi.partition("\\")
        report = ParcelReport(
            lot=_str(a.get("PARCEL_LOT_NUMBER")) or lot,
            plan=_str(a.get("PARCEL_PLAN_NUMBER")) or plan,
            lot_plan=spi,
            tenure="Crown land" if _str(a.get("PARCEL_CROWN_STATUS")) == "C" else None,
            land_area_m2=rings_area_m2(rings) if rings else None,
            locality=None,
            local_authority=council,
            parcel_type=None,
            overlays=overlays,
            overlays_checked=checked,
            overlays_failed=failed,
            not_checked=not_checked(),
            source=SOURCE,
            source_url=self._layer(PARCELS, PARCEL_LAYER),
            retrieved_at=datetime.now(UTC),
            has_geometry=bool(rings),
            state="VIC",
            parcel_label=spi_label(spi),
            zone=zone,
        )
        if not failed:
            self._cache.put(f"parcel:{parcel_id}", report)
        return report

    async def match_address(self, line1: str, suburb: str) -> AddressMatch | None:
        want = " ".join(STREET_TYPES.get(t, t) for t in _TOKEN.findall(f"{line1} {suburb}".upper()))
        candidates = [
            m
            for m in await self.search_addresses(f"{line1} {suburb}", limit=6)
            if f"{m.line1} {m.suburb}".upper() == want
        ]
        spis = {m.lot_plan for m in candidates}
        if not candidates or len(spis) != 1:
            return None
        return candidates[0]
