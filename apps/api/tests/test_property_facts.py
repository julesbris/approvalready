"""Property facts providers and questionnaire prefill (Milestone 5)."""

from __future__ import annotations

from typing import Any

import pytest

from app.core.config import Environment, PropertyFactsProviderKind, Settings
from app.modules.property_facts.provider import (
    AddressQuery,
    MockProvider,
    NoProvider,
    get_provider,
)
from tests.conftest import make_settings
from tests.harness import ApiHarness, User

MOCK_ADDRESS = {
    "line1": "1 Pretend Street",
    "suburb": "Mockville",
    "state": "QLD",
    "postcode": "4870",
}


@pytest.fixture
def settings() -> Settings:
    return make_settings(property_facts_provider=PropertyFactsProviderKind.MOCK)


def test_default_provider_returns_nothing() -> None:
    assert isinstance(get_provider(make_settings()), NoProvider)


async def test_mock_provider_only_answers_for_mockville() -> None:
    provider = MockProvider()
    facts = await provider.lookup(AddressQuery("1 Pretend St", "Mockville", "QLD", "4870"))
    assert {f.key: f.value for f in facts} == {
        "property.lga": "cairns",
        "property.zone": "low_density_residential",
    }
    assert all(f.is_mock and "made-up" in f.source for f in facts)
    assert await provider.lookup(AddressQuery("1 Esplanade", "Cairns", "QLD", "4870")) == []


def test_mock_provider_is_refused_in_production() -> None:
    with pytest.raises(ValueError, match="PROPERTY_FACTS_PROVIDER=mock"):
        make_settings(
            app_env=Environment.PRODUCTION,
            secret_key="x" * 40,
            cors_origins=["https://app.approvalready.com.au"],
            property_facts_provider=PropertyFactsProviderKind.MOCK,
        )


async def _submission(user: User, **project: Any) -> tuple[str, dict[str, Any]]:
    org = f"/v1/organisations/{user.personal_org_id}"
    r = await user.post(
        f"{org}/projects", json={"vertical": "PLANNING", "title": "Granny flat", **project}
    )
    assert r.status_code == 201, r.text
    r = await user.post(f"{org}/projects/{r.json()['id']}/submissions", json={})
    assert r.status_code in (200, 201), r.text
    return org, r.json()


@pytest.mark.integration
async def test_prefill_from_property_and_provider(api: ApiHarness) -> None:
    user = await api.user()
    org = f"/v1/organisations/{user.personal_org_id}"
    r = await user.post(
        f"{org}/properties",
        json={"address": MOCK_ADDRESS, "lot_plan": "1RP000001", "land_area_m2": "640.5"},
    )
    assert r.status_code == 201, r.text
    org, submission = await _submission(user, property_id=r.json()["id"])
    r = await user.get(f"{org}/submissions/{submission['id']}/prefill")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "mock"
    found = {s["key"]: s for s in body["suggestions"]}
    assert found["property.address"]["value"] == MOCK_ADDRESS
    assert found["property.address"]["source"] == "Your property details"
    assert found["property.lot_plan"]["value"] == "1RP000001"
    assert found["property.land_area_m2"]["value"] == "640.5"
    assert found["property.lga"]["value"] == "cairns" and found["property.lga"]["is_mock"]
    assert found["property.zone"]["label"].startswith("Which zone")

    # Suggestions save through the normal answers endpoint; answered questions drop out.
    answers = {k: s["value"] for k, s in found.items()}
    r = await user.put(f"{org}/submissions/{submission['id']}/answers", json={"answers": answers})
    assert r.status_code == 200, r.text
    r = await user.get(f"{org}/submissions/{submission['id']}/prefill")
    assert r.json()["suggestions"] == []


@pytest.mark.integration
async def test_prefill_uses_the_answered_address_without_a_property(api: ApiHarness) -> None:
    user = await api.user()
    org, submission = await _submission(user)
    r = await user.get(f"{org}/submissions/{submission['id']}/prefill")
    assert r.json()["suggestions"] == []
    r = await user.put(
        f"{org}/submissions/{submission['id']}/answers",
        json={"answers": {"property.address": MOCK_ADDRESS}},
    )
    assert r.status_code == 200
    r = await user.get(f"{org}/submissions/{submission['id']}/prefill")
    assert [s["key"] for s in r.json()["suggestions"]] == ["property.lga", "property.zone"]

    outsider = await api.user()
    r = await outsider.get(f"{org}/submissions/{submission['id']}/prefill")
    assert r.status_code == 404
