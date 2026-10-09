"""Property facts providers: where facts about a site (council area, lot and plan, land
area, mapped constraints) can come from other than the customer.

* ``NoProvider`` returns nothing, so every fact comes from the customer's answers.
* ``QldSpatialProvider`` matches a Queensland address in the state's address data and
  reads its parcel and state-mapped overlays (``app/modules/lookups/qld.py``). It answers
  only when the address matches exactly one lot and plan, and never answers the zone:
  councils' planning scheme zoning isn't published as a service we can read.
* ``MockProvider`` only answers for made-up addresses in the suburb "Mockville" and labels
  every fact as made up. It exists for development and tests.

A provider returns each fact with where it came from and when, and may only return values
a questionnaire question accepts (anything else is dropped before it is offered).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from app.core.config import PropertyFactsProviderKind, Settings
from app.modules.lookups.client import LookupUnavailable

if TYPE_CHECKING:
    from app.modules.lookups.service import Lookups


@dataclass(frozen=True)
class AddressQuery:
    line1: str
    suburb: str
    state: str
    postcode: str


@dataclass(frozen=True)
class PropertyFact:
    key: str  # fact path, the same as the question key that collects it
    value: Any
    source: str  # who says so, in words a customer understands
    source_url: str | None
    retrieved_at: datetime
    is_mock: bool = False


class PropertyFactsProvider(Protocol):
    name: str

    async def lookup(self, address: AddressQuery) -> list[PropertyFact]: ...


class NoProvider:
    name = "none"

    async def lookup(self, address: AddressQuery) -> list[PropertyFact]:
        return []


MOCK_SUBURB = "mockville"
MOCK_SOURCE = "Mock provider (made-up data for development, not from any council)"


class MockProvider:
    name = "mock"

    async def lookup(self, address: AddressQuery) -> list[PropertyFact]:
        if address.suburb.strip().lower() != MOCK_SUBURB or address.state != "QLD":
            return []
        now = datetime.now(UTC)
        return [
            PropertyFact("property.lga", "cairns", MOCK_SOURCE, None, now, is_mock=True),
            PropertyFact(
                "property.zone", "low_density_residential", MOCK_SOURCE, None, now, is_mock=True
            ),
        ]


class QldSpatialProvider:
    name = "qld_spatial"

    def __init__(self, lookups: Lookups) -> None:
        self.lookups = lookups

    async def lookup(self, address: AddressQuery) -> list[PropertyFact]:
        if address.state != "QLD" or not self.lookups.enabled:
            return []
        qld = self.lookups.qld
        try:
            match = await qld.match_address(address.line1, address.suburb)
            if match is None or match.lot_plan is None:
                return []
            parcel = await qld.parcel(match.lot_plan)
        except LookupUnavailable:
            return []  # prefill is a convenience: the customer can still answer
        if parcel is None:
            return []
        source = f"{parcel.source} ({parcel.lot_plan_label})"
        at = parcel.retrieved_at
        facts = [PropertyFact("property.lot_plan", parcel.lot_plan_label, source, None, at)]
        if parcel.lga:
            facts.append(PropertyFact("property.lga", parcel.lga, source, parcel.source_url, at))
        if parcel.land_area_m2 is not None:
            facts.append(
                PropertyFact("property.land_area_m2", str(parcel.land_area_m2), source, None, at)
            )
        if parcel.constraints:
            first = next(o for o in parcel.overlays if o.constraint)
            facts.append(
                PropertyFact(
                    "planning.known_constraints",
                    parcel.constraints,
                    "Queensland Government state mapping: "
                    + "; ".join(o.label for o in parcel.overlays if o.constraint),
                    first.source_url,
                    at,
                )
            )
        return facts


def get_provider(settings: Settings, lookups: Lookups | None = None) -> PropertyFactsProvider:
    if settings.property_facts_provider == PropertyFactsProviderKind.MOCK:
        return MockProvider()
    if settings.property_facts_provider == PropertyFactsProviderKind.QLD_SPATIAL and lookups:
        return QldSpatialProvider(lookups)
    return NoProvider()
