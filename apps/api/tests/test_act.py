"""The ACT: address search, blocks, zones and overlays against stand-ins for ACTmapi's
services (no network in tests), and the ACT content: the ACT Government entry, packs,
guides and forms."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from app.modules.councils import directory, states
from app.modules.guidance import guides
from app.modules.lookups.act import (
    ActSpatial,
    block_label,
    overlay_codes,
    parse_address,
    parse_block,
    zone_labels,
)
from app.modules.rules import packs

BASE = "https://act.example/rest/services"
RINGS = [
    [
        [149.12500, -35.28370],
        [149.12500, -35.28397],
        [149.12522, -35.28397],
        [149.12522, -35.28370],
        [149.12500, -35.28370],
    ]
]
POINT = {"x": 149.12511, "y": -35.28383}


def fake_act(found: set[str] | None = None, fail: str = "") -> httpx.MockTransport:
    hits = found if found is not None else {"Bushfire_Prone_Area_Details_2026"}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        params: dict[str, Any] = dict(request.url.params)
        if request.method == "POST":
            params = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if fail and fail in url:
            return httpx.Response(200, json={"error": {"code": 500, "message": "boom"}})
        if "ACTGOV_ADDRESSES/FeatureServer/0/query" in url:
            if params["where"] != (
                "STREET_NAME LIKE 'SMITH%' AND STREET_NUMBER = '12' AND "
                "STREET_TYPE = 'CIRCUIT' AND DIVISION LIKE 'AINSLIE%'"
            ):
                return httpx.Response(200, json={"features": []})
            attrs = {
                "ADDRESS_ID": 4242,
                "STREET_NUMBER": "12",
                "STREET_NAME": "SMITH",
                "STREET_TYPE": "CIRCUIT",
                "DIVISION": "AINSLIE",
                "DISTRICT": "NORTH CANBERRA",
                "SECTION": 7,
                "BLOCK": 3,
                "DOOR_NO": None,
            }
            feature = {"attributes": attrs, "geometry": POINT}
            return httpx.Response(200, json={"features": [feature, feature]})
        if "ACTGOV_BLOCKS/FeatureServer/0/query" in url:
            if "BLOCK_NUMBER = 3 AND SECTION_NUMBER = 7" not in params["where"]:
                return httpx.Response(200, json={"features": []})
            block = {
                "BLOCK_NUMBER": 3,
                "SECTION_NUMBER": 7,
                "DIVISION_NAME": "AINSLIE",
                "DISTRICT_NAME": "NORTH CANBERRA",
                "BLOCK_DERIVED_AREA": "802",
                "LAND_USE_POLICY_ZONES": "RZ1: SUBURBAN",
                "OVERLAY_PROVISION_ZONES": "Pc: Nature Reserve.;\nPUBLAN: Public Land",
            }
            return httpx.Response(
                200, json={"features": [{"attributes": block, "geometry": {"rings": RINGS}}]}
            )
        for key in hits:
            if f"{key}/FeatureServer" in url:
                return httpx.Response(200, json={"features": [{"attributes": {"OBJECTID": 1}}]})
        return httpx.Response(200, json={"features": []})

    return httpx.MockTransport(handler)


def test_parsing() -> None:
    assert parse_address("12 Smith Cct, Ainslie ACT 2602") == ("12", "SMITH", "CIRCUIT", "AINSLIE")
    assert parse_address("1 London Circuit Canberra") == ("1", "LONDON", "CIRCUIT", None)
    assert parse_address("O'Connor") == (None, "O''CONNOR", None, None)
    assert parse_address("12") is None
    assert parse_block("Block 3 Section 7 Ainslie") == "BLOCK 3 SECTION 7 AINSLIE"
    assert parse_block("block 03 section 7 o'connor") == "BLOCK 3 SECTION 7 O'CONNOR"
    assert parse_block("1' OR 1=1") is None
    assert block_label("BLOCK 3 SECTION 7 AINSLIE") == "Block 3 Section 7 Ainslie"
    assert (
        zone_labels("NUZ3: HILLS, RIDGES AND BUFFER AREAS; RZ1: SUBURBAN")
        == "NUZ3 Hills, Ridges and Buffer Areas; RZ1 Suburban"
    )
    assert overlay_codes("Pc: Nature Reserve.;\nPUBLAN: Public Land") == [
        ("Pc", "Nature Reserve"),
        ("PUBLAN", "Public Land"),
    ]


async def test_address_search_gives_the_block_and_the_act_government() -> None:
    async with httpx.AsyncClient(transport=fake_act()) as http:
        matches = await ActSpatial(http, BASE).search_addresses("12 Smith Cct Ainslie")
    assert len(matches) == 1
    m = matches[0]
    assert (m.line1, m.suburb, m.state) == ("12 Smith Circuit", "Ainslie", "ACT")
    assert m.label == "12 Smith Circuit, Ainslie ACT"
    assert m.lot_plan == "BLOCK 3 SECTION 7 AINSLIE"
    assert m.lot_plan_label == "Block 3 Section 7 Ainslie"
    assert m.lga == "act_government"
    assert (m.latitude, m.longitude) == (POINT["y"], POINT["x"])


async def test_block_report_with_zone_overlays_and_a_failed_service() -> None:
    async with httpx.AsyncClient(transport=fake_act(fail="ACTGOV_FLOOD_EXTENT")) as http:
        act = ActSpatial(http, BASE)
        report = await act.parcel("BLOCK 3 SECTION 7 AINSLIE")
        assert await act.parcel("BLOCK 9 SECTION 9 AINSLIE") is None
    assert report is not None
    assert report.state == "ACT" and report.lot_plan_label == "Block 3 Section 7 Ainslie"
    assert report.land_area_m2 == 802
    assert report.zone == "RZ1 Suburban"
    assert report.lga == "act_government"
    assert [o.key for o in report.overlays] == [
        "overlay_pc",
        "overlay_publan",
        "bushfire_prone_area",
    ]
    assert report.constraints == ["bushfire", "vegetation"]
    assert report.overlays_failed == ["Flooding"]
    assert "Heritage registers" in report.overlays_checked


async def test_match_address_needs_one_block() -> None:
    async with httpx.AsyncClient(transport=fake_act()) as http:
        match = await ActSpatial(http, BASE).match_address("12 Smith Cct", "Ainslie")
    assert match is not None and match.lot_plan == "BLOCK 3 SECTION 7 AINSLIE"


def test_the_act_government_entry() -> None:
    [act] = directory.councils("ACT")
    assert act.key == "act_government" and act.sources
    assert directory.for_local_authority("UNINCORPORATED ACT", "ACT") is not None
    planning = states.for_state("ACT")
    assert planning is not None and planning.fees and planning.zoning_lookup_url


def test_every_act_approval_has_a_guide() -> None:
    kinds: set[str] = set()
    for name in ("planning_act", "property_act", "business_act"):
        pack = packs.load_file(name)
        for rule_set in pack.rule_sets:
            assert rule_set.jurisdiction.endswith("ACT")
            for rule in rule_set.rules:
                for outcome in rule.outcomes:
                    approval = (outcome.payload or {}).get("approval")
                    if approval:
                        kinds.add(approval["kind"])
    assert kinds and all(k.startswith("ACT_") for k in kinds)
    have = {g.kind for g in guides.guides()}
    assert kinds <= have, kinds - have


@pytest.mark.parametrize("name", ["planning_act", "property_act", "business_act", "councils_act"])
def test_packs_load(name: str) -> None:
    assert packs.load_file(name).key == name
