"""Listing import and the free property report, against stand-ins for every outside
service (no network in tests)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import PropertyFactsProviderKind, Settings
from app.main import create_app
from app.modules.lookups.listing import domain_details, parse_listing_url
from app.modules.property_report.scores import neighbourhood_scores, overall
from app.modules.property_report.service import (
    local_schools_section,
    people_section,
    surroundings_section,
)
from app.modules.property_report.sources import (
    Nearby,
    Place,
    Suburb,
    _norm_lga,
    distance_to_line,
    last_twelve_months,
    places_from,
    sdmx_series,
    surroundings_from,
)
from tests.conftest import make_settings
from tests.harness import ApiHarness
from tests.test_lookups import BASE, OVERLAYS, fake_government

ABS_GEO = "https://abs.example/arcgis/rest/services"
ABS_DATA = "https://absdata.example/rest"
OVERPASS = "https://overpass.example/api/interpreter"
QPS = "https://qps.example/Crime%20Statistics"
DOMAIN = "https://domain.example"

CRIME_HEADER = "LGA Name,Month Year,Offences Against the Person,Offences Against Property,Unlawful Entry,Unlawful Use of Motor Vehicle,Other Property Damage,Drug Offences\n"  # noqa: E501


def _crime_rows(name: str, months: list[str], value: float) -> str:
    return "".join(
        f"{name},{m},{value},{value * 4},{value},{value},{value},{value}\n" for m in months
    )


MONTHS = ["DEC98", "AUG25", "SEP25", "OCT25", "NOV25", "DEC25", "JAN26", "FEB26", "MAR26",
          "APR26", "MAY26", "JUN26", "JUL26", "AUG26"]  # fmt: skip
LGA_CSV = CRIME_HEADER + _crime_rows("Cairns Regional Council", MONTHS, 100.0)
QLD_CSV = CRIME_HEADER.replace("LGA Name,", "") + "".join(
    f"{m},50,200,50,50,50,50\n" for m in MONTHS
)


def sdmx(dims: list[list[str]], series: dict[str, float]) -> dict[str, Any]:
    return {
        "data": {
            "dataSets": [{"series": {k: {"observations": {"0": [v]}} for k, v in series.items()}}],
            "structures": [
                {
                    "dimensions": {
                        "series": [{"values": [{"id": c} for c in codes]} for codes in dims]
                    }
                }
            ],
        }
    }


G02 = sdmx(
    [["1", "4", "6"], ["30001"], ["SAL"], ["3"]],
    {"0:0:0:0": 33, "1:0:0:0": 1500, "2:0:0:0": 400},
)
G01 = sdmx(
    [["3"], ["P_1", "0_4", "25_34"], ["30001"], ["SAL"], ["3"]],
    {"0:0:0:0:0": 1000, "0:1:0:0:0": 80, "0:2:0:0:0": 150},
)
G37 = sdmx(
    [["_T", "1", "2", "R_T"], ["_T", "11", "3"], ["30001"], ["SAL"], ["3"]],
    {
        "0:0:0:0:0": 400,
        "1:0:0:0:0": 100,
        "2:0:0:0:0": 140,
        "3:0:0:0:0": 150,
        "0:1:0:0:0": 300,
        "0:2:0:0:0": 60,
    },
)
OVERPASS_BODY = {
    "elements": [
        {
            "type": "node",
            "lat": -17.001,
            "lon": 145.7,
            "tags": {"shop": "supermarket", "name": "Woolworths"},
        },
        {"type": "node", "lat": -17.01, "lon": 145.7, "tags": {"shop": "supermarket"}},
        {"type": "way", "center": {"lat": -17.0, "lon": 145.702}, "tags": {"leisure": "park"}},
        {"type": "node", "lat": -17.0005, "lon": 145.7, "tags": {"highway": "bus_stop"}},
    ]
}
DOMAIN_LISTING = {
    "id": 2019123456,
    "objective": "sale",
    "status": "live",
    "propertyTypes": ["house"],
    "bedrooms": 3,
    "bathrooms": 2.0,
    "carspaces": 2,
    "headline": "Family home close to schools",
    "priceDetails": {"canDisplayPrice": True, "displayPrice": "Offers over $650,000"},
    "addressParts": {"displayAddress": "34 Gilmore Street, Bentley Park QLD 4869"},
    "geoLocation": {"latitude": -17.0, "longitude": 145.7},
}


# A highway about 150 m north and an airport about 5 km east of -17.0, 145.7.
SURROUNDINGS_BODY = {
    "elements": [
        {
            "type": "way",
            "tags": {"highway": "primary", "name": "Bruce Highway"},
            "geometry": [{"lat": -16.99865, "lon": 145.69}, {"lat": -16.99865, "lon": 145.71}],
        },
        {
            "type": "way",
            "tags": {"highway": "residential"},
            "geometry": [{"lat": -17.0, "lon": 145.69}, {"lat": -17.0, "lon": 145.71}],
        },
        {
            "type": "node",
            "tags": {"aeroway": "aerodrome", "name": "Cairns Airport"},
            "lat": -17.0,
            "lon": 145.747,
        },
    ]
}


def fake_everything() -> httpx.MockTransport:
    government, _ = fake_government(OVERLAYS)

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/ASGS2021/SAL/MapServer/0/query" in url:
            attrs = {
                "sal_code_2021": "30001",
                "sal_name_2021": "Bentley Park",
                "area_albers_sqkm": 5,
            }
            return httpx.Response(200, json={"features": [{"attributes": attrs}]})
        if url.startswith(ABS_DATA):
            for flow, body in (("C21_G02_SAL", G02), ("C21_G01_SAL", G01), ("C21_G37_SAL", G37)):
                if flow in url:
                    assert ".30001.SAL.3" in url
                    return httpx.Response(200, json=body)
        if "SchoolsAndSchoolCatchments/MapServer/1/query" in url:
            attrs = {"centre_name": "Bentley Park State School"}
            return httpx.Response(200, json={"features": [{"attributes": attrs}]})
        if "SchoolsAndSchoolCatchments/MapServer/4/query" in url:
            feature = {
                "attributes": {"centre_name": "Bentley Park State School"},
                "geometry": {"x": 145.705, "y": -17.0},
            }
            return httpx.Response(200, json={"features": [feature]})
        if "SchoolsAndSchoolCatchments" in url:
            return httpx.Response(200, json={"features": []})
        if "BasinOnePercentAEP" in url:
            return httpx.Response(200, json={"count": 0})
        if url == OVERPASS and b"aerodrome" in request.content:
            return httpx.Response(200, json=SURROUNDINGS_BODY)
        if url == OVERPASS:
            assert b"supermarket" in request.content
            return httpx.Response(200, json=OVERPASS_BODY)
        if url.startswith(QPS):
            return httpx.Response(200, text=LGA_CSV if "LGA_" in url else QLD_CSV)
        if url.startswith(DOMAIN):
            assert request.headers["x-api-key"] == "test-key"
            if url.endswith("/v1/listings/2019123456"):
                return httpx.Response(200, json=DOMAIN_LISTING)
            return httpx.Response(404)
        return government.handle_request(request)

    return httpx.MockTransport(handler)


# --- Pure helpers ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "site", "address", "listing_id"),
    [
        (
            "https://www.domain.com.au/34-gilmore-street-bentley-park-qld-4869-2019123456",
            "domain",
            "34 Gilmore Street Bentley Park QLD 4869",
            "2019123456",
        ),
        (
            "www.realestate.com.au/property-house-qld-bentley+park-143123456",
            "realestate",
            "Bentley Park QLD",
            "143123456",
        ),
        (
            "https://www.homely.com.au/homes/34-gilmore-street-bentley-park-qld-4869/123",
            "homely",
            "34 Gilmore Street Bentley Park QLD 4869",
            None,
        ),
        (
            "https://www.property.com.au/qld/bentley-park-4869/gilmore-st/34-pid-1234567/",
            "property_com_au",
            "34 Gilmore St Bentley Park QLD 4869",
            None,
        ),
        ("https://www.facebook.com/marketplace/item/1234", "facebook", None, None),
    ],
)
def test_listing_links_are_read_without_fetching(
    url: str, site: str, address: str | None, listing_id: str | None
) -> None:
    link = parse_listing_url(url)
    assert link is not None
    assert (link.site.key, link.address_text, link.listing_id) == (site, address, listing_id)


def test_listing_link_rejects_non_links() -> None:
    assert parse_listing_url("not a link") is None
    assert (
        parse_listing_url("realestate.com.au/property-house-qld-cairns-1").site.key == "realestate"
    )  # type: ignore[union-attr]


def test_domain_details() -> None:
    d = domain_details(DOMAIN_LISTING)
    assert (d.bedrooms, d.bathrooms, d.car_spaces, d.property_type) == (3, 2, 2, "House")
    assert d.price_text == "Offers over $650,000"
    assert domain_details({"propertyTypes": ["apartmentUnitFlat"]}).property_type == "Apartment"


def test_sdmx_series() -> None:
    assert sdmx_series(G02)[("4", "30001", "SAL", "3")] == 1500
    assert sdmx_series({"nonsense": 1}) == {}


def test_places_nearest_and_counts() -> None:
    places = {p.key: p for p in places_from(OVERPASS_BODY, -17.0, 145.7)}
    assert places["supermarket"].nearest_name == "Woolworths"
    assert places["supermarket"].count == 2
    assert 100 < places["supermarket"].nearest_m < 120
    assert places["park"].nearest_name is None


def test_distance_to_a_line() -> None:
    # A line running east-west 0.001 degrees (about 111 m) north of the point.
    assert distance_to_line(-17.0, 145.7, [(-16.999, 145.69), (-16.999, 145.71)]) == 111
    assert distance_to_line(-17.0, 145.7, []) is None


def test_surroundings_nearest_of_each() -> None:
    found = {n.key: n for n in surroundings_from(SURROUNDINGS_BODY, -17.0, 145.7)}
    assert 140 < (found["major_road"].distance_m or 0) < 160
    assert found["major_road"].name == "Bruce Highway"
    assert 4900 < (found["airport"].distance_m or 0) < 5100
    assert found["railway"].distance_m is None
    section = surroundings_section(list(found.values()))
    assert [i.label for i in section.items] == [
        "Major road or motorway: Bruce Highway",
        "Airport or airfield: Cairns Airport",
    ]
    assert section.facts[0].value == "2 of 6 checked"
    assert surroundings_section(None).status == "unavailable"


def test_neighbourhood_scores() -> None:
    places = [
        Place("supermarket", "Supermarket", "Woolworths", 300, 2),
        Place("bus", "Bus stop", None, 1500, 4),
        Place("park", "Park", None, 200, 3),
    ]
    surroundings = [Nearby("major_road", "Major road", 150, 800, None, "Noise.")]
    scores = {s.key: s for s in neighbourhood_scores(places, None, surroundings)}
    assert list(scores) == ["walk", "shops", "transport", "schools", "health", "outdoors", "quiet"]
    assert scores["walk"].score == 2.5  # supermarket and park of the 8 everyday needs
    assert scores["shops"].score == 10.0
    assert scores["transport"].score == 0.0
    assert scores["schools"].summary == "No school or childcare within 2 km."
    assert scores["quiet"].score == 8.0  # a major road at half its 300 m reach takes off 2
    assert "major road 150 m" in scores["quiet"].summary
    assert overall(scores.values()) == round(sum(s.score for s in scores.values()) / 7, 1)
    assert neighbourhood_scores(None, None, None) == []
    assert overall([]) is None


def test_people_compared_with_their_own_state() -> None:
    census = {
        "population": 12000,
        "median_age": 41,
        "household_income": 2000,
        "rented": 40.0,
        "owned_outright": 25.0,
        "separate_house": 50.0,
        "age_groups": [("0 to 4", 6.0)],
    }
    suburb = Suburb(code="10001", name="Newtown", area_km2=2.0)
    section = people_section(suburb, census, "NSW")
    facts = {f.label: f for f in section.facts}
    assert facts["Median household income"].compare == "9% above New South Wales ($1,829)"
    assert facts["Median age"].compare == "New South Wales: 39"
    assert "compared with New South Wales" in section.intro
    charts = {c.title: c for c in section.charts}
    assert charts["Ages"].bars[0].compare is None
    rented = next(b for b in charts["Homes owned and rented"].bars if b.label == "Rented")
    assert (rented.value, rented.compare) == (40.0, 32.6)
    assert charts["Kinds of homes"].compare_label == "New South Wales"


def test_schools_from_openstreetmap_outside_queensland() -> None:
    section = local_schools_section([Place("school", "School", "Newtown Public", 450, 3)])
    assert section.items[0].label == "Nearest school: Newtown Public"
    assert local_schools_section(None).status == "unavailable"


def test_crime_uses_the_latest_twelve_months() -> None:
    import csv
    import io

    rows = list(csv.DictReader(io.StringIO(LGA_CSV)))
    sums, months = last_twelve_months(rows)
    assert months[0] == (2025, 9) and months[-1] == (2026, 8)  # DEC98 is 1998, not 2098
    assert sums["Unlawful Entry"] == 1200
    assert _norm_lga("Cairns Regional Council") == _norm_lga("Cairns Regional")
    assert _norm_lga("Weipa (T)") == _norm_lga("Weipa Town")


# --- Through the API -------------------------------------------------------------------


@pytest.fixture
def settings() -> Settings:
    return make_settings(
        qld_spatial_base_url=BASE,
        abs_geo_base_url=ABS_GEO,
        abs_data_api_base_url=ABS_DATA,
        overpass_url=OVERPASS,
        qps_crime_data_base_url=QPS,
        domain_api_base_url=DOMAIN,
        domain_api_key="test-key",
        property_facts_provider=PropertyFactsProviderKind.QLD_SPATIAL,
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings, lookup_transport=fake_everything())


@pytest.mark.integration
async def test_listing_import_from_domain(api: ApiHarness) -> None:
    user = await api.user()
    base = f"/v1/organisations/{user.personal_org_id}/lookups/listing"
    r = await user.post(
        base,
        json={"url": "https://www.domain.com.au/34-gilmore-st-bentley-park-qld-4869-2019123456"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["site"] == "domain"
    assert body["details"]["bedrooms"] == 3
    assert body["details"]["price_text"] == "Offers over $650,000"
    [match] = body["matches"]
    assert match["lot_plan"] == "1RP731159"

    r = await user.post(
        base,
        json={"url": "https://www.realestate.com.au/property-house-qld-bentley+park-143123456"},
    )
    body = r.json()
    assert body["details"] is None and body["matches"] == []
    assert body["property_type"] == "House"
    assert "only gives the suburb" in body["note"]
    assert "terms" in body["how"]

    assert (await user.post(base, json={"url": "nonsense"})).status_code == 422


@pytest.mark.integration
async def test_property_report(api: ApiHarness) -> None:
    user = await api.user()
    org = f"/v1/organisations/{user.personal_org_id}"
    r = await user.post(
        f"{org}/properties",
        json={
            "address": {
                "line1": "34 Gilmore Street",
                "suburb": "Bentley Park",
                "state": "QLD",
                "postcode": "4869",
                "latitude": -17.0,
                "longitude": 145.7,
            },
            "lot_plan": "1RP731159",
            "bedrooms": 3,
            "bathrooms": 2,
            "property_type": "House",
            "listing_url": "https://www.domain.com.au/34-gilmore-st-bentley-park-qld-4869-2019123456",
        },
    )
    assert r.status_code == 201, r.text
    prop = r.json()
    assert prop["bedrooms"] == 3 and prop["address"]["latitude"] == "-17.000000"

    r = await user.get(f"{org}/properties/{prop['id']}/report")
    assert r.status_code == 200, r.text
    report = r.json()
    sections = {s["key"]: s for s in report["sections"]}
    assert list(sections) == [
        "land",
        "hazards",
        "schools",
        "nearby",
        "surroundings",
        "people",
        "market",
        "safety",
        "checks",
    ]
    assert all(s["status"] != "unavailable" for s in sections.values()), sections
    facts = {f["label"]: f for s in report["sections"] for f in s["facts"]}
    assert facts["The home"]["value"] == "House: 3 bed, 2 bath"
    assert facts["Land area"]["value"] == "774 m²"
    assert facts["Primary state school catchment"]["value"] == "Bentley Park State School"
    assert facts["Median household income"]["value"] == "$1,500 a week"
    assert facts["Median household income"]["compare"] == "10% below Queensland ($1,675)"
    charts = {c["title"]: c for c in sections["people"]["charts"]}
    bars = {b["label"]: b for b in charts["Homes owned and rented"]["bars"]}
    assert (bars["Rented"]["value"], bars["Rented"]["compare"]) == (37.5, 33.1)
    assert charts["Kinds of homes"]["bars"][0]["value"] == 75
    assert sections["surroundings"]["items"][0]["label"] == "Major road or motorway: Bruce Highway"
    scores = {s["key"]: s for s in report["scores"]}
    assert scores["schools"]["score"] > 9.5  # the state school is about 530 m away
    assert scores["quiet"]["score"] < 10
    assert report["overall_score"] is not None
    assert report["finance_url"] == "https://approvalreadyai.com/#contact"
    assert facts["Break-ins (unlawful entry)"]["value"] == "1,200 per 100,000 people"
    assert "100% above Queensland" in facts["Break-ins (unlawful entry)"]["compare"]
    assert [i["label"] for i in sections["hazards"]["items"]] == [
        "Storm tide inundation area (high hazard)",
        "Remnant vegetation (category B on the regulated vegetation management map)",
    ]
    assert sections["nearby"]["items"][0]["label"] == "Bus stop"
    assert any("Bentley Park State School" in h for h in report["headline"])
    assert report["council"] == "Cairns Regional Council"

    r = await user.get(f"{org}/properties/{prop['id']}/report.pdf")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert "property-report-34-gilmore-street" in r.headers["content-disposition"]

    outsider = await api.user()
    r = await outsider.get(f"{org}/properties/{prop['id']}/report")
    assert r.status_code == 404
