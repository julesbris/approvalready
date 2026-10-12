"""What every state's address and parcel lookup returns, and the ArcGIS REST plumbing they
share.

Each state or territory publishes its own address data, cadastre and overlay mapping, as
free ArcGIS REST services (``qld.py`` and the other state modules). They all answer in the
same shapes, so the router, the questionnaire prefill and the property report don't care
which state an address is in:

* ``AddressMatch``: one address, with the parcel it sits on (in that state's own words,
  "Lot 2 on RP53576" in Queensland, "Lot 1 DP123456" in New South Wales), its council and
  where it is.
* ``ParcelReport``: a parcel's area, tenure and council, the state-mapped overlays it
  touches, and what to check elsewhere because no service we can read publishes it.

A state module implements ``StateSpatial``.
"""

from __future__ import annotations

import itertools
import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

import httpx

from app.modules.councils.directory import for_local_authority
from app.modules.lookups.client import LookupUnavailable

# Every state and territory, by the code addresses use, with its name.
STATES: dict[str, str] = {
    "QLD": "Queensland",
    "NSW": "New South Wales",
    "VIC": "Victoria",
    "WA": "Western Australia",
    "SA": "South Australia",
    "TAS": "Tasmania",
    "ACT": "Australian Capital Territory",
    "NT": "Northern Territory",
}


def lga_answer(local_authority: str | None, state: str = "QLD") -> str | None:
    """The planning questionnaire's ``property.lga`` value (the council directory's key)
    for a council name in a state's address data, or None when it isn't a known council."""
    council = for_local_authority(local_authority, state)
    return council.key if council else None


@dataclass(frozen=True)
class AddressMatch:
    address_pid: int | str
    label: str
    line1: str
    suburb: str
    state: str
    lot: str | None
    plan: str | None
    lot_plan: str | None
    local_authority: str | None
    latitude: float | None
    longitude: float | None
    # The parcel in the state's own words; None for "Lot <lot> on <plan>".
    parcel_label: str | None = None
    postcode: str | None = None

    @property
    def lot_plan_label(self) -> str | None:
        if self.parcel_label:
            return self.parcel_label
        return f"Lot {self.lot} on {self.plan}" if self.lot and self.plan else None

    @property
    def lga(self) -> str | None:
        return lga_answer(self.local_authority, self.state)


@dataclass(frozen=True)
class OverlayCheck:
    key: str
    label: str
    service: str
    layers: tuple[int, ...]
    # The planning questionnaire's ``planning.known_constraints`` option it supports.
    constraint: str | None
    group: str
    # Only features matching this (for a layer holding several places).
    where: str | None = None


@dataclass(frozen=True)
class Overlay:
    key: str
    label: str
    group: str
    constraint: str | None
    source_url: str


@dataclass(frozen=True)
class NotChecked:
    label: str
    why: str
    where_to_check: str | None


@dataclass(frozen=True)
class ParcelReport:
    lot: str
    plan: str
    lot_plan: str
    tenure: str | None
    land_area_m2: Decimal | None
    locality: str | None
    local_authority: str | None
    parcel_type: str | None
    overlays: list[Overlay]
    overlays_checked: list[str]  # groups checked; a found layer or none of them
    overlays_failed: list[str]  # groups whose service didn't answer
    not_checked: list[NotChecked]
    source: str
    source_url: str
    retrieved_at: datetime
    has_geometry: bool = field(default=True)
    state: str = "QLD"
    # The parcel in the state's own words; None for "Lot <lot> on <plan>".
    parcel_label: str | None = None
    # The planning zone, where the state publishes zoning as a service ("R2 Low Density
    # Residential"); None where it doesn't.
    zone: str | None = None

    @property
    def lga(self) -> str | None:
        return lga_answer(self.local_authority, self.state)

    @property
    def lot_plan_label(self) -> str:
        return self.parcel_label or f"Lot {self.lot} on {self.plan}"

    @property
    def constraints(self) -> list[str]:
        return sorted({o.constraint for o in self.overlays if o.constraint})


class StateSpatial(Protocol):
    """One state's address search and parcel lookup."""

    state: str
    # Who publishes the data, in words a customer understands.
    source: str

    def parse_parcel_id(self, text: str) -> str | None:
        """The parcel identifier ``parcel`` takes, from what someone typed, or None."""
        ...

    async def search_addresses(self, query: str, limit: int = 8) -> list[AddressMatch]: ...

    async def parcel(self, parcel_id: str) -> ParcelReport | None: ...

    async def match_address(self, line1: str, suburb: str) -> AddressMatch | None: ...


def _str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return number if number > 0 else None


_EARTH_RADIUS_M = 6_371_008.8


def rings_area_m2(rings: list[list[list[float]]]) -> Decimal | None:
    """The area of a polygon given as longitude/latitude rings (ArcGIS ``rings``, holes
    included), on a sphere: within about 0.5% of the surveyed area, for states whose
    parcel data has no area field."""
    total = 0.0
    for ring in rings:
        ring_sum = 0.0
        for (x1, y1, *_), (x2, y2, *_) in itertools.pairwise(ring):
            ring_sum += math.radians(x2 - x1) * (
                2 + math.sin(math.radians(y1)) + math.sin(math.radians(y2))
            )
        total += ring_sum
    area = abs(total) * _EARTH_RADIUS_M**2 / 2
    return _decimal(round(area)) if area else None


async def arcgis_json(
    http: httpx.AsyncClient,
    url: str,
    params: dict[str, Any],
    *,
    post: bool = False,
) -> dict[str, Any]:
    """An ArcGIS REST answer as JSON, or ``LookupUnavailable``. ``post`` for queries carrying
    a parcel's boundary, which is too long for a URL."""
    data = {"f": "json", **params}
    try:
        if post:
            response = await http.post(url, data=data)
        else:
            response = await http.get(url, params=data)
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise LookupUnavailable(str(exc)) from exc
    if not isinstance(body, dict) or "error" in body:
        raise LookupUnavailable(json.dumps(body)[:300])
    return body
