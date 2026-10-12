"""Victoria: address search, parcels, zones and overlays against stand-ins for the Victorian
Government's spatial services (no network in tests), and the Victorian content: councils,
packs, guides and forms."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from app.modules.councils import directory, states
from app.modules.guidance import guides
from app.modules.lookups.spatial import rings_area_m2
from app.modules.lookups.vic import VicSpatial, address_prefix, parse_spi, spi_label, zone_label
from app.modules.rules import packs

GEO = "https://geo.example/rest/services"
VP = "https://vp.example/rest/services"
# About 20 m by 30 m in Fitzroy.
RINGS = [
    [
        [144.97800, -37.80000],
        [144.97800, -37.80027],
        [144.97823, -37.80027],
        [144.97823, -37.80000],
        [144.97800, -37.80000],
    ]
]
POINT = {"x": 144.97810, "y": -37.80010}
ADDRESS = "12 SMITH STREET FITZROY 3065"


def fake_vic(
    found: set[str] | None = None, fail: str = "", suggest: bool = True
) -> tuple[httpx.MockTransport, list[str]]:
    hits = found if found is not None else {"VicPlan_Bushfire/MapServer/1"}
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        params: dict[str, Any] = dict(request.url.params)
        if request.method == "POST":
            params = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if fail and fail in url:
            return httpx.Response(200, json={"error": {"code": 500, "message": "boom"}})
        if "GeocodeServer/suggest" in url:
            if not suggest:
                return httpx.Response(503)
            return httpx.Response(
                200,
                json={"suggestions": [{"text": ADDRESS, "magicKey": "k", "isCollection": False}]},
            )
        if "VicPlan_PropertyAndParcel/MapServer/2/query" in url:
            assert params["where"] in (
                f"EZI_ADDRESS IN ('{ADDRESS}')",
                "EZI_ADDRESS LIKE '12 SMITH STREET FITZROY%'",
            ), params
            attrs = {
                "PROPERTY_PFI": "203494497",
                "EZI_ADDRESS": ADDRESS,
                "NUM_ROAD_ADDRESS": "12 SMITH STREET",
                "LOCALITY_NAME": "FITZROY",
                "POSTCODE": "3065",
                "LGA_CODE": "367",
            }
            # Two properties share the address; we show it once.
            feature = {"attributes": attrs, "geometry": POINT}
            return httpx.Response(200, json={"features": [feature, feature]})
        if "VicPlan_PropertyAndParcel/MapServer/4/query" in url:
            if "geometry" in params:
                rows = [
                    {"attributes": {"PARCEL_SPI": "R1\\PS1", "PARCEL_ROAD": "Y"}},
                    {"attributes": {"PARCEL_SPI": "1\\PS123456", "PARCEL_ROAD": "N"}},
                ]
                return httpx.Response(200, json={"features": rows})
            if params["where"] != "PARCEL_SPI = '1\\PS123456'":
                return httpx.Response(200, json={"features": []})
            parcel_attrs: dict[str, Any] = {
                "PARCEL_SPI": "1\\PS123456",
                "PARCEL_LOT_NUMBER": "1",
                "PARCEL_PLAN_NUMBER": "PS123456",
                "PARCEL_CROWN_STATUS": None,
            }
            return httpx.Response(
                200, json={"features": [{"attributes": parcel_attrs, "geometry": {"rings": RINGS}}]}
            )
        if "Planning_Scheme_Boundary/MapServer/0/query" in url:
            return httpx.Response(200, json={"features": [{"attributes": {"SCHEME": "YARRA"}}]})
        if "Vicplan_PlanningSchemeZones/MapServer/0/query" in url:
            assert json.loads(params["geometry"])["rings"] == RINGS
            zone = {
                "ZONE_CODE": "NRZ1",
                "ZONE_DESCRIPTION": "NEIGHBOURHOOD RESIDENTIAL ZONE - SCHEDULE 1",
                "CODE_PARENT": "NRZ",
            }
            return httpx.Response(200, json={"features": [{"attributes": zone}]})
        if "Vicplan_PlanningSchemeOverlays/MapServer/0/query" in url:
            overlay_rows: list[dict[str, Any]] = [
                {
                    "ZONE_CODE": "HO334",
                    "ZONE_DESCRIPTION": "HERITAGE OVERLAY (HO334)",
                    "CODE_PARENT": "HO",
                },
                {
                    "ZONE_CODE": "DDO10",
                    "ZONE_DESCRIPTION": "DESIGN AND DEVELOPMENT OVERLAY - SCHEDULE 10",
                    "CODE_PARENT": "DDO",
                },
            ]
            return httpx.Response(200, json={"features": [{"attributes": r} for r in overlay_rows]})
        for key in hits:
            if f"{key}/query" in url:
                return httpx.Response(200, json={"features": [{"attributes": {"OBJECTID": 1}}]})
        return httpx.Response(200, json={"features": []})

    return httpx.MockTransport(handler), calls


def test_parsing() -> None:
    assert address_prefix("12 Smith St, Fitzroy VIC 3065") == "12 SMITH STREET FITZROY 3065"
    assert address_prefix("O'Grady St") == "O''GRADY STREET"
    assert address_prefix("12") is None
    assert parse_spi("Lot 1 PS123456") == "1\\PS123456"
    assert parse_spi("Lot 1 on PS 123456") == "1\\PS123456"
    assert parse_spi("1/PS123456") == "1\\PS123456"
    assert parse_spi("1\\ps123456") == "1\\PS123456"
    assert parse_spi("1' OR 1=1") is None
    assert spi_label("1\\PS123456") == "Lot 1 PS123456"
    assert (
        zone_label("GRZ1", "GENERAL RESIDENTIAL ZONE - SCHEDULE 1")
        == "GRZ1 General Residential Zone - Schedule 1"
    )
    assert (
        zone_label("DDO10", "DESIGN AND DEVELOPMENT OVERLAY - SCHEDULE 10")
        == "DDO10 Design and Development Overlay - Schedule 10"
    )


def test_area_from_the_boundary() -> None:
    area = rings_area_m2(RINGS)
    assert area is not None and 580 < area < 620  # 20.2 m by 30.0 m


@pytest.mark.parametrize("suggest", [True, False])
async def test_address_search_gives_the_lot_council_and_postcode(suggest: bool) -> None:
    transport, _ = fake_vic(suggest=suggest)
    async with httpx.AsyncClient(transport=transport) as http:
        matches = await VicSpatial(http, GEO, VP).search_addresses("12 Smith St Fitzroy")
    assert len(matches) == 1
    m = matches[0]
    assert (m.line1, m.suburb, m.state, m.postcode) == ("12 SMITH STREET", "FITZROY", "VIC", "3065")
    assert m.label == "12 SMITH STREET, FITZROY VIC 3065"
    assert m.lot_plan == "1\\PS123456" and m.lot_plan_label == "Lot 1 PS123456"
    assert m.lga == "vic_yarra"
    assert (m.latitude, m.longitude) == (POINT["y"], POINT["x"])


async def test_parcel_report_with_zone_overlays_and_a_failed_service() -> None:
    transport, _ = fake_vic(fail="VicPlan_Heritage/MapServer/2/")
    async with httpx.AsyncClient(transport=transport) as http:
        vic = VicSpatial(http, GEO, VP)
        report = await vic.parcel("1\\PS123456")
        assert await vic.parcel("9\\PS1") is None
    assert report is not None
    assert report.state == "VIC" and report.lot_plan_label == "Lot 1 PS123456"
    assert report.land_area_m2 is not None and 580 < report.land_area_m2 < 620
    assert report.zone == "NRZ1 Neighbourhood Residential Zone - Schedule 1"
    assert report.lga == "vic_yarra"
    assert [o.key for o in report.overlays] == [
        "overlay_ho334",
        "overlay_ddo10",
        "bushfire_prone_area",
    ]
    assert sorted(report.constraints) == ["bushfire", "heritage"]
    assert report.overlays_failed == ["Heritage registers"]
    assert "Planning scheme overlays" in report.overlays_checked


async def test_match_address_needs_one_exact_lot() -> None:
    transport, _ = fake_vic()
    async with httpx.AsyncClient(transport=transport) as http:
        match = await VicSpatial(http, GEO, VP).match_address("12 Smith St", "Fitzroy")
    assert match is not None and match.lot_plan == "1\\PS123456"


def test_every_council_area_has_an_entry() -> None:
    vic = directory.councils("VIC")
    assert len(vic) == 79
    for council in vic:
        assert council.key.startswith("vic_") and council.sources, council.key
        assert council.spatial_name == council.spatial_name.upper(), council.key
    assert directory.for_local_authority("GREATER GEELONG", "VIC") is not None
    assert directory.for_local_authority("YARRA", "VIC") is not None
    planning = states.for_state("VIC")
    assert planning is not None and planning.fees and planning.zoning_lookup_url


def test_every_vic_approval_has_a_guide() -> None:
    kinds: set[str] = set()
    for name in ("planning_vic", "property_vic", "business_vic"):
        pack = packs.load_file(name)
        for rule_set in pack.rule_sets:
            assert rule_set.jurisdiction.endswith("VIC")
            for rule in rule_set.rules:
                for outcome in rule.outcomes:
                    approval = (outcome.payload or {}).get("approval")
                    if approval:
                        kinds.add(approval["kind"])
    assert kinds and all(k.startswith("VIC_") for k in kinds)
    have = {g.kind for g in guides.guides()}
    assert kinds <= have, kinds - have


@pytest.mark.parametrize("name", ["planning_vic", "property_vic", "business_vic", "councils_vic"])
def test_packs_load(name: str) -> None:
    assert packs.load_file(name).key == name
