"""The free public data behind the property report. Every source is official or openly
licensed, needs no key, and is named (with its date) next to each figure it gives:

* **ABS Census 2021** for the suburb (``data.api.abs.gov.au``, tables G01 people, G02
  medians and averages, G37 home ownership and dwelling types), the suburb found by placing
  the address in the ABS "suburbs and localities" boundaries (``geo.abs.gov.au``).
* **Queensland school catchments and school locations** (Department of Education and the
  Non-State Schools Accreditation Board, ``Society/SchoolsAndSchoolCatchments``).
* **State basin flood studies** (Queensland FloodCheck, the 1% annual chance flood extent).
* **Queensland Police Service reported offence rates** by council area, monthly (QPS open
  data, the same figures as the QPS online crime map).
* **Places nearby** from OpenStreetMap (© OpenStreetMap contributors, ODbL), through the
  Overpass API.

Each client answers None (or an empty list) when its service is down: the report then
says that part couldn't be checked, and the rest still works.
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
import io
import math
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from app.modules.lookups.client import TtlCache

QLD_STATE_CODE = "3"


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Straight-line distance in metres (haversine)."""
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)))


def _point(lat: float, lon: float) -> dict[str, str]:
    return {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "f": "json",
    }


async def _json(http: httpx.AsyncClient, url: str, **kwargs: Any) -> Any | None:
    try:
        response = await http.get(url, **kwargs)
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    if isinstance(body, dict) and body.get("error"):
        return None
    return body


# --- ABS: suburb and Census 2021 --------------------------------------------------------


@dataclass(frozen=True)
class Suburb:
    code: str
    name: str
    area_km2: float | None


# Queensland figures from Census 2021 QuickStats, for comparison (they don't change).
QLD_CENSUS = {
    "median_age": 38,
    "personal_income": 787,
    "family_income": 2024,
    "household_income": 1675,
    "mortgage": 1733,
    "rent": 365,
    "household_size": 2.5,
    "owned_outright": 29.1,
    "owned_mortgage": 34.4,
    "rented": 33.1,
    "separate_house": 74.8,
    "semi_detached": 11.7,
    "flat": 12.5,
}
G02 = {
    "1": "median_age",
    "2": "personal_income",
    "3": "family_income",
    "4": "household_income",
    "5": "mortgage",
    "6": "rent",
    "7": "persons_per_bedroom",
    "8": "household_size",
}
AGE_GROUPS = (
    ("0_4", "0 to 4"),
    ("5_14", "5 to 14"),
    ("15_19", "15 to 19"),
    ("20_24", "20 to 24"),
    ("25_34", "25 to 34"),
    ("35_44", "35 to 44"),
    ("45_54", "45 to 54"),
    ("55_64", "55 to 64"),
    ("65_74", "65 to 74"),
    ("75_84", "75 to 84"),
    ("GE85", "85 and over"),
)
TENURE = {"1": "owned_outright", "2": "owned_mortgage", "R_T": "rented", "_T": "total"}
STRUCTURE = {"11": "separate_house", "2": "semi_detached", "3": "flat", "_T": "total"}


def sdmx_series(body: Any) -> dict[tuple[str, ...], float]:
    """An SDMX-JSON data message as {(code per series dimension): first observation}."""
    data = body.get("data", body) if isinstance(body, dict) else None
    if not isinstance(data, dict):
        return {}
    structures = data.get("structures") or [data.get("structure")]
    structure = structures[0] if structures else None
    datasets = data.get("dataSets") or []
    if not isinstance(structure, dict) or not datasets:
        return {}
    dims = (structure.get("dimensions") or {}).get("series") or []
    codes = [[str(v.get("id")) for v in d.get("values") or []] for d in dims]
    out: dict[tuple[str, ...], float] = {}
    for key, series in (datasets[0].get("series") or {}).items():
        try:
            idx = [int(i) for i in key.split(":")]
            key_codes = tuple(codes[d][i] for d, i in enumerate(idx))
        except (ValueError, IndexError):
            continue
        observations = series.get("observations") or {}
        first = next(iter(observations.values()), None)
        if first and isinstance(first[0], int | float):
            out[key_codes] = float(first[0])
    return out


