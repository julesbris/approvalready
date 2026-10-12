"""Groundwork for covering every state: which state an address is in, address search across
the states we cover, councils keyed and matched by state, and each state's planning basics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.modules.councils import directory, pack, states
from app.modules.lookups.client import LookupUnavailable
from app.modules.lookups.router import search_in_states
from app.modules.lookups.spatial import AddressMatch, ParcelReport
from app.modules.lookups.which_state import state_for_postcode, state_in_text
from app.modules.questionnaires.schemas import option_group


def test_state_from_the_address_text() -> None:
    assert state_in_text("12 Smith St Parramatta NSW 2150") == "NSW"
    assert state_in_text("1 Collins Street Melbourne Victoria") == "VIC"
    assert state_in_text("4 Hay St Perth 6000") == "WA"
    assert state_in_text("34 Gilmore Street Bentley Park") is None
    assert state_in_text("2600") is None  # a bare number isn't a postcode yet
    assert state_for_postcode("2600") == "ACT"
    assert state_for_postcode("0800") == "NT"
    assert state_for_postcode("7000") == "TAS"


def _match(state: str, n: int) -> AddressMatch:
    return AddressMatch(
        address_pid=f"{state}-{n}",
        label=f"{n} Test Street, Town {state}",
        line1=f"{n} Test Street",
        suburb="Town",
        state=state,
        lot=None,
        plan=None,
        lot_plan=None,
        local_authority=None,
        latitude=None,
        longitude=None,
    )


@dataclass
class FakeState:
    state: str
    fail: bool = False
    asked: list[str] = field(default_factory=list)
    source: str = "Fake"

    def parse_parcel_id(self, text: str) -> str | None:
        return text

    async def search_addresses(self, query: str, limit: int = 8) -> list[AddressMatch]:
        self.asked.append(query)
        if self.fail:
            raise LookupUnavailable("down")
        return [_match(self.state, n) for n in range(1, 4)]

    async def parcel(self, parcel_id: str) -> ParcelReport | None:
        return None

    async def match_address(self, line1: str, suburb: str) -> AddressMatch | None:
        return None


class FakeLookups:
    def __init__(self, *services: FakeState) -> None:
        self.states: dict[str, Any] = {s.state: s for s in services}

    def for_state(self, state: str | None) -> Any:
        return self.states.get((state or "").upper())


@pytest.mark.asyncio
async def test_search_asks_the_named_state_only() -> None:
    qld, nsw = FakeState("QLD"), FakeState("NSW")
    matches, failed = await search_in_states(FakeLookups(qld, nsw), "1 Test St Town NSW", None)  # type: ignore[arg-type]
    assert {m.state for m in matches} == {"NSW"} and not failed
    assert qld.asked == []


@pytest.mark.asyncio
async def test_search_without_a_state_asks_every_state_and_interleaves() -> None:
    qld, nsw = FakeState("QLD"), FakeState("NSW", fail=True)
    lookups = FakeLookups(qld, nsw)
    matches, failed = await search_in_states(lookups, "1 Test St Town", None, limit=4)  # type: ignore[arg-type]
    assert [m.state for m in matches] == ["QLD"] * 3
    assert [s.state for s in failed] == ["NSW"]
    nsw.fail = False
    matches, _ = await search_in_states(lookups, "1 Test St Town", None, limit=4)  # type: ignore[arg-type]
    assert [m.address_pid for m in matches] == ["QLD-1", "NSW-1", "QLD-2", "NSW-2"]
    qld.fail = nsw.fail = True
    with pytest.raises(LookupUnavailable):
        await search_in_states(lookups, "1 Test St Town", None)  # type: ignore[arg-type]


def test_councils_are_matched_within_their_state() -> None:
    cairns = directory.by_key("cairns")
    assert cairns is not None and cairns.state == "QLD" and cairns.label == cairns.name
    assert directory.for_local_authority("Cairns Regional", "QLD") == cairns
    assert directory.for_local_authority("Cairns Regional", "NSW") is None
    assert pack.jurisdiction(cairns) == "LGA:QLD_CAIRNS"
    for state in directory.states():
        assert pack.pack_file(state).read_text(encoding="utf-8") == pack.render(state), (
            "Run `python -m app.modules.councils.pack`"
        )
    text = pack.PLANNING_FILE.read_text(encoding="utf-8")
    assert pack.render_planning(text) == text, "Run `python -m app.modules.councils.pack`"


def test_council_options_are_grouped_by_state_once_there_are_several() -> None:
    grouped = len(directory.states()) > 1
    assert (option_group("property.lga", "cairns") == "Queensland") is grouped
    assert option_group("property.zone", "cairns") is None
    assert option_group("property.lga", "other") is None


def test_every_state_with_councils_has_its_planning_basics() -> None:
    for state in directory.states():
        planning = states.for_state(state)
        assert planning is not None, f"{state}: add it to councils/states.json"
        assert planning.general_steps and planning.source.url.startswith("https://")
