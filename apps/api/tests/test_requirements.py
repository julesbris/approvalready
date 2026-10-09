"""Outcome payloads → approval and evidence requirements, referral categories, limitations
and project tasks when an assessment runs (Milestone 5).

Fictional test data only; PLANNING rule sets are scoped to a lot plan unique to each test.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.tenant import bind_tenant
from app.modules.rules.payload import Certainty, OutcomePayload, certainty_for, validate_payload
from tests.harness import ApiHarness, platform_user
from tests.regulatory_helpers import ADMIN, content, reference, rule_set, unique
from tests.test_assessments import FLOOR_OVER_80, LAND_AT_LEAST_600, org_url, run, scoped
from tests.test_assessments import submitted_project as submitted

pytestmark = pytest.mark.integration

APPROVAL_PAYLOAD = {
    "approval": {
        "kind": "PLANNING_MATERIAL_CHANGE_OF_USE",
        "authority": "Test Council",
        "pathway": "Code assessment",
    },
    "evidence": [{"kind": "SITE_PLAN", "title": "Site plan", "detail": "Show the parking."}],
    "referral_categories": ["town_planner"],
    "task": "Book a pre-lodgement meeting",
}


# --- Payload validation (pure) ---------------------------------------------------------


def test_certainty_defaults_from_the_outcome_and_can_only_be_lowered() -> None:
    spec = OutcomePayload.model_validate(APPROVAL_PAYLOAD).approval
    assert spec is not None
    assert certainty_for("APPROVAL_REQUIRED", spec) == Certainty.REQUIRED
    assert certainty_for("APPROVAL_LIKELY", spec) == Certainty.LIKELY_REQUIRED
    assert certainty_for("NOT_REQUIRED", spec) == Certainty.NOT_IDENTIFIED
    assert certainty_for("WARNING", spec) == Certainty.MAY_APPLY
    lowered = {**APPROVAL_PAYLOAD["approval"], "certainty": "MAY_APPLY"}  # type: ignore[dict-item]
    assert validate_payload("APPROVAL_REQUIRED", {"approval": lowered}) == {"approval": lowered}
    with pytest.raises(ValueError, match="can't be required"):
        validate_payload("APPROVAL_LIKELY", {"approval": {**lowered, "certainty": "REQUIRED"}})


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"approval": {"kind": "lower case"}}, "approval.kind"),
        ({"evidence": [{"kind": "SITE_PLAN"}]}, "evidence.0.title"),
        ({"referral_categories": ["Town Planner"]}, "referral_categories.0"),
        ({"referral_categories": ["town_planner", "town_planner"]}, "list each category once"),
        ({"surprise": True}, "surprise"),
        ({"task": ""}, "task"),
    ],
)
def test_invalid_payloads_are_explained(payload: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_payload("INFO", payload)


def test_empty_payload_is_stored_as_none() -> None:
    assert validate_payload("INFO", {}) is None
    assert validate_payload("INFO", None) is None


# --- Authoring -------------------------------------------------------------------------


async def test_payloads_are_validated_saved_and_copied_to_new_versions(api: ApiHarness) -> None:
    staff = await platform_user(api, "STAFF")
    admin = await platform_user(api, "ADMIN")
    rs = await rule_set(staff, vertical="PLANNING", applies_when=scoped(unique("LOT")))
    ref = await reference(staff)
    r = await staff.post(
        f"{ADMIN}/rule-sets/{rs['id']}/rules",
        json={"key": unique("rule"), "title": "Payload rule", "condition": FLOOR_OVER_80},
    )
    version_id = r.json()["versions"][0]["id"]
    body = content(FLOOR_OVER_80, [ref["id"]])
    body["outcomes"][0]["payload"] = {"approval": {"kind": "bad kind"}}
    r = await staff.put(f"{ADMIN}/rule-versions/{version_id}", json=body)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "invalid_payload"
    assert "outcomes.0.payload" in r.json()["detail"]["fields"]

    body["outcomes"][0]["payload"] = APPROVAL_PAYLOAD
    r = await staff.put(f"{ADMIN}/rule-versions/{version_id}", json=body)
    assert r.status_code == 200, r.text
    saved = {o["on_result"]: o for o in r.json()["outcomes"]}
    assert saved["MATCH"]["payload"] == APPROVAL_PAYLOAD
    assert saved["NO_MATCH"]["payload"] is None

    published = (await admin.post(f"{ADMIN}/rule-versions/{version_id}/publish")).json()
    draft = (await staff.post(f"{ADMIN}/rules/{published['rule_id']}/versions")).json()
    copied = {o["on_result"]: o for o in draft["outcomes"]}
    assert copied["MATCH"]["payload"] == APPROVAL_PAYLOAD


async def test_rule_set_limitations(api: ApiHarness) -> None:
    staff = await platform_user(api, "STAFF")
    rs = await rule_set(staff)
    assert rs["limitations"] == []
    r = await staff.patch(
        f"{ADMIN}/rule-sets/{rs['id']}", json={"limitations": ["Does not check overlays."]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["limitations"] == ["Does not check overlays."]
    r = await staff.patch(f"{ADMIN}/rule-sets/{rs['id']}", json={"limitations": [""]})
    assert r.status_code == 422


# --- Assessments -----------------------------------------------------------------------


async def _publish(
    admin: Any, rule_set_id: str, condition: dict[str, Any], body: dict[str, Any]
) -> dict[str, Any]:
    r = await admin.post(
        f"{ADMIN}/rule-sets/{rule_set_id}/rules",
        json={"key": unique("rule"), "title": "Test rule", "condition": condition},
    )
    assert r.status_code == 201, r.text
    version_id = r.json()["versions"][0]["id"]
    r = await admin.put(f"{ADMIN}/rule-versions/{version_id}", json=body)
    assert r.status_code == 200, r.text
    r = await admin.post(f"{ADMIN}/rule-versions/{version_id}/publish")
    assert r.status_code == 200, r.text
    return dict(r.json())


async def test_findings_become_requirements_referrals_and_tasks(api: ApiHarness) -> None:
    staff = await platform_user(api, "STAFF")
    admin = await platform_user(api, "ADMIN")
    lot = unique("LOT")
    rs = await rule_set(staff, vertical="PLANNING", applies_when=scoped(lot))
    await staff.patch(
        f"{ADMIN}/rule-sets/{rs['id']}",
        json={"limitations": ["Does not check overlays.", "Answers are not verified."]},
    )
    verified = await reference(staff)
    unverified = await reference(staff, verify=False)

    approval = content(FLOOR_OVER_80, [verified["id"]])
    approval["outcomes"][0] = {
        "on_result": "MATCH",
        "outcome_type": "APPROVAL_LIKELY",
        "title": "A development application is likely",
        "payload": APPROVAL_PAYLOAD,
    }
    big = await _publish(admin, rs["id"], FLOOR_OVER_80, approval)

    warning = content(LAND_AT_LEAST_600, [unverified["id"]])
    warning["outcomes"][0] = {
        "on_result": "MATCH",
        "outcome_type": "WARNING",
        "title": "Check the overlay",
        "payload": {
            "approval": {"kind": "PLANNING_OVERLAY_ASSESSMENT"},
            "referral_categories": ["geotechnical_engineer", "town_planner"],
            "task": "Check the overlay map",
        },
    }
    land = await _publish(admin, rs["id"], LAND_AT_LEAST_600, warning)

    customer = await api.user()
    org = org_url(customer)
    project = await submitted(customer, lot)
    r = await run(customer, project["id"])
    assert r.status_code == 201, r.text
    body = r.json()
    findings = {f["rule_version_id"]: f for f in body["finding_list"]}
    big_finding, land_finding = findings[big["id"]], findings[land["id"]]
    assert big_finding["referral_categories"] == ["town_planner"]

    approvals = {a["finding_id"]: a for a in body["approval_requirements"]}
    assert approvals[big_finding["id"]] | {"id": None} == {
        "id": None,
        "finding_id": big_finding["id"],
        "kind": "PLANNING_MATERIAL_CHANGE_OF_USE",
        "title": "A development application is likely",
        "authority": "Test Council",
        "pathway": "Code assessment",
        "certainty": "LIKELY_REQUIRED",
        "confidence": "VERIFIED",
    }
    # A warning can only say an approval "may apply", and inherits its finding's confidence.
    overlay = approvals[land_finding["id"]]
    assert (overlay["certainty"], overlay["confidence"]) == ("MAY_APPLY", "LIKELY")
    assert overlay["title"] == "Check the overlay"
    assert [(e["kind"], e["title"], e["detail"]) for e in body["evidence_requirements"]] == [
        ("SITE_PLAN", "Site plan", "Show the parking.")
    ]
    assert {c["key"]: sorted(c["finding_ids"]) for c in body["referral_categories"]} == {
        "town_planner": sorted([big_finding["id"], land_finding["id"]]),
        "geotechnical_engineer": [land_finding["id"]],
    }
    assert body["limitations"] == ["Does not check overlays.", "Answers are not verified."]
    [scope] = [s for s in body["rule_sets"] if s["rule_set_id"] == rs["id"]]
    assert scope["limitations"] == body["limitations"]

    tasks = (await customer.get(f"{org}/projects/{project['id']}/tasks")).json()
    rule_tasks = {t["title"]: t for t in tasks if t["source"] == "RULE"}
    assert set(rule_tasks) == {"Book a pre-lodgement meeting", "Check the overlay map"}
    assert rule_tasks["Book a pre-lodgement meeting"]["finding_id"] == big_finding["id"]
    assert rule_tasks["Book a pre-lodgement meeting"]["notes"] == (
        "A development application is likely"
    )

    # Re-running doesn't duplicate open tasks; a task the customer finished comes back
    # only if a later assessment still calls for it.
    second = (await run(customer, project["id"])).json()
    tasks = (await customer.get(f"{org}/projects/{project['id']}/tasks")).json()
    assert len([t for t in tasks if t["source"] == "RULE"]) == 2
    assert len(second["approval_requirements"]) == 2  # requirements belong to each run
    done = rule_tasks["Check the overlay map"]["id"]
    r = await customer.patch(
        f"{org}/projects/{project['id']}/tasks/{done}", json={"status": "DONE"}
    )
    assert r.status_code == 200
    await run(customer, project["id"])
    tasks = (await customer.get(f"{org}/projects/{project['id']}/tasks")).json()
    overlay_tasks = [t for t in tasks if t["title"] == "Check the overlay map"]
    assert sorted(t["status"] for t in overlay_tasks) == ["DONE", "OPEN"]

    # The earlier assessment still reads exactly the same.
    assert (await customer.get(f"{org}/assessments/{body['id']}")).json() == body


async def test_requirements_are_tenant_isolated_and_append_only(api: ApiHarness) -> None:
    staff = await platform_user(api, "STAFF")
    admin = await platform_user(api, "ADMIN")
    lot = unique("LOT")
    rs = await rule_set(staff, vertical="PLANNING", applies_when=scoped(lot))
    ref = await reference(staff)
    body = content(FLOOR_OVER_80, [ref["id"]])
    body["outcomes"][0]["payload"] = APPROVAL_PAYLOAD
    await _publish(admin, rs["id"], FLOOR_OVER_80, body)

    alice, bob = await api.user(name="Alice"), await api.user(name="Bob")
    project = await submitted(alice, lot)
    assert (await run(alice, project["id"])).status_code == 201

    factory = api.app.state.resources.session_factory
    async with factory() as db:
        await bind_tenant(db, uuid.UUID(bob.personal_org_id))
        for table in ("approval_requirement", "evidence_requirement"):
            count = (await db.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()  # noqa: S608
            assert count == 0
    for statement in (
        "UPDATE approval_requirement SET certainty = 'REQUIRED'",
        "DELETE FROM approval_requirement",
        "UPDATE evidence_requirement SET title = 'x'",
        "DELETE FROM evidence_requirement",
    ):
        async with factory() as db:
            await bind_tenant(db, uuid.UUID(alice.personal_org_id))
            with pytest.raises(DBAPIError, match="permission denied"):
                await db.execute(text(statement))
            await db.rollback()