class AbsCensus:
    def __init__(self, http: httpx.AsyncClient, geo_base_url: str, data_base_url: str) -> None:
        self.http = http
        self.geo = geo_base_url.rstrip("/")
        self.data = data_base_url.rstrip("/")
        self._cache = TtlCache(max_entries=2048, ttl_seconds=30 * 24 * 3600)

    async def suburb_at(self, lat: float, lon: float) -> Suburb | None:
        body = await _json(
            self.http,
            f"{self.geo}/ASGS2021/SAL/MapServer/0/query",
            params={
                **_point(lat, lon),
                "outFields": "sal_code_2021,sal_name_2021,area_albers_sqkm",
                "returnGeometry": "false",
            },
        )
        features = body.get("features") if isinstance(body, dict) else None
        if not features:
            return None
        a = features[0].get("attributes") or {}
        code = str(a.get("sal_code_2021") or "")
        if not code.isdigit():
            return None
        area = a.get("area_albers_sqkm")
        return Suburb(
            code=code,
            name=str(a.get("sal_name_2021") or ""),
            area_km2=float(area) if isinstance(area, int | float) else None,
        )

    async def _flow(self, flow: str, key: str) -> dict[tuple[str, ...], float] | None:
        cache_key = f"{flow}:{key}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached  # type: ignore[no-any-return]
        body = await _json(
            self.http,
            f"{self.data}/data/ABS,{flow},1.0.0/{key}",
            params={"format": "jsondata"},
            headers={"accept": "application/json"},
        )
        if body is None:
            return None
        series = sdmx_series(body)
        self._cache.put(cache_key, series)
        return series

    async def profile(self, sal_code: str) -> dict[str, Any] | None:
        """Census 2021 figures for a Queensland suburb, or None when the ABS didn't answer."""
        place = f"{sal_code}.SAL.{QLD_STATE_CODE}"
        ages = "+".join(["P_1", *(code for code, _ in AGE_GROUPS)])
        medians, people, homes = await asyncio.gather(
            self._flow("C21_G02_SAL", f".{place}"),
            self._flow("C21_G01_SAL", f"3.{ages}.{place}"),
            self._flow("C21_G37_SAL", f"{'+'.join(TENURE)}.{'+'.join(STRUCTURE)}.{place}"),
        )
        if medians is None and people is None and homes is None:
            return None
        out: dict[str, Any] = {}
        for k, v in (medians or {}).items():
            if k and k[0] in G02:
                out[G02[k[0]]] = v
        counts = {k[1]: v for k, v in (people or {}).items() if len(k) > 1}
        if counts.get("P_1"):
            out["population"] = int(counts["P_1"])
            out["age_groups"] = [
                (label, round(100 * counts.get(code, 0) / counts["P_1"], 1))
                for code, label in AGE_GROUPS
            ]
        dwellings = {(k[0], k[1]): v for k, v in (homes or {}).items() if len(k) > 1}
        total = dwellings.get(("_T", "_T"))
        if total:
            out["dwellings"] = int(total)
            for code, name in TENURE.items():
                if code != "_T" and (code, "_T") in dwellings:
                    out[name] = round(100 * dwellings[(code, "_T")] / total, 1)
            for code, name in STRUCTURE.items():
                if code != "_T" and ("_T", code) in dwellings:
                    out[name] = round(100 * dwellings[("_T", code)] / total, 1)
        return out or None


# --- Queensland schools and flood studies -----------------------------------------------

SCHOOLS = "Society/SchoolsAndSchoolCatchments/MapServer"
CATCHMENTS = ((1, "Primary"), (2, "Junior secondary"), (3, "Senior secondary"))
SCHOOL_LAYERS = (
    (4, "State primary school"),
    (5, "State secondary school (junior)"),
    (6, "State secondary school (senior)"),
    (7, "State secondary school"),
    (8, "State special school"),
    (9, "Non-government school"),
)
FLOOD_1PCT = "FloodCheck/BasinOnePercentAEP/MapServer/1"


