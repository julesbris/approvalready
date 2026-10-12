"""Tasmania: address search, titles, councils and the heritage register against stand-ins
for the LIST's services (no network in tests), and the Tasmanian content: councils, packs,
guides and forms."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from app.modules.councils import directory, states
from app.modules.guidance import guides
from app.modules.lookups.tas import TasSpatial, address_prefix, parse_title, title_label
from app.modules.rules import packs

LIST = "https://list.example/rest/services"
# About 20 m by 30 m in Hobart.
RINGS = [
    [
        [147.33100, -42.88200],
        [147.33100, -42.88227],
        [147.33124, -42.88227],
        [147.33124, -42.88200],
        [147.33100, -42.88200],
    ]
]
POINT = {"x": 147.33112, "y": -42.88213}


def fake_tas(heritage: bool = True, fail: str = "") -> tuple[httpx.MockTransport, list[str]]:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        params: dict[str, Any] = dict(request.url.params)
        if request.method == "POST":
            params = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if fail and fail in url:
            return httpx.Response(200, json={"error": {"code": 500, "message": "boom"}})
        if "SearchService/MapServer/7/query" in url:
            assert params["where"] == "ADDRESS LIKE '50 MACQUARIE STREET HOBART%'", params
            attrs: dict[str, Any] = {
                "ADDRESS": "50 MACQUARIE STREET HOBART",
                "PID": 2567107.0,
                "UNIT_TYPE": None,
                "UNIT_NUMBER": None,
                "STREET_NUMBER_FROM": 50,
                "STREET_NUMBER_FROM_SUFFIX": None,
                "STREET_NUMBER_TO": None,
                "STREET": "MACQUARIE",
                "STREET_TYPE": "STREET",
                "STREET_SUFFIX": None,
                "LOCALITY": "HOBART",
                "POSTCODE": 7000,
            }
            feature = {"attributes": attrs, "geometry": POINT}
            return httpx.Response(200, json={"features": [feature, feature]})
        if "OpenDataWFS/MapServer/14/query" in url:
            parcel: dict[str, Any] = {
                "VOLUME": "142916",
                "FOLIO": 1,
                "PID": 2567107,
                "TENURE_TY": "Council",
                "CAD_TYPE1": "Authority Land",
                "COMP_AREA": 5048.055,
            }
            if params["where"] == "PID = 2567107":
                return httpx.Response(200, json={"features": [{"attributes": parcel}]})
            if params["where"] == "VOLUME = '142916' AND FOLIO = 1":
                return httpx.Response(
                    200, json={"features": [{"attributes": parcel, "geometry": {"rings": RINGS}}]}
                )
            return httpx.Response(200, json={"features": []})
        if "OpenDataWFS/MapServer/28/query" in url:
            return httpx.Response(200, json={"features": [{"attributes": {"NAME": "Hobart"}}]})
        if "HT_Public/MapServer/0/query" in url:
            rows = [{"attributes": {"THR_ID": "12039", "THR_NAME": "Hobart Town Hall"}}]
            return httpx.Response(200, json={"features": rows if heritage else []})
        return httpx.Response(200, json={"features": []})

    return httpx.MockTransport(handler), calls


def test_parsing() -> None:
    assert address_prefix("50 Macquarie St, Hobart TAS 7000") == "50 MACQUARIE STREET HOBART"
    assert address_prefix("O'Brien Rd") == "O''BRIEN ROAD"
    assert address_prefix("50") is None
    assert parse_title("CT 142916/1") == "142916/1"
    assert parse_title("142916/01") == "142916/1"
    assert parse_title("Volume 142916 Folio 1") == "142916/1"
    assert parse_title("1' OR 1=1") is None
    assert title_label("142916/1") == "CT 142916/1"


async def test_address_search_gives_the_title_council_and_postcode() -> None:
    transport, _ = fake_tas()
    async with httpx.AsyncClient(transport=transport) as http:
        matches = await TasSpatial(http, LIST).search_addresses("50 Macquarie St Hobart")
    assert len(matches) == 1
    m = matches[0]
    assert (m.line1, m.suburb, m.state, m.postcode) == (
        "50 Macquarie Street",
        "Hobart",
        "TAS",
        "7000",
    )
    assert m.label == "50 Macquarie Street, Hobart TAS 7000"
    assert m.lot_plan == "142916/1" and m.lot_plan_label == "CT 142916/1"
    assert m.lga == "tas_hobart"
    assert (m.latitude, m.longitude) == (POINT["y"], POINT["x"])


async def test_parcel_report_with_heritage_and_area() -> None:
    transport, _ = fake_tas()
    async with httpx.AsyncClient(transport=transport) as http:
        tas = TasSpatial(http, LIST)
        report = await tas.parcel("142916/1")
        assert await tas.parcel("1/1") is None
        assert await tas.parcel("x/1") is None
    assert report is not None
    assert report.state == "TAS" and report.lot_plan_label == "CT 142916/1"
    assert report.land_area_m2 == 5048
    assert report.tenure == "Council"
    assert report.zone is None
    assert report.lga == "tas_hobart"
    assert [o.key for o in report.overlays] == ["tasmanian_heritage_register"]
    assert report.constraints == ["heritage"]
    assert report.overlays_checked == ["Heritage registers"]
    assert any("zone" in n.label for n in report.not_checked)


async def test_parcel_report_when_the_heritage_register_fails() -> None:
    transport, _ = fake_tas(fail="HT_Public")
    async with httpx.AsyncClient(transport=transport) as http:
        report = await TasSpatial(http, LIST).parcel("142916/1")
    assert report is not None
    assert report.overlays == [] and report.overlays_failed == ["Heritage registers"]


async def test_match_address_needs_one_exact_title() -> None:
    transport, _ = fake_tas()
    async with httpx.AsyncClient(transport=transport) as http:
        match = await TasSpatial(http, LIST).match_address("50 Macquarie St", "Hobart")
    assert match is not None and match.lot_plan == "142916/1"


def test_every_council_area_has_an_entry() -> None:
    tas = directory.councils("TAS")
    assert len(tas) == 29
    for council in tas:
        assert council.key.startswith("tas_") and council.sources, council.key
        assert council.spatial_name == council.spatial_name.upper(), council.key
    for name in ("HOBART", "LAUNCESTON", "BREAK O'DAY", "WARATAH-WYNYARD"):
        assert directory.for_local_authority(name, "TAS") is not None, name
    planning = states.for_state("TAS")
    # Tasmanian councils set their own planning fees, so there are no statewide ones.
    assert planning is not None and planning.fees is None and planning.zoning_lookup_url


def test_every_tas_approval_has_a_guide() -> None:
    kinds: set[str] = set()
    for name in ("planning_tas", "property_tas", "business_tas"):
        pack = packs.load_file(name)
        for rule_set in pack.rule_sets:
            assert rule_set.jurisdiction.endswith("TAS")
            for rule in rule_set.rules:
                for outcome in rule.outcomes:
                    approval = (outcome.payload or {}).get("approval")
                    if approval:
                        kinds.add(approval["kind"])
    assert kinds and all(k.startswith("TAS_") for k in kinds)
    have = {g.kind for g in guides.guides()}
    assert kinds <= have, kinds - have


@pytest.mark.parametrize("name", ["planning_tas", "property_tas", "business_tas", "councils_tas"])
def test_packs_load(name: str) -> None:
    assert packs.load_file(name).key == name
