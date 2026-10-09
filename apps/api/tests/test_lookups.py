"""Address, parcel and vessel lookups against stand-ins for the Queensland spatial services
and AMSA's vessel list (no network in tests)."""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import PropertyFactsProviderKind, Settings
from app.main import create_app
from app.modules.lookups.amsa import (
    AmsaVesselList,
    normalise_uvi,
    parse_vessel_list,
    read_first_sheet,
)
from app.modules.lookups.qld import QldSpatial, address_pattern, parse_lot_plan
from tests.conftest import make_settings
from tests.harness import ApiHarness

BASE = "https://spatial.example/arcgis/rest/services"
AMSA_PAGE = "https://amsa.example/list-commercial-vessels-vessel-permission"

ADDRESS = {
    "address": "34 Gilmore Street Bentley Park QLD",
    "lot": "1",
    "plan": "RP731159",
    "lotplan": "1RP731159",
    "street_full": "Gilmore Street",
    "street_number": "34",
    "unit_number": None,
    "unit_type": None,
    "locality": "Bentley Park",
    "local_authority": "Cairns Regional",
    "state": "QLD",
    "latitude": -17.0,
    "longitude": 145.7,
    "address_pid": 123,
}
PARCEL = {
    "lot": "1",
    "plan": "RP731159",
    "lotplan": "1RP731159",
    "tenure": "Freehold",
    "lot_area": 774.0,
    "locality": "Bentley Park",
    "shire_name": "Cairns Regional",
    "parcel_typ": "Lot Type Parcel",
}
RINGS = [[[145.7, -17.0], [145.701, -17.0], [145.701, -17.001], [145.7, -17.0]]]


def xlsx(rows: list[list[str]]) -> bytes:
    """A minimal workbook: one sheet of inline strings."""

    def col(i: int) -> str:
        return chr(65 + i)

    sheet_rows = "".join(
        f'<row r="{r + 1}">'
        + "".join(
            f'<c r="{col(c)}{r + 1}" t="inlineStr"><is><t>{v}</t></is></c>'
            for c, v in enumerate(row)
            if v
        )
        + "</row>"
        for r, row in enumerate(rows)
    )
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            "xl/workbook.xml",
            f'<workbook {ns} {rel}><sheets><sheet name="DCV" sheetId="1" r:id="rId1"/>'
            "</sheets></workbook>",
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/data.xml" Type="x"/></Relationships>',
        )
        z.writestr(
            "xl/worksheets/data.xml",
            f"<worksheet {ns}><sheetData>{sheet_rows}</sheetData></worksheet>",
        )
    return buf.getvalue()


VESSEL_ROWS = [
    ["Domestic commercial vessels with a vessel permission"],
    ["Valid at 3 August 2026"],
    ["UVI", "Vessel Name", "Displayed Identifier", "Measured Length (m)", "Class", "Owner Name"],
    ["412345", "Reef Runner", "QF123", "12.4", "1C", "Jane Citizen"],
    ["", "No UVI row", "", "", "", ""],
]


def fake_government(overlay_counts: dict[tuple[str, int], int] | None = None, fail: str = ""):  # type: ignore[no-untyped-def]
    counts = overlay_counts or {}
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if url == AMSA_PAGE:
            return httpx.Response(
                200, text='<a href="/sites/default/files/dcv-vessels-aug26.xlsx">Download</a>'
            )
        if url.endswith(".xlsx"):
            return httpx.Response(200, content=xlsx(VESSEL_ROWS))
        if fail and fail in url:
            return httpx.Response(200, json={"error": {"code": 500, "message": "boom"}})
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if "LandParcelPropertyFramework/MapServer/0/query" in url:
            assert form["where"].startswith("upper(address) LIKE '34%GILMORE%STREET%")
            return httpx.Response(200, json={"features": [{"attributes": ADDRESS}]})
        if "LandParcelPropertyFramework/MapServer/4/query" in url:
            if form["where"] != "lotplan = '1RP731159'":
                return httpx.Response(200, json={"features": []})
            return httpx.Response(
                200, json={"features": [{"attributes": PARCEL, "geometry": {"rings": RINGS}}]}
            )
        for (service, layer), count in counts.items():
            if f"{service}/MapServer/{layer}/query" in url:
                assert json.loads(form["geometry"])["rings"] == RINGS
                return httpx.Response(200, json={"count": count})
        return httpx.Response(200, json={"count": 0})

    return httpx.MockTransport(handler), calls


OVERLAYS = {("PlanningCadastre/CoastalManagement", 11): 1, ("Biota/VegetationManagement", 103): 2}


def test_address_pattern() -> None:
    assert (
        address_pattern("34 Gilmore St, Bentley Park QLD 4869") == "34%GILMORE%STREET%BENTLEY%PARK%"
    )
    assert address_pattern("1/34 Gilmore Rd") == "%1/34%GILMORE%ROAD%"
    assert address_pattern("O'Brien Street") == "%O''BRIEN%STREET%"
    assert address_pattern("12") is None
    assert address_pattern("'; drop table x; --") == "%''%DROP%TABLE%X%--%"


def test_parse_lot_plan() -> None:
    assert parse_lot_plan("Lot 12 on RP123456") == "12RP123456"
    assert parse_lot_plan("12rp123456") == "12RP123456"
    assert parse_lot_plan("12 SP 1234") == "12SP1234"
    assert parse_lot_plan("12 on RP1' OR 1=1") is None