@dataclass(frozen=True)
class School:
    name: str
    kind: str
    distance_m: int
    years: str | None = None


class QldSchoolsAndFlood:
    def __init__(self, http: httpx.AsyncClient, base_url: str) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")
        self._cache = TtlCache(max_entries=1024, ttl_seconds=7 * 24 * 3600)

    async def catchments(self, lat: float, lon: float) -> list[tuple[str, str]] | None:
        """The state school catchments the address is in: (level, school)."""
        results = await asyncio.gather(
            *(
                _json(
                    self.http,
                    f"{self.base_url}/{SCHOOLS}/{layer}/query",
                    params={
                        **_point(lat, lon),
                        "outFields": "centre_name",
                        "returnGeometry": "false",
                    },
                )
                for layer, _ in CATCHMENTS
            )
        )
        if all(r is None for r in results):
            return None
        out = []
        for (_, level), body in zip(CATCHMENTS, results, strict=True):
            for f in (body or {}).get("features") or []:
                name = (f.get("attributes") or {}).get("centre_name")
                if name:
                    out.append((level, str(name)))
        return out

    async def schools_near(
        self, lat: float, lon: float, radius_m: int = 3000
    ) -> list[School] | None:
        results = await asyncio.gather(
            *(
                _json(
                    self.http,
                    f"{self.base_url}/{SCHOOLS}/{layer}/query",
                    params={
                        **_point(lat, lon),
                        "distance": str(radius_m),
                        "units": "esriSRUnit_Meter",
                        "outFields": "*",
                        "returnGeometry": "true",
                        "outSR": "4326",
                    },
                )
                for layer, _ in SCHOOL_LAYERS
            )
        )
        if all(r is None for r in results):
            return None
        seen: set[str] = set()
        out = []
        for (_, kind), body in zip(SCHOOL_LAYERS, results, strict=True):
            for f in (body or {}).get("features") or []:
                a = f.get("attributes") or {}
                g = f.get("geometry") or {}
                name = a.get("centre_name") or a.get("name")
                if not name or not isinstance(g.get("x"), int | float) or name in seen:
                    continue
                seen.add(name)
                school_kind = kind
                if a.get("type_of_education"):
                    school_kind = f"{kind}, {str(a['type_of_education']).lower()}"
                years = a.get("year_levels_accredited")
                out.append(
                    School(
                        name=str(name),
                        kind=school_kind,
                        distance_m=distance_m(lat, lon, g["y"], g["x"]),
                        years=str(years) if years else None,
                    )
                )
        return sorted(out, key=lambda s: s.distance_m)

    async def in_basin_flood_extent(self, lat: float, lon: float) -> bool | None:
        """Whether a state basin flood study maps the address inside its 1% annual chance
        flood extent; None when the service didn't answer."""
        body = await _json(
            self.http,
            f"{self.base_url}/{FLOOD_1PCT}/query",
            params={**_point(lat, lon), "returnCountOnly": "true"},
        )
        if not isinstance(body, dict) or not isinstance(body.get("count"), int):
            return None
        return bool(body["count"])


# --- OpenStreetMap: places nearby -------------------------------------------------------

# (key, label, OSM tag filters) - the nearest of each, and how many within the radius.
PLACES: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    ("supermarket", "Supermarket", (("shop", "supermarket"),)),
    ("shops", "Corner shop or bakery", (("shop", "convenience"), ("shop", "bakery"))),
    ("cafe", "Cafe or restaurant", (("amenity", "cafe"), ("amenity", "restaurant"))),
    ("childcare", "Childcare or kindy", (("amenity", "childcare"), ("amenity", "kindergarten"))),
    ("gp", "Doctor or medical centre", (("amenity", "doctors"), ("amenity", "clinic"))),
    ("hospital", "Hospital", (("amenity", "hospital"),)),
    ("pharmacy", "Pharmacy", (("amenity", "pharmacy"),)),
    ("bus", "Bus stop", (("highway", "bus_stop"),)),
    (
        "train",
        "Train, tram or ferry",
        (
            ("railway", "station"),
            ("railway", "halt"),
            ("railway", "tram_stop"),
            ("amenity", "ferry_terminal"),
        ),
    ),
    ("park", "Park or playground", (("leisure", "park"), ("leisure", "playground"))),
    (
        "sport",
        "Gym, pool or sports centre",
        (("leisure", "fitness_centre"), ("leisure", "sports_centre"), ("leisure", "swimming_pool")),
    ),
    ("beach", "Beach", (("natural", "beach"),)),
    ("library", "Library", (("amenity", "library"),)),
    ("police", "Police station", (("amenity", "police"),)),
    ("fuel", "Service station", (("amenity", "fuel"),)),
)


