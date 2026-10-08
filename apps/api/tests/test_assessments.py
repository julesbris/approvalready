"""Assessments end to end: submitted answers → published rules → findings with confidence,
trace and sources; version pinning, reproducibility, scope, tenant isolation.

The test database is shared, so every PLANNING rule set created here is scoped to a lot
plan unique to its test (``applies_when``); other tests' rule sets are out of scope.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.db.tenant import bind_tenant
from app.modules.assessments import service as assessments
from app.modules.assessments.models import Assessment
from tests.harness import ApiHarness, User, platform_user
from tests.regulatory_helpers import ADMIN, content, published_rule, reference, rule_set, unique

pytestmark = pytest.mark.integration

ADDRESS = {"line1": "1 Example St", "suburb": "Cairns", "state": "QLD", "postcode": "4870"}
FLOOR_OVER_80 = {
    "fact": "planning.secondary_dwelling_floor_area_m2",
    "op": "greater_than",
    "value": 80,
}
LAND_AT_LEAST_600 = {"fact": "property.land_area_m2", "op": "greater_equal", "value": 600}
STARTS_2027 = {"fact": "planning.target_start_date", "op": "greater_equal", "value": "2027-01-01"}


def org_url(user: User) -> str:
    return f"/v1/organisations/{user.personal_org_id}"


async def submitted_project(user: User, lot_plan: str, **answers: Any) -> dict[str, Any]:
    org = org_url(user)
    r = await user.post(f"{org}/projects", json={"vertical": "PLANNING", "title": "Granny flat"})
    assert r.status_code == 201, r.text
    project = r.json()
    r = await user.post(f"{org}/projects/{project['id']}/submissions", json={})
    submission = r.json()
    values = {
        "property.address": ADDRESS,
        "property.lot_plan": lot_plan,
        "property.land_area_m2": 812.25,
        "property.has_existing_dwelling": True,
        "planning.development_type": "secondary_dwelling",
        "planning.secondary_dwelling_bedrooms": 1,
        "planning.secondary_dwelling_floor_area_m2": 92.5,
        "planning.storeys": 1,
        **answers,
    }
    values = {k: v for k, v in values.items() if v is not None}
    r = await user.put(f"{org}/submissions/{submission['id']}/answers", json={"answers": values})
    assert r.status_code == 200, r.text
    r = await user.post(f"{org}/submissions/{submission['id']}/submit")
    assert r.status_code == 200, r.text
    return project


def scoped(lot_plan: str, *extra: dict[str, Any]) -> dict[str, Any]:
    return {"all": [{"fact": "property.lot_plan", "op": "equals", "value": lot_plan}, *extra]}


async def run(user: User, project_id: str) -> Any:
    return await user.post(f"{org_url(user)}/projects/{project_id}/assessments")


def ours(assessment: dict[str, Any], rule_set_id: str) -> list[dict[str, Any]]:
    return [f for f in assessment["finding_list"] if f["rule_set_id"] == rule_set_id]


async def test_assessment_end_to_end(api: ApiHarness) -> None:
    staff = await platform_user(api, "STAFF")
    admin = await platform_user(api, "ADMIN")
    lot = unique("LOT")
    rs = await rule_set(staff, vertical="PLANNING", applies_when=scoped(lot))
    verified = await reference(staff)
    unverified = await reference(staff, verify=False)
    size = await published_rule(admin, rs["id"], FLOOR_OVER_80, [verified["id"]])
    land = await published_rule(admin, rs["id"], LAND_AT_LEAST_600, [unverified["id"]])
    start = await published_rule(admin, rs["id"], STARTS_2027, [verified["id"]])

    customer = await api.user()
    project = await submitted_project(customer, lot)
    r = await run(customer, project["id"])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "COMPLETED"
    assert body["engine_version"] == "rules-engine/1"
    assert len(body["facts_hash"]) == 64
    assert body["facts"]["property.land_area_m2"] == {"$decimal": "812.25"}

    findings = {f["rule_version_id"]: f for f in ours(body, rs["id"])}
    assert set(findings) == {size["id"], land["id"], start["id"]}
    f = findings[size["id"]]
    assert (f["result"], f["outcome_type"], f["title"], f["confidence"]) == (
        "MATCH",
        "APPROVAL_REQUIRED",
        "Approval needed",
        "VERIFIED",
    )
    assert f["trace"]["actual"] == "92.5"
    assert f["sources"][0]["reference_id"] == verified["id"]
    assert f["sources"][0]["verification_status"] == "VERIFIED"
    assert f["sources"][0]["citation"] == verified["citation"]

    f = findings[land["id"]]
    assert (f["result"], f["confidence"]) == ("MATCH", "LIKELY")
    assert any("not been verified" in reason for reason in f["confidence_reasons"])

    f = findings[start["id"]]  # target start date not answered
    assert (f["result"], f["outcome_type"], f["confidence"]) == ("UNKNOWN", None, "UNKNOWN")
    assert f["missing_facts"] == ["planning.target_start_date"]
    assert "planning.target_start_date" in body["fact_labels"]

    assert body["overall_confidence"] == "UNKNOWN"  # the weakest finding
    scopes = {s["rule_set_id"]: s["scope"] for s in body["rule_sets"]}
    assert scopes[rs["id"]] == "IN_SCOPE"
    assert all(s == "OUT_OF_SCOPE" for k, s in scopes.items() if k != rs["id"])

    # The project moved to "assessed" and lists the assessment.
    org = org_url(customer)
    detail = (await customer.get(f"{org}/projects/{project['id']}")).json()
    assert detail["status"] == "ASSESSED"
    assert detail["latest_assessment"]["id"] == body["id"]
    events = (await customer.get(f"{org}/projects/{project['id']}/status-events")).json()
    assert events[-1]["to_status"] == "ASSESSED"
    listed = (await customer.get(f"{org}/projects/{project['id']}/assessments")).json()
    assert [a["id"] for a in listed] == [body["id"]]
    assert listed[0]["findings"] == len(body["finding_list"])
    assert (await customer.get(f"{org}/assessments/{body['id']}")).json() == body

    audit = (await customer.get(f"{org}/audit-events")).json()
    assert any(e["action"] == "assessment.run" for e in audit)

    # Reproducible: the stored facts and pinned rule versions give identical traces.
    async with api.app.state.resources.session_factory() as db:
        await bind_tenant(db, uuid.UUID(customer.personal_org_id))
        stored = (
            await db.execute(select(Assessment).where(Assessment.id == uuid.UUID(body["id"])))
        ).scalar_one()
        assert await assessments.replay_matches(db, stored)


async def test_assessment_needs_submitted_answers(api: ApiHarness) -> None:
    customer = await api.user()
    org = org_url(customer)
    project = (
        await customer.post(f"{org}/projects", json={"vertical": "PLANNING", "title": "Shed"})
    ).json()
    r = await run(customer, project["id"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "answers_not_submitted"

    project = await submitted_project(customer, unique("LOT"))
    r = await customer.post(f"{org}/projects/{project['id']}/status", json={"status": "ARCHIVED"})
    assert r.status_code == 200
    r = await run(customer, project["id"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "project_archived"


async def test_versions_are_pinned_and_source_changes_only_affect_new_runs(
    api: ApiHarness,
) -> None:
    staff = await platform_user(api, "STAFF")
    admin = await platform_user(api, "ADMIN")
    lot = unique("LOT")
    rs = await rule_set(staff, vertical="PLANNING", applies_when=scoped(lot))
    ref = await reference(staff)
    v1 = await published_rule(admin, rs["id"], FLOOR_OVER_80, [ref["id"]])

    customer = await api.user()
    project = await submitted_project(customer, lot)
    first = (await run(customer, project["id"])).json()
    assert [(f["result"], f["confidence"]) for f in ours(first, rs["id"])] == [
        ("MATCH", "VERIFIED")
    ]

    # The rule changes (threshold raised) and its source is disputed.
    v2 = (await staff.post(f"{ADMIN}/rules/{v1['rule_id']}/versions")).json()
    raised = {**FLOOR_OVER_80, "value": 100}
    r = await staff.put(f"{ADMIN}/rule-versions/{v2['id']}", json=content(raised, [ref["id"]]))
    assert r.status_code == 200
    assert (await admin.post(f"{ADMIN}/rule-versions/{v2['id']}/publish")).status_code == 200
    r = await staff.post(
        f"{ADMIN}/source-references/{ref['id']}/review",
        json={"action": "DISPUTE", "notes": "Under review"},
    )
    assert r.status_code == 200

    org = org_url(customer)
    unchanged = (await customer.get(f"{org}/assessments/{first['id']}")).json()
    assert unchanged == first  # stored results never move

    second = (await run(customer, project["id"])).json()
    [finding] = ours(second, rs["id"])
    assert finding["rule_version_id"] == v2["id"]
    assert (finding["result"], finding["outcome_type"]) == ("NO_MATCH", "NOT_REQUIRED")
    assert finding["confidence"] == "REVIEW_REQUIRED"
    assert finding["sources"][0]["verification_status"] == "DISPUTED"
    assert second["facts_hash"] == first["facts_hash"]  # same answers

    async with api.app.state.resources.session_factory() as db:
        await bind_tenant(db, uuid.UUID(customer.personal_org_id))
        for a in (first, second):
            stored = (
                await db.execute(select(Assessment).where(Assessment.id == uuid.UUID(a["id"])))
            ).scalar_one()
            assert await assessments.replay_matches(db, stored)


async def test_scope_out_and_needs_information(api: ApiHarness) -> None:
    staff = await platform_user(api, "STAFF")
    admin = await platform_user(api, "ADMIN")
    lot = unique("LOT")
    rs = await rule_set(staff, vertical="PLANNING", applies_when=scoped(lot, LAND_AT_LEAST_600))
    ref = await reference(staff)
    await published_rule(admin, rs["id"], FLOOR_OVER_80, [ref["id"]])
    customer = await api.user()

    # A lot no rule set covers: said plainly, never "nothing required".
    elsewhere = await submitted_project(customer, unique("LOT"))
    body = (await run(customer, elsewhere["id"])).json()
    assert body["status"] == "NO_APPLICABLE_RULES"
    assert body["overall_confidence"] == "UNKNOWN"
    assert body["finding_list"] == []

    # Our lot, but the land area that decides scope is missing.
    unknown = await submitted_project(customer, lot, **{"property.land_area_m2": None})
    body = (await run(customer, unknown["id"])).json()
    [scope] = [s for s in body["rule_sets"] if s["rule_set_id"] == rs["id"]]
    assert scope["scope"] == "NEEDS_INFORMATION"
    assert scope["missing_facts"] == ["property.land_area_m2"]
    assert body["status"] == "COMPLETED" and body["overall_confidence"] == "UNKNOWN"
    assert ours(body, rs["id"]) == []

    # Small lot: out of scope.
    small = await submitted_project(customer, lot, **{"property.land_area_m2": 400})
    body = (await run(customer, small["id"])).json()
    assert [s["scope"] for s in body["rule_sets"] if s["rule_set_id"] == rs["id"]] == [
        "OUT_OF_SCOPE"
    ]


async def test_assessments_are_tenant_isolated_and_append_only(api: ApiHarness) -> None:
    alice, bob = await api.user(name="Alice"), await api.user(name="Bob")
    project = await submitted_project(alice, unique("LOT"))
    assessment = (await run(alice, project["id"])).json()

    assert (await bob.get(f"{org_url(bob)}/assessments/{assessment['id']}")).status_code == 404
    assert (await bob.get(f"{org_url(alice)}/assessments/{assessment['id']}")).status_code == 404
    assert (await run(bob, project["id"])).status_code == 404
    r = await bob.post(
        f"/v1/organisations/{alice.personal_org_id}/projects/{project['id']}/assessments"
    )
    assert r.status_code == 404

    factory = api.app.state.resources.session_factory
    for statement in (
        "UPDATE assessment SET overall_confidence = 'VERIFIED'",
        "DELETE FROM assessment",
        "UPDATE assessment_finding SET confidence = 'VERIFIED'",
        "DELETE FROM assessment_finding",
    ):
        async with factory() as db:
            await bind_tenant(db, uuid.UUID(alice.personal_org_id))
            with pytest.raises(DBAPIError, match="permission denied"):
                await db.execute(text(statement))
            await db.rollback()
