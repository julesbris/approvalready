"""Property facts providers: where facts about a site (council area, zone, overlays) could
come from other than the customer.

No real provider exists yet. Councils and the state publish planning scheme mapping, but we
have not integrated any of it, and we never pretend to: ``NoProvider`` (the default and the
only choice in production) returns nothing, so every fact comes from the customer's answers.
``MockProvider`` exists so the interface, the prefill flow and the screens can be built and
tested. It only answers for made-up addresses in the suburb "Mockville" and labels every
fact as made up.

A real provider must return each fact with where it came from and when, and may only return
values a questionnaire question accepts (anything else is dropped before it is offered).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from app.core.config import PropertyFactsProviderKind, Settings


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


def get_provider(settings: Settings) -> PropertyFactsProvider:
    if settings.property_facts_provider == PropertyFactsProviderKind.MOCK:
        return MockProvider()
    return NoProvider()