@dataclass(frozen=True)
class Place:
    key: str
    label: str
    nearest_name: str | None
    nearest_m: int
    count: int


def overpass_query(lat: float, lon: float, radius_m: int) -> str:
    pairs = sorted({tag for _, _, tags in PLACES for tag in tags})
    lines = "".join(f'nwr(around:{radius_m},{lat:.6f},{lon:.6f})["{k}"="{v}"];' for k, v in pairs)
    return f"[out:json][timeout:25];({lines});out tags center qt 3000;"


def places_from(body: Any, lat: float, lon: float) -> list[Place]:
    best: dict[str, tuple[int, str | None]] = {}
    counts: dict[str, int] = {}
    for el in (body or {}).get("elements") or []:
        tags = el.get("tags") or {}
        y = el.get("lat", (el.get("center") or {}).get("lat"))
        x = el.get("lon", (el.get("center") or {}).get("lon"))
        if not isinstance(y, int | float) or not isinstance(x, int | float):
            continue
        d = distance_m(lat, lon, y, x)
        for key, _, filters in PLACES:
            if any(tags.get(k) == v for k, v in filters):
                counts[key] = counts.get(key, 0) + 1
                name = tags.get("name")
                if key not in best or d < best[key][0]:
                    best[key] = (d, str(name) if name else None)
    return [
        Place(key, label, best[key][1], best[key][0], counts[key])
        for key, label, _ in PLACES
        if key in best
    ]


