"""New South Wales: address search, lots, zoning and overlays against stand-ins for the NSW
Government's spatial services (no network in tests), and the NSW content: councils, packs,
guides and forms."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from app.modules.councils import directory, states
from app.modules.guidance import guides
from app.modules.lookups.nsw import NswSpatial, address_prefix, lot_label, parse_lot
from app.modules.rules import packs

SS = "https://ss.example/rest/services"
EP = "https://ep.example/rest/services"
RINGS = [[[151.0059, -33.8151], [151.0060, -33.8151], [151.0060, -33.8155], [151.0059, -33.8151]]]
POINT = {"x": 151.00565, "y": -33.81532}


def fake_nsw(
    found: set[str] | None = None, fail: str = ""
) -> tuple[httpx.MockTransport, list[str]]:
    hits = found if found is not None else {"Planning_Portal_Hazard/MapServer/229"}
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        params: dict[str, Any] = dict(request.url.params)
        if request.method == "POST":
            params = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if fail and fail in url:
            return httpx.Response(200, json={"error": {"code": 500, "message": "boom"}})
        if "NSW_Geocoded_Addressing_Theme/MapServer/1/query" in url:
            assert params["where"] == "address LIKE '25 SMITH STREET PARRAMATTA%'", params
            return httpx.Response(
                200,
                json={
                    "features": [
                        {
                            "attributes": {
                                "address": "25 SMITH STREET PARRAMATTA",
                                "gurasid": 85553412,
                            },
                            "geometry": POINT,
                        }
                    ]
                },
            )
        if "NSW_Administrative_Boundaries_Theme/MapServer/8/query" in url:
            return httpx.Response(
                200, json={"features": [{"attributes": {"lganame": "CITY OF PARRAMATTA"}}]}
            )
        if "NSW_Administrative_Boundaries_Theme/MapServer/2/query" in url:
            return httpx.Response(
                200,
                json={"features": [{"attributes": {"suburbname": "PARRAMATTA", "postcode": 2150}}]},
            )
        if "NSW_Land_Parcel_Property_Theme/MapServer/8/query" in url:
            if "geometry" in params:
                return httpx.Response(
                    200, json={"features": [{"attributes": {"lotidstring": "200//DP1287229"}}]}
                )
            if params["where"] != "lotidstring = '200//DP1287229'":
                return httpx.Response(200, json={"features": []})
            attrs = {
                "lotidstring": "200//DP1287229",
                "lotnumber": "200",
                "sectionnumber": None,
                "planlabel": "DP1287229",
                "planlotarea": 2170.007,
                "planlotareaunits": "Meters",
            }
            return httpx.Response(
                200, json={"features": [{"attributes": attrs, "geometry": {"rings": RINGS}}]}
            )
        if "EPI_Primary_Planning_Layers/MapServer/2/query" in url:
            assert json.loads(params["geometry"])["rings"] == RINGS
            zone = {"SYM_CODE": "R2", "LAY_CLASS": "Low Density Residential"}
            return httpx.Response(200, json={"features": [{"attributes": zone}]})
        for key in hits:
            if f"{key}/query" in url:
                return httpx.Response(200, json={"features": [{"attributes": {"OBJECTID": 1}}]})
        return httpx.Response(200, json={"features": []})

    return httpx.MockTransport(handler), calls


def test_parsing() -> None:
    assert address_prefix("25 Smith St, Parramatta NSW 2150") == "25 SMITH STREET PARRAMATTA"
    assert address_prefix("O'Connell St") == "O''CONNELL STREET"
    assert address_prefix("12") is None
    assert parse_lot("Lot 200 DP 1287229") == "200//DP1287229"
    assert parse_lot("200/DP1287229") == "200//DP1287229"
    assert parse_lot("200//dp1287229") == "200//DP1287229"
    assert parse_lot("Lot 3 Sec 2 DP 758") == "3/2/DP758"
    assert parse_lot("Lot 1 on SP 1234") == "1//SP1234"
    assert parse_lot("1' OR 1=1") is None
    assert lot_label("3/2/DP758") == "Lot 3 Section 2 DP758"


async def test_address_search_gives_the_lot_council_and_postcode() -> None:
    transport, _ = fake_nsw()
    async with httpx.AsyncClient(transport=transport) as http:
        matches = await NswSpatial(http, SS, EP).search_addresses("25 Smith St Parramatta NSW")
    assert len(matches) == 1
    m = matches[0]
    assert (m.line1, m.suburb, m.state, m.postcode) == (
        "25 SMITH STREET",
        "PARRAMATTA",
        "NSW",
        "2150",
    )
    assert m.lot_plan == "200//DP1287229" and m.lot_plan_label == "Lot 200 DP1287229"
    assert m.lga == "nsw_city_of_parramatta"
    assert (m.latitude, m.longitude) == (POINT["y"], POINT["x"])


async def test_parcel_report_with_zone_overlays_and_a_failed_service() -> None:
    transport, _ = fake_nsw(fail="HMS/Heritage/MapServer/6/")
    async with httpx.AsyncClient(transport=transport) as http:
        nsw = NswSpatial(http, SS, EP)
        report = await nsw.parcel("200//DP1287229")
        assert await nsw.parcel("1//DP1") is None
    assert report is not None
    assert report.state == "NSW" and report.lot_plan_label == "Lot 200 DP1287229"
    assert str(report.land_area_m2) == "2170.01"
    assert report.zone == "R2 Low Density Residential"
    assert report.lga == "nsw_city_of_parramatta" and report.locality == "PARRAMATTA"
    assert [o.key for o in report.overlays] == ["bush_fire_prone"]
    assert report.constraints == ["bushfire"]
    assert report.overlays_failed == ["State Heritage Register"]
    assert "Zoning" in report.overlays_checked
    assert any("10.7" in n.label for n in report.not_checked)


async def test_match_address_needs_one_exact_lot() -> None:
    transport, _ = fake_nsw()
    async with httpx.AsyncClient(transport=transport) as http:
        nsw = NswSpatial(http, SS, EP)
        match = await nsw.match_address("25 Smith St", "Parramatta")
    assert match is not None and match.lot_plan == "200//DP1287229"


def test_every_council_area_has_an_entry() -> None:
    nsw = directory.councils("NSW")
    assert len(nsw) == 128
    for council in nsw:
        assert council.key.startswith("nsw_") and council.sources, council.key
        assert council.spatial_name == council.spatial_name.upper(), council.key
    assert directory.for_local_authority("BLUE MOUNTAINS", "NSW") is not None
    planning = states.for_state("NSW")
    assert planning is not None and planning.portal and planning.fees
    assert len(directory.councils()) >= len(directory.councils("QLD")) + 128


def test_every_nsw_approval_has_a_guide() -> None:
    kinds: set[str] = set()
    for name in ("planning_nsw", "property_nsw", "business_nsw"):
        pack = packs.load_file(name)
        for rule_set in pack.rule_sets:
            assert rule_set.jurisdiction.endswith("NSW")
            for rule in rule_set.rules:
                for outcome in rule.outcomes:
                    approval = (outcome.payload or {}).get("approval")
                    if approval:
                        kinds.add(approval["kind"])
    assert kinds and all(k.startswith("NSW_") for k in kinds)
    have = {g.kind for g in guides.guides()}
    assert kinds <= have, kinds - have


@pytest.mark.parametrize("name", ["planning_nsw", "property_nsw", "business_nsw", "councils_nsw"])
def test_packs_load(name: str) -> None:
    assert packs.load_file(name).key == name
