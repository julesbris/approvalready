"""Rule authoring: drafts, the publish gate, immutability, versions, retirement.

Rule sets here use the VESSEL vertical so they never affect the PLANNING assessments in
``test_assessments.py`` (the test database is shared across tests).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.harness import ApiHarness, platform_user
from tests.regulatory_helpers import ADMIN, content, published_rule, reference, rule_set, unique

pytestmark = pytest.mark.integration

LENGTH_OVER_12 = {"fact": "vessel.length_m", "op": "greater_than", "value": 12}
TESTS = [
    {
        "name": "long",
        "facts": {"vessel.length_m": {"$decimal": "12.5"}},
        "expected_result": "MATCH",
    },
    {"name": "short", "facts": {"vessel.length_m": 8}, "expected_result": "NO_MATCH"},
    {"name": "unknown", "facts": {}, "expected_result": "UNKNOWN"},
]


async def _new_rule(staff: Any, rule_set_id: str, condition: dict[str, Any] | None = None) -> Any:
    r = await staff.post(
        f"{ADMIN}/rule-sets/{rule_set_id}/rules",
        json={
            "key": unique("rule"),
            "title": "Long vessels",
            "condition": condition or LENGTH_OVER_12,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_only_rule_authors_reach_rules(api: ApiHarness) -> None:
    customer = await api.user()
    assert (await customer.get(f"{ADMIN}/rule-sets")).status_code == 403
    staff = await platform_user(api, "STAFF")
    assert (await staff.get(f"{ADMIN}/rule-sets")).status_code == 200


async def test_conditions_are_validated(api: ApiHarness) -> None:
    staff = await platform_user(api, "STAFF")
    r = await staff.post(
        f"{ADMIN}/rule-sets",
        json={
            "key": f"test.{unique('set')}",
            "vertical": "VESSEL",
            "jurisdiction": "QLD",
            "title": "Bad scope",
            "applies_when": {"fact": "x", "op": "matches", "value": "y"},
        },
    )
    assert r.status_code == 422
    assert set(r.json()["detail"]["fields"]) == {"applies_when"}

    rs = await rule_set(staff)
    r = await staff.post(
        f"{ADMIN}/rule-sets/{rs['id']}/rules",
        json={"key": "bad", "title": "Bad", "condition": {"eval": "__import__('os')"}},
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_condition"
    rule = await _new_rule(staff, rs["id"])
    r = await staff.post(
        f"{ADMIN}/rule-sets/{rs['id']}/rules",
        json={"key": rule["key"], "title": "Duplicate", "condition": LENGTH_OVER_12},
    )
    assert r.status_code == 409


async def test_publish_gate(api: ApiHarness) -> None:
    staff = await platform_user(api, "STAFF")
    admin = await platform_user(api, "ADMIN")
    rs = await rule_set(staff)
    rule = await _new_rule(staff, rs["id"])
    version_id = rule["versions"][0]["id"]
    url = f"{ADMIN}/rule-versions/{version_id}"

    gate = (await staff.get(f"{url}/checks")).json()
    assert gate["ready"] is False
    failing = {c["key"] for c in gate["checks"] if not c["passed"]}
    assert failing == {"effective_from", "outcomes", "basis_source", "test_cases"}
    # The vessel questionnaire asks for vessel.length_m, so nothing to warn about yet.
    assert gate["warnings"] == []

    unverified = await reference(staff, verify=False)
    wrong = [{**TESTS[0], "expected_result": "NO_MATCH"}, TESTS[1]]
    r = await staff.put(url, json=content(LENGTH_OVER_12, [unverified["id"]], test_cases=wrong))
    assert r.status_code == 200, r.text
    assert r.json()["fact_paths"] == ["vessel.length_m"]
    gate = (await staff.get(f"{url}/checks")).json()
    assert [c["key"] for c in gate["checks"] if not c["passed"]] == ["test_cases"]
    assert [t["passed"] for t in gate["test_results"]] == [False, True]
    assert gate["test_results"][0]["trace"]["actual"] == "12.5"
    assert any("not been verified" in w or "Not verified" in w for w in gate["warnings"])

    # Staff may draft but not publish; a blocked publish says why, per check.
    assert (await staff.post(f"{url}/publish")).status_code == 403
    r = await admin.post(f"{url}/publish")
    assert r.status_code == 409 and set(r.json()["detail"]["fields"]) == {"test_cases"}

    disputed = await reference(staff)
    r = await staff.post(
        f"{ADMIN}/source-references/{disputed['id']}/review",
        json={"action": "DISPUTE", "notes": "Wrong clause"},
    )
    assert r.status_code == 200
    r = await staff.put(
        url,
        json=content(LENGTH_OVER_12, [unverified["id"], disputed["id"]], test_cases=TESTS),
    )
    gate = (await staff.get(f"{url}/checks")).json()
    assert [c["key"] for c in gate["checks"] if not c["passed"]] == ["sources_usable"]

    r = await staff.put(url, json=content(LENGTH_OVER_12, [unverified["id"]], test_cases=TESTS))
    assert (await staff.get(f"{url}/checks")).json()["ready"] is True
    r = await admin.post(f"{url}/publish")
    assert r.status_code == 200, r.text
    published = r.json()
    assert published["status"] == "PUBLISHED"
    assert published["published_by"] == admin.id
    assert len(published["content_hash"]) == 64


async def test_draft_validation(api: ApiHarness) -> None:
    staff = await platform_user(api, "STAFF")
    rs = await rule_set(staff)
    rule = await _new_rule(staff, rs["id"])
    url = f"{ADMIN}/rule-versions/{rule['versions'][0]['id']}"
    ref = await reference(staff, verify=False)
    cases: list[tuple[dict[str, Any], str]] = [
        (content(LENGTH_OVER_12, [str(uuid.uuid4())]), "unknown_source"),
        (content(LENGTH_OVER_12, [ref["id"], ref["id"]]), "duplicate_source"),
        (
            content(
                LENGTH_OVER_12,
                [ref["id"]],
                outcomes=[
                    {"on_result": "MATCH", "outcome_type": "INFO", "title": "a"},
                    {"on_result": "MATCH", "outcome_type": "WARNING", "title": "b"},
                ],
            ),
            "duplicate_outcome",
        ),
        (
            content(
                LENGTH_OVER_12,
                [ref["id"]],
                test_cases=[{"name": "x", "facts": {"Not A Path": 1}, "expected_result": "MATCH"}],
            ),
            "invalid_test_cases",
        ),
        (
            content(LENGTH_OVER_12, [ref["id"]], effective_to="2025-01-01"),
            "invalid_dates",
        ),
    ]
    for body, code in cases:
        r = await staff.put(url, json=body)
        assert r.status_code == 422 and r.json()["detail"]["code"] == code, (code, r.text)

    # A fact no questionnaire collects is allowed, with a warning.
    uncollected = await _new_rule(staff, rs["id"], {"fact": "vessel.hull_colour", "op": "exists"})
    gate = (
        await staff.get(f"{ADMIN}/rule-versions/{uncollected['versions'][0]['id']}/checks")
    ).json()
    assert any("vessel.hull_colour" in w for w in gate["warnings"])


async def test_published_versions_are_immutable(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    staff = await platform_user(api, "STAFF")
    admin = await platform_user(api, "ADMIN")
    rs = await rule_set(staff)
    ref = await reference(staff)
    v1 = await published_rule(admin, rs["id"], LENGTH_OVER_12, [ref["id"]], test_cases=TESTS)
    url = f"{ADMIN}/rule-versions/{v1['id']}"

    r = await staff.put(url, json=content(LENGTH_OVER_12, [ref["id"]], test_cases=TESTS))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "version_immutable"
    assert (await staff.delete(url)).status_code == 409

    # The database refuses too, even for the owner.
    async with owner_sessions() as db:
        for statement in (
            'UPDATE rule_version SET condition = \'{"fact": "x", "op": "exists"}\' WHERE id = :id',
            "UPDATE rule_version SET status = 'DRAFT', published_at = NULL WHERE id = :id",
            "DELETE FROM rule_version WHERE id = :id",
            "UPDATE rule_outcome SET title = 'changed' WHERE rule_version_id = :id",
            "DELETE FROM rule_source WHERE rule_version_id = :id",
            "DELETE FROM rule_test_case WHERE rule_version_id = :id",
            "INSERT INTO rule_fact_dependency (rule_version_id, fact_path) VALUES (:id, 'x.y')",
        ):
            with pytest.raises(DBAPIError, match="immutable"):
                await db.execute(text(statement), {"id": uuid.UUID(v1["id"])})
            await db.rollback()


async def test_new_versions_retire_the_previous_one(api: ApiHarness) -> None:
    staff = await platform_user(api, "STAFF")
    admin = await platform_user(api, "ADMIN")
    rs = await rule_set(staff)
    ref = await reference(staff)
    v1 = await published_rule(admin, rs["id"], LENGTH_OVER_12, [ref["id"]], test_cases=TESTS)

    r = await staff.post(f"{ADMIN}/rules/{v1['rule_id']}/versions")
    assert r.status_code == 201, r.text
    v2 = r.json()
    assert v2["version"] == 2 and v2["status"] == "DRAFT"
    # A copy of the latest version: same content, ready to edit.
    for key in ("condition", "outcomes", "sources", "test_cases", "effective_from"):
        assert v2[key] == v1[key], key
    assert (await staff.post(f"{ADMIN}/rules/{v1['rule_id']}/versions")).status_code == 409

    longer = {"fact": "vessel.length_m", "op": "greater_than", "value": 15}
    tests = [{"name": "15m", "facts": {"vessel.length_m": 15}, "expected_result": "NO_MATCH"}]
    r = await staff.put(
        f"{ADMIN}/rule-versions/{v2['id']}", json=content(longer, [ref["id"]], test_cases=tests)
    )
    assert r.status_code == 200
    r = await admin.post(f"{ADMIN}/rule-versions/{v2['id']}/publish")
    assert r.status_code == 200, r.text

    rule = (await staff.get(f"{ADMIN}/rules/{v1['rule_id']}")).json()
    assert [(v["version"], v["status"]) for v in rule["versions"]] == [
        (1, "RETIRED"),
        (2, "PUBLISHED"),
    ]
    old = (await staff.get(f"{ADMIN}/rule-versions/{v1['id']}")).json()
    assert old["condition"] == LENGTH_OVER_12  # retired versions stay readable, unchanged
    listed = (await staff.get(f"{ADMIN}/rule-sets/{rs['id']}")).json()["rules"][0]
    assert listed["published_version"] == 2 and listed["draft_version_id"] is None

    # A third draft can be discarded; retiring leaves the rule with nothing published.
    v3 = (await staff.post(f"{ADMIN}/rules/{v1['rule_id']}/versions")).json()
    assert (await staff.delete(f"{ADMIN}/rule-versions/{v3['id']}")).status_code == 204
    assert (await staff.post(f"{ADMIN}/rule-versions/{v2['id']}/retire")).status_code == 403
    r = await admin.post(f"{ADMIN}/rule-versions/{v2['id']}/retire")
    assert r.json()["status"] == "RETIRED"
    assert (await admin.post(f"{ADMIN}/rule-versions/{v2['id']}/retire")).status_code == 409


async def test_try_a_version_against_facts(api: ApiHarness) -> None:
    staff = await platform_user(api, "STAFF")
    rs = await rule_set(staff)
    rule = await _new_rule(staff, rs["id"])
    version_id = rule["versions"][0]["id"]
    ref = await reference(staff)
    await staff.put(
        f"{ADMIN}/rule-versions/{version_id}",
        json=content(LENGTH_OVER_12, [ref["id"]], max_confidence="LIKELY"),
    )
    r = await staff.post(
        f"{ADMIN}/rule-versions/{version_id}/evaluate", json={"facts": {"vessel.length_m": 20}}
    )
    body = r.json()
    assert body["result"] == "MATCH"
    assert body["outcome"]["title"] == "Approval needed"
    assert body["confidence"] == "LIKELY"  # capped
    r = await staff.post(f"{ADMIN}/rule-versions/{version_id}/evaluate", json={"facts": {}})
    assert r.json()["missing_facts"] == ["vessel.length_m"]
    assert r.json()["outcome"] is None