def test_vessel_list_parsing() -> None:
    records = parse_vessel_list(read_first_sheet(xlsx(VESSEL_ROWS)))
    assert list(records) == ["412345"]
    vessel = records["412345"]
    assert (vessel.name, vessel.displayed_identifier, vessel.length_m) == (
        "Reef Runner",
        "QF123",
        "12.4",
    )
    assert "Owner Name" not in vessel.fields
    assert vessel.fields["Class"] == "1C"
    assert normalise_uvi(" 412-345 ") == "412345"
    assert normalise_uvi("x") is None


async def test_parcel_report_with_overlays_and_a_failed_service() -> None:
    transport, _ = fake_government(OVERLAYS, fail="CoastalManagement/MapServer/7/")
    async with httpx.AsyncClient(transport=transport) as http:
        report = await QldSpatial(http, BASE).parcel("1RP731159")
    assert report is not None
    assert report.lot_plan_label == "Lot 1 on RP731159"
    assert str(report.land_area_m2) == "774.00"
    assert report.lga == "cairns"
    assert [o.key for o in report.overlays] == ["storm_tide_high", "remnant_vegetation"]
    assert report.constraints == ["flooding", "vegetation"]
    assert report.overlays_failed == ["State coastal hazard mapping"]
    assert report.overlays_checked == ["State vegetation management mapping"]
    assert any("Zone" in n.label for n in report.not_checked)


async def test_amsa_list_is_found_on_the_page_and_cached() -> None:
    transport, calls = fake_government()
    settings = make_settings(amsa_vessel_list_page_url=AMSA_PAGE)
    async with httpx.AsyncClient(transport=transport) as http:
        vessels = AmsaVesselList(http, settings)
        found, listed = await vessels.find("412345")
        missing, _ = await vessels.find("999999")
    assert found is not None and found.name == "Reef Runner"
    assert missing is None
    assert listed.source_url == "https://amsa.example/sites/default/files/dcv-vessels-aug26.xlsx"
    assert len(calls) == 2  # page and file, once


# --- Through the API -------------------------------------------------------------------


@pytest.fixture
def settings() -> Settings:
    return make_settings(
        qld_spatial_base_url=BASE,
        amsa_vessel_list_page_url=AMSA_PAGE,
        property_facts_provider=PropertyFactsProviderKind.QLD_SPATIAL,
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    transport, _ = fake_government(OVERLAYS)
    return create_app(settings, lookup_transport=transport)


@pytest.mark.integration
async def test_lookup_endpoints(api: ApiHarness) -> None:
    user = await api.user()
    base = f"/v1/organisations/{user.personal_org_id}/lookups"

    r = await user.get(f"{base}/addresses", params={"q": "34 Gilmore St Bentley Park"})
    assert r.status_code == 200, r.text
    [match] = r.json()["matches"]
    assert match["line1"] == "34 Gilmore Street"
    assert match["suburb"] == "Bentley Park"
    assert match["lot_plan"] == "1RP731159"
    assert match["lot_plan_label"] == "Lot 1 on RP731159"
    assert match["lga"] == "cairns"

    r = await user.get(f"{base}/parcels/Lot 1 on RP731159")
    assert r.status_code == 200, r.text
    parcel = r.json()
    assert parcel["land_area_m2"] == "774.00"
    assert {o["constraint"] for o in parcel["overlays"]} == {"flooding", "vegetation"}
    assert r.json()["overlays_failed"] == []

    assert (await user.get(f"{base}/parcels/2RP1")).status_code == 404
    assert (await user.get(f"{base}/parcels/nonsense!")).status_code == 422

    r = await user.get(f"{base}/vessels/412345")
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Reef Runner"
    assert r.json()["length_m"] == "12.4"
    r = await user.get(f"{base}/vessels/999999")
    assert r.status_code == 404

    outsider = await api.user()
    r = await outsider.get(f"{base}/vessels/412345")
    assert r.status_code == 404


@pytest.mark.integration
async def test_prefill_from_queensland_data(api: ApiHarness) -> None:
    user = await api.user()
    org = f"/v1/organisations/{user.personal_org_id}"
    r = await user.post(f"{org}/projects", json={"vertical": "PLANNING", "title": "Granny flat"})
    project: dict[str, Any] = r.json()
    r = await user.post(f"{org}/projects/{project['id']}/submissions", json={})
    submission = r.json()
    r = await user.put(
        f"{org}/submissions/{submission['id']}/answers",
        json={
            "answers": {
                "property.address": {
                    "line1": "34 Gilmore St",
                    "suburb": "Bentley Park",
                    "state": "QLD",
                    "postcode": "4869",
                }
            }
        },
    )
    assert r.status_code == 200, r.text
    r = await user.get(f"{org}/submissions/{submission['id']}/prefill")
    body = r.json()
    assert body["provider"] == "qld_spatial"
    found = {s["key"]: s for s in body["suggestions"]}
    assert found["property.lga"]["value"] == "cairns"
    assert found["property.lot_plan"]["value"] == "Lot 1 on RP731159"
    assert found["property.land_area_m2"]["value"] == "774"
    assert found["planning.known_constraints"]["value"] == ["flooding", "vegetation"]
    assert "Storm tide" in found["planning.known_constraints"]["source"]
    assert not any(s["is_mock"] for s in body["suggestions"])
