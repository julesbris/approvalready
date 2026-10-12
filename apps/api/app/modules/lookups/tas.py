"""Tasmanian addresses, titles and councils, from the LIST (Land Information System
Tasmania, free, no key, Creative Commons Attribution 3.0 Australia).

* Address search reads the LIST's address geocodes (``Public/SearchService`` layer 7) by
  the start of the full address ("50 MACQUARIE STREET HOBART"). Street types are spelt out
  there, so "St" is searched as "STREET".
* A parcel is named by its certificate of title, volume and folio ("CT 142916/1"), read
  from the LIST cadastral parcels (``Public/OpenDataWFS`` layer 14) with its computed area.
  An address point carries the property id (PID), which finds its title.
* The council comes from the LIST local government areas (layer 28), and the Tasmanian
  Heritage Register (``HT/HT_Public`` layer 0) is checked over the land.

What this does **not** tell you, and says so: the Tasmanian Planning Scheme zone and code
overlays (bushfire-prone areas, flooding, landslip, local heritage). The LIST publishes
them, but with no licence stated, so we point people to the LIST map instead of showing
them until Land Tasmania confirms the terms. Nor easements and covenants (a title search).
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from decimal import Decimal
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

ADDRESSES = "Public/SearchService/MapServer/7"
PARCELS = "Public/OpenDataWFS/MapServer/14"
COUNCILS = "Public/OpenDataWFS/MapServer/28"
HERITAGE = "HT/HT_Public/MapServer/0"
SOURCE = (
    "Address Geocodes, Cadastral Parcels, Local Government Areas and the Tasmanian Heritage "
    "Register from theLIST © State of Tasmania (CC BY 3.0 AU)"
)
LIST_MAP = "https://maps.thelist.tas.gov.au/listmap/app/list/map"

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
_NOISE = {"TAS", "TASMANIA", "AUSTRALIA"}
_TOKEN = re.compile(r"[A-Z0-9/'-]+")
_POSTCODE = re.compile(r"^7\d{3}$")
_TITLE = re.compile(
    r"^(?:CT|C/T|TITLE|CERTIFICATE OF TITLE)?\s*(?:VOL(?:UME)?\.?\s*)?(\d{1,7})"
    r"\s*(?:/|\s+FOL(?:IO)?\.?\s*|\s+)\s*(\d{1,4})$"
)


def address_prefix(query: str) -> str | None:
    """The start of an address as the LIST writes it ("50 MACQUARIE STREET HOB"), or None
    when there isn't enough to search on. Safe in a where clause."""
    tokens = [STREET_TYPES.get(t, t) for t in _TOKEN.findall(query.upper().replace(",", " "))]
    kept = [t for t in tokens if t not in _NOISE and not _POSTCODE.match(t)]
    if len(kept) < 2 or sum(len(t) for t in kept) < 5:
        return None
    return " ".join(kept).replace("'", "''")


def parse_title(text: str) -> str | None:
    """ "CT 142916/1", "142916/1", "Volume 142916 Folio 1" to "142916/1"."""
    match = _TITLE.match(re.sub(r"\s+", " ", text.strip().upper()))
    if match is None:
        return None
    volume, folio = match.groups()
    return f"{volume}/{int(folio)}"


def title_label(title: str) -> str:
    return f"CT {title}"


def _place(text: str) -> str:
    return " ".join(w.capitalize() if not any(c.isdigit() for c in w) else w for w in text.split())


def not_checked() -> list[NotChecked]:
    return [
        NotChecked(
            "Planning scheme zone and code overlays",
            "The Tasmanian Planning Scheme maps show the zone and overlays such as "
            "bushfire-prone areas, flooding, landslip and local heritage. Check them on the "
            "LIST map (Planning Online) or ask the council.",
            LIST_MAP,
        ),
        NotChecked(
            "Easements and covenants",
            "Only a title search shows these.",
            "https://www.thelist.tas.gov.au/",
        ),
    ]


async def _none() -> None:
    return None


def _centre(rings: list[list[list[float]]]) -> tuple[float, float]:
    xs = [p[0] for p in rings[0]]
    ys = [p[1] for p in rings[0]]
    return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2