class Overpass:
    def __init__(self, http: httpx.AsyncClient, url: str) -> None:
        self.http = http
        self.url = url
        self._cache = TtlCache(max_entries=1024, ttl_seconds=7 * 24 * 3600)

    async def places(self, lat: float, lon: float, radius_m: int = 2000) -> list[Place] | None:
        key = f"{lat:.4f},{lon:.4f},{radius_m}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached  # type: ignore[no-any-return]
        try:
            response = await self.http.post(
                self.url, data={"data": overpass_query(lat, lon, radius_m)}, timeout=30
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        places = places_from(body, lat, lon)
        self._cache.put(key, places)
        return places


# --- Queensland Police Service: reported offences ---------------------------------------

CRIME_CATEGORIES = (
    ("Offences Against the Person", "Offences against the person (assault, robbery and more)"),
    ("Offences Against Property", "Offences against property (all)"),
    ("Unlawful Entry", "Break-ins (unlawful entry)"),
    ("Unlawful Use of Motor Vehicle", "Car theft (unlawful use of a motor vehicle)"),
    ("Other Property Damage", "Property damage"),
    ("Drug Offences", "Drug offences"),
)
_MONTH = re.compile(r"^([A-Z]{3})(\d{2})$")
_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


@dataclass(frozen=True)
class CrimeRates:
    area: str
    period: str  # e.g. "September 2025 to August 2026"
    # category label -> (area rate, Queensland rate), offences per 100,000 people a year
    rates: list[tuple[str, float, float | None]]


def _month_key(text: str) -> tuple[int, int] | None:
    m = _MONTH.match(text.strip().upper())
    if not m or m[1] not in _MONTHS:
        return None
    year = int(m[2])  # the files start in the 1990s
    return (1900 + year if year >= 90 else 2000 + year), _MONTHS.index(m[1]) + 1


def last_twelve_months(
    rows: list[dict[str, str]],
) -> tuple[dict[str, float], list[tuple[int, int]]]:
    """Sums of each category over the latest twelve months in the rows."""
    by_month = {}
    for row in rows:
        key = _month_key(row.get("Month Year", ""))
        if key:
            by_month[key] = row
    months = sorted(by_month)[-12:]
    sums: dict[str, float] = {}
    for column, _ in CRIME_CATEGORIES:
        total = 0.0
        for month in months:
            with contextlib.suppress(ValueError):
                total += float(by_month[month].get(column) or 0)
        sums[column] = total
    return sums, months


def _period(months: list[tuple[int, int]]) -> str:
    def word(m: tuple[int, int]) -> str:
        return f"{datetime(m[0], m[1], 1).strftime('%B')} {m[0]}"

    return f"{word(months[0])} to {word(months[-1])}" if months else ""


def _norm_lga(name: str) -> str:
    text = re.sub(r"\(.*?\)", "", name.upper())
    text = re.sub(r"\b(CITY|REGIONAL|SHIRE|ABORIGINAL|ISLAND|COUNCIL|TOWN|T)\b", "", text)
    return re.sub(r"[^A-Z]", "", text)


class QpsCrime:
    """Monthly offence rates per 100,000 people by council area and for Queensland. The
    files are re-read weekly; only the latest twelve months are kept."""

    def __init__(self, http: httpx.AsyncClient, base_url: str) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")
        self._loaded_at = 0.0
        self._by_lga: dict[str, tuple[str, dict[str, float]]] = {}
        self._qld: dict[str, float] = {}
        self._months: list[tuple[int, int]] = []
        self._lock = asyncio.Lock()
        self._loading: asyncio.Task[bool] | None = None

    async def _csv(self, name: str) -> list[dict[str, str]] | None:
        try:
            response = await self.http.get(f"{self.base_url}/{name}", timeout=60)
            response.raise_for_status()
        except httpx.HTTPError:
            return None
        text = response.content.decode("utf-8-sig", errors="replace")
        return list(csv.DictReader(io.StringIO(text)))

    async def _load(self) -> bool:
        if self._by_lga and time.monotonic() - self._loaded_at < 7 * 24 * 3600:
            return True
        async with self._lock:
            if self._by_lga and time.monotonic() - self._loaded_at < 7 * 24 * 3600:
                return True
            lga_rows, qld_rows = await asyncio.gather(
                self._csv("LGA_Reported_Offences_Rates.csv"),
                self._csv("QLD_Reported_Offences_Rates.csv"),
            )
            if not lga_rows:
                return bool(self._by_lga)
            grouped: dict[str, list[dict[str, str]]] = {}
            for row in lga_rows:
                grouped.setdefault(row.get("LGA Name", ""), []).append(row)
            by_lga = {}
            months: list[tuple[int, int]] = []
            for name, rows in grouped.items():
                sums, m = last_twelve_months(rows)
                by_lga[_norm_lga(name)] = (name, sums)
                months = max(months, m)
            self._by_lga = by_lga
            self._months = months
            self._qld = last_twelve_months(qld_rows)[0] if qld_rows else {}
            self._loaded_at = time.monotonic()
            return True

    def warm(self) -> None:
        """Start reading the files in the background if they aren't fresh, so the first
        report doesn't wait on the download (and a report that gives up waiting doesn't
        cancel it)."""
        fresh = self._by_lga and time.monotonic() - self._loaded_at < 7 * 24 * 3600
        if not fresh and (self._loading is None or self._loading.done()):
            self._loading = asyncio.create_task(self._load())

    async def rates(self, local_authority: str | None) -> CrimeRates | None:
        if not local_authority:
            return None
        self.warm()
        if self._loading is not None and not self._loading.done():
            await asyncio.shield(self._loading)
        if not self._by_lga:
            return None
        found = self._by_lga.get(_norm_lga(local_authority))
        if found is None:
            return None
        name, sums = found
        return CrimeRates(
            area=name,
            period=_period(self._months),
            rates=[
                (
                    label,
                    round(sums.get(column, 0.0)),
                    round(self._qld[column]) if column in self._qld else None,
                )
                for column, label in CRIME_CATEGORIES
            ],
        )


def now() -> datetime:
    return datetime.now(UTC)
