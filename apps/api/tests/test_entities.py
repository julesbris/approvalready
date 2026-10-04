"""Properties, vessels and business profiles; linking them to projects."""

from __future__ import annotations

import pytest

from tests.harness import ApiHarness

pytestmark = pytest.mark.integration

ADDRESS = {"line1": "1 Esplanade", "suburb": "Cairns City", "state": "QLD", "postcode": "4870"}
VALID_ABN = "51824753556"
VALID_ACN = "000000019"  # ASIC's published example ACN


def base(org_id: str) -> str:
    return f"/v1/organisations/{org_id}"


async def test_property_lifecycle(api: ApiHarness) -> None:
    user = await api.user()
    url = f"{base(user.personal_org_id)}/properties"
    r = await user.post(
        url,
        json={
            "address": ADDRESS,
            "lot_plan": "12RP123456",
            "land_area_m2": "607.5",
            "relationship": "LANDLORD",
        },
    )
    assert r.status_code == 201, r.text
    prop = r.json()
    assert prop["address"]["suburb"] == "Cairns City"
    assert prop["relationships"] == ["LANDLORD"]
    assert float(prop["land_area_m2"]) == 607.5

    r = await user.patch(
        f"{url}/{prop['id']}", json={"address": {**ADDRESS, "line1": "2 Esplanade"}}
    )
    assert r.status_code == 200
    assert r.json()["address"]["line1"] == "2 Esplanade"
    assert (await user.get(url)).json()[0]["address"]["line1"] == "2 Esplanade"

    audit = (await user.get(f"{base(user.personal_org_id)}/audit-events")).json()
    updated = next(e for e in audit if e["action"] == "property.updated")
    assert updated["details"] == {"fields": ["address"]}  # field names, never values

    assert (await user.delete(f"{url}/{prop['id']}")).status_code == 204
    assert (await user.get(f"{url}/{prop['id']}")).status_code == 404
    assert (await user.get(url)).json() == []


@pytest.mark.parametrize(
    "address",
    [
        {**ADDRESS, "postcode": "487"},
        {**ADDRESS, "state": "Queensland"},
        {**ADDRESS, "line1": ""},
        {**ADDRESS, "country": "AU"},
    ],
)
async def test_invalid_address_rejected(api: ApiHarness, address: dict[str, str]) -> None:
    user = await api.user()
    r = await user.post(f"{base(user.personal_org_id)}/properties", json={"address": address})
    assert r.status_code == 422


async def test_vessel_and_business_profile(api: ApiHarness) -> None:
    user = await api.user()
    org = base(user.personal_org_id)
    r = await user.post(
        f"{org}/vessels",
        json={
            "name": "Reef Runner",
            "vessel_type": "MOTOR",
            "length_m": 12.4,
            "propulsion": "OUTBOARD",
        },
    )
    assert r.status_code == 201, r.text
    vessel = r.json()
    r = await user.patch(f"{org}/vessels/{vessel['id']}", json={"max_passengers": 24})
    assert r.json()["max_passengers"] == 24 and r.json()["name"] == "Reef Runner"
    assert (
        await user.post(f"{org}/vessels", json={"name": "X", "vessel_type": "SUB"})
    ).status_code == 422
    assert (
        await user.post(f"{org}/vessels", json={"name": "X", "vessel_type": "SAIL", "length_m": 0})
    ).status_code == 422

    r = await user.post(
        f"{org}/business-profiles",
        json={
            "legal_name": "Reef Tours Pty Ltd",
            "entity_type": "COMPANY",
            "abn": "51 824 753 556",
            "acn": "000 000 019",
            "employee_band": "5_19",
            "address": ADDRESS,
        },
    )
    assert r.status_code == 201, r.text
    business = r.json()
    assert (business["abn"], business["acn"]) == (VALID_ABN, VALID_ACN)
    assert business["address"]["postcode"] == "4870"
    for bad in ({"abn": "51824753557"}, {"acn": "000000018"}, {"employee_band": "LOTS"}):
        r = await user.post(
            f"{org}/business-profiles", json={"legal_name": "X", "entity_type": "TRUST", **bad}
        )
        assert r.status_code == 422, bad


async def test_projects_link_to_matching_entities_only(api: ApiHarness) -> None:
    user = await api.user()
    other = await api.user()
    org = base(user.personal_org_id)
    prop = (await user.post(f"{org}/properties", json={"address": ADDRESS})).json()
    vessel = (await user.post(f"{org}/vessels", json={"name": "V", "vessel_type": "SAIL"})).json()
    foreign = (
        await other.post(f"{base(other.personal_org_id)}/properties", json={"address": ADDRESS})
    ).json()

    r = await user.post(
        f"{org}/projects",
        json={"vertical": "PLANNING", "title": "Extension", "property_id": prop["id"]},
    )
    assert r.status_code == 201
    project = r.json()
    assert project["property_id"] == prop["id"]

    # Wrong kind of subject for the vertical.
    r = await user.post(
        f"{org}/projects", json={"vertical": "PLANNING", "title": "x", "vessel_id": vessel["id"]}
    )
    assert r.json()["detail"]["code"] == "subject_not_allowed"
    # Another organisation's property does not exist from here.
    r = await user.post(
        f"{org}/projects", json={"vertical": "SELL", "title": "x", "property_id": foreign["id"]}
    )
    assert r.json()["detail"]["code"] == "subject_not_found"
    r = await user.patch(f"{org}/projects/{project['id']}", json={"property_id": foreign["id"]})
    assert r.json()["detail"]["code"] == "subject_not_found"

    # A property in use can't be deleted.
    r = await user.delete(f"{org}/properties/{prop['id']}")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "in_use"