class TasSpatial:
    state = "TAS"
    source = SOURCE

    def __init__(self, http: httpx.AsyncClient, base_url: str) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")
        self._cache = TtlCache()

    def parse_parcel_id(self, text: str) -> str | None:
        return parse_title(text)

    def _layer(self, path: str) -> str:
        return f"{self.base_url}/{path}"

    async def _query(self, path: str, params: dict[str, Any], *, post: bool = False) -> Any:
        return await arcgis_json(self.http, self._layer(path) + "/query", params, post=post)

    async def _at(self, path: str, x: float, y: float, fields: str) -> list[dict[str, Any]]:
        body = await self._query(
            path,
            {
                "geometry": f"{x},{y}",
                "geometryType": "esriGeometryPoint",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": fields,
                "returnGeometry": "false",
            },
        )
        return [f.get("attributes") or {} for f in body.get("features") or []]

    async def _title_for_pid(self, pid: str) -> str | None:
        body = await self._query(
            PARCELS,
            {
                "where": f"PID = {int(pid)}",
                "outFields": "VOLUME,FOLIO",
                "returnGeometry": "false",
            },
        )
        for feature in body.get("features") or []:
            a = feature.get("attributes") or {}
            volume, folio = _str(a.get("VOLUME")), a.get("FOLIO")
            if volume and folio is not None:
                return f"{volume}/{int(folio)}"
        return None

    async def _council_at(self, x: float, y: float) -> str | None:
        key = f"lga:{x:.5f},{y:.5f}"
        cached = self._cache.get(key)
        if cached is not None:
            name: str = cached
            return name
        rows = await self._at(COUNCILS, x, y, "NAME")
        found = _str(rows[0].get("NAME")) if rows else None
        if found:
            found = found.upper()
            self._cache.put(key, found)
        return found

    async def _enrich(self, match: AddressMatch) -> AddressMatch:
        pid = str(match.address_pid)
        title, council = await asyncio.gather(
            self._title_for_pid(pid) if pid.isdigit() else _none(),
            self._council_at(float(match.longitude), float(match.latitude))
            if match.latitude is not None and match.longitude is not None
            else _none(),
        )
        volume, _, folio = (title or "").partition("/")
        return AddressMatch(
            address_pid=match.address_pid,
            label=match.label,
            line1=match.line1,
            suburb=match.suburb,
            state="TAS",
            lot=folio or None,
            plan=volume or None,
            lot_plan=title,
            local_authority=council,
            latitude=match.latitude,
            longitude=match.longitude,
            parcel_label=title_label(title) if title else None,
            postcode=match.postcode,
        )

    async def _addresses(self, prefix: str, limit: int) -> list[AddressMatch]:
        body = await self._query(
            ADDRESSES,
            {
                "where": f"ADDRESS LIKE '{prefix}%'",
                "outFields": "ADDRESS,PID,UNIT_TYPE,UNIT_NUMBER,STREET_NUMBER_FROM,"
                "STREET_NUMBER_FROM_SUFFIX,STREET_NUMBER_TO,STREET,STREET_TYPE,STREET_SUFFIX,"
                "LOCALITY,POSTCODE",
                "returnGeometry": "true",
                "outSR": "4326",
                "resultRecordCount": str(limit * 3),
            },
        )
        found: dict[str, AddressMatch] = {}
        for feature in body.get("features") or []:
            a = feature.get("attributes") or {}
            g = feature.get("geometry") or {}
            address = _str(a.get("ADDRESS"))
            if not address or address in found:
                continue
            suburb = _place(_str(a.get("LOCALITY")) or "")
            postcode = _str(a.get("POSTCODE"))
            number = "".join(
                p
                for p in (
                    _str(a.get("STREET_NUMBER_FROM")),
                    _str(a.get("STREET_NUMBER_FROM_SUFFIX")),
                )
                if p
            )
            if to := _str(a.get("STREET_NUMBER_TO")):
                number = f"{number}-{to}"
            if unit := _str(a.get("UNIT_NUMBER")):
                number = f"{unit}/{number}"
            street = " ".join(
                p
                for p in (
                    _str(a.get("STREET")),
                    _str(a.get("STREET_TYPE")),
                    _str(a.get("STREET_SUFFIX")),
                )
                if p
            )
            line1 = _place(f"{number} {street}".strip()) if street else _place(address)
            pid = a.get("PID")
            found[address] = AddressMatch(
                address_pid=str(int(pid)) if isinstance(pid, int | float) else address,
                label=f"{line1}, {suburb} TAS" + (f" {postcode}" if postcode else ""),
                line1=line1,
                suburb=suburb,
                state="TAS",
                lot=None,
                plan=None,
                lot_plan=None,
                local_authority=None,
                latitude=g.get("y"),
                longitude=g.get("x"),
                postcode=postcode,
            )
        return list(found.values())

    async def search_addresses(self, query: str, limit: int = 6) -> list[AddressMatch]:
        prefix = address_prefix(query)
        if prefix is None:
            return []
        cache_key = f"addr:{prefix}:{limit}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return list(cached)
        rows = await self._addresses(prefix, limit)
        results = await asyncio.gather(
            *(self._enrich(m) for m in rows[:limit]), return_exceptions=True
        )
        found = [r for r in results if isinstance(r, AddressMatch)]
        if rows and not found:
            raise LookupUnavailable("Tasmanian parcels didn't answer")
        self._cache.put(cache_key, tuple(found))
        return found

    async def parcel(self, parcel_id: str) -> ParcelReport | None:
        """The title's parcel, its area, council and heritage listing, or None when the
        title isn't in the LIST's parcels."""
        cached = self._cache.get(f"parcel:{parcel_id}")
        if cached is not None:
            report: ParcelReport = cached
            return report
        volume, _, folio = parcel_id.partition("/")
        if not volume.isdigit() or not folio.isdigit():
            return None
        body = await self._query(
            PARCELS,
            {
                "where": f"VOLUME = '{volume}' AND FOLIO = {int(folio)}",
                "outFields": "VOLUME,FOLIO,PID,TENURE_TY,CAD_TYPE1,COMP_AREA",
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
        council: str | None = None
        group = "Heritage registers"
        if rings:
            polygon = {"rings": rings, "spatialReference": {"wkid": 4326}}
            x, y = _centre(rings)
            results: tuple[Any, ...] = await asyncio.gather(
                self._council_at(x, y),
                self._query(
                    HERITAGE,
                    {
                        "geometry": json.dumps(polygon),
                        "geometryType": "esriGeometryPolygon",
                        "inSR": "4326",
                        "spatialRel": "esriSpatialRelIntersects",
                        "outFields": "THR_ID,THR_NAME,REG_STATUS",
                        "returnGeometry": "false",
                    },
                    post=True,
                ),
                return_exceptions=True,
            )
            council_r, heritage_r = results
            if isinstance(council_r, str):
                council = council_r
            if isinstance(heritage_r, BaseException):
                failed.append(group)
            else:
                checked.append(group)
                if heritage_r.get("features"):
                    overlays.append(
                        Overlay(
                            "tasmanian_heritage_register",
                            "Tasmanian Heritage Register place",
                            group,
                            "heritage",
                            self._layer(HERITAGE),
                        )
                    )
        area = a.get("COMP_AREA")
        land_area: Decimal | None
        if isinstance(area, int | float) and area > 0:
            land_area = Decimal(round(area))
        else:
            land_area = rings_area_m2(rings) if rings else None
        title = f"{_str(a.get('VOLUME')) or volume}/{int(a.get('FOLIO') or folio)}"
        tenure = _str(a.get("TENURE_TY"))
        report = ParcelReport(
            lot=title.partition("/")[2],
            plan=title.partition("/")[0],
            lot_plan=title,
            tenure=tenure if tenure and tenure != "Private Freehold" else None,
            land_area_m2=land_area,
            locality=None,
            local_authority=council,
            parcel_type=_str(a.get("CAD_TYPE1")),
            overlays=overlays,
            overlays_checked=checked,
            overlays_failed=failed,
            not_checked=not_checked(),
            source=SOURCE,
            source_url=self._layer(PARCELS),
            retrieved_at=datetime.now(UTC),
            has_geometry=bool(rings),
            state="TAS",
            parcel_label=title_label(title),
            zone=None,
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
        titles = {m.lot_plan for m in candidates}
        if not candidates or len(titles) != 1:
            return None
        return candidates[0]
