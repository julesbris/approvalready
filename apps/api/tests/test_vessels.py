"""VesselReady (Milestone 9): the vessel content pack, checklists, vessel certificates, the
safety management system builder, vessel prefill and the vessel reports.

VESSEL rule sets created here are scoped to a vessel name unique to each test, so other
tests' rule sets are out of scope. The real pack's rules are only checked offline and loaded
inside a transaction that is rolled back.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app import cli
from app.modules.checklists import definition as checklist_definitions
from app.modules.conditions import parse_condition, referenced_facts
from app.modules.marketplace import service as marketplace
from app.modules.questionnaires.definition import load_bundled
from app.modules.regulatory.service import Actor
from app.modules.rules import engine, packs
from app.modules.rules.payload import parse_payload, validate_payload
from app.modules.tenancy.models import Organisation
from app.modules.vessels import sms
from tests.harness import ApiHarness, User, platform_user
from tests.regulatory_helpers import ADMIN, content, reference, rule_set, unique

PACK = "vessel_au_qld"


def _org(user: User) -> str:
    return f"/v1/organisations/{user.personal_org_id}"


def _scope(name: str) -> dict[str, Any]:
    return {"fact": "vessel.name", "op": "equals", "value": name}


# --- The vessel content pack -----------------------------------------------------------


def test_pack_rules_pass_their_own_test_cases() -> None:
    pack = packs.load_file(PACK)
    assert len(pack.rule_sets) == 2
    for rs in pack.rule_sets:
        assert rs.vertical == "VESSEL"
        assert rs.limitations, f"{rs.key} must say what it doesn't check"
        if rs.applies_when is not None:
            parse_condition(rs.applies_when)
        for rule in rs.rules:
            condition = parse_condition(rule.condition)
            for outcome in rule.outcomes:
                validate_payload(outcome.outcome_type, outcome.payload)
            assert rule.test_cases
            for case in rule.test_cases:
                result = engine.run_test_case(
                    condition, case.name, case.facts, case.expected_result
                )
                assert result.passed, f"{rs.key}.{rule.key}: {case.name} gave {result.actual}"


def test_pack_only_reads_facts_the_vessel_questionnaire_collects() -> None:
    vessel = next(d for d in load_bundled() if d.key == "vessel.general")
    collected = {q.key for q in vessel.questions()}
    for rs in packs.load_file(PACK).rule_sets:
        for condition in [rs.applies_when, *(r.condition for r in rs.rules)]:
            if condition is None:
                continue
            for leaf in referenced_facts(parse_condition(condition)):
                assert leaf.fact in collected, f"{rs.key}: {leaf.fact} is never asked"


def test_pack_marks_every_extract_as_a_summary() -> None:
    for ref in packs.load_file(PACK).references:
        assert ref.extracted_text.startswith("[Summary, not the source's wording]")
        assert ref.interpretation and "verify" in ref.interpretation


def test_pack_names_only_real_checklists_and_categories() -> None:
    categories = {c.key for c in marketplace.load_bundled()}
    named: set[str] = set()
    for rs in packs.load_file(PACK).rule_sets:
        for rule in rs.rules:
            for o in rule.outcomes:
                payload = parse_payload(o.payload)
                assert set(payload.referral_categories) <= categories
                assert checklist_definitions.unknown_keys(payload.checklists) == []
                named |= set(payload.checklists)
    vessel_checklists = {d.key for d in checklist_definitions.for_vertical("VESSEL")}
    assert named == vessel_checklists, "every vessel checklist is reachable from a rule"


@pytest.mark.integration
async def test_pack_loads_and_publishes_then_rolls_back(api: ApiHarness) -> None:
    admin = await platform_user(api, "ADMIN")
    pack = packs.load_file(PACK)
    suffix = uuid.uuid4().hex[:8]
    for rs in pack.rule_sets:
        rs.key = f"{rs.key}_{suffix}"
    factory = api.app.state.resources.session_factory
    async with factory() as db:
        org = (
            await db.execute(select(Organisation).where(Organisation.kind == "PLATFORM_ADMIN"))
        ).scalar_one()
        report = await packs.load(
            db, pack, Actor(uuid.UUID(admin.id), org.id, cli.CLI_META), publish=True
        )
        assert report.not_published == [], report.lines()
        assert len(report.published) == sum(len(rs.rules) for rs in pack.rule_sets)
        await db.rollback()


# --- Checklist definitions and the SMS structure ----------------------------------------


def test_checklist_definitions_are_valid_and_cite_sources() -> None:
    found = checklist_definitions.bundled()
    assert set(found) >= {
        "vessel.initial_survey",
        "vessel.non_survey_approval",
        "vessel.certificate_of_operation",
        "vessel.uvi",
        "vessel.qld_registration",
    }
    for d in found.values():
        assert d.sources and d.items
        assert len(d.content_hash()) == 32


def test_checklist_file_name_must_match_its_key(tmp_path: Any) -> None:
    path = tmp_path / "vessel.other.json"
    path.write_text(
        '{"key": "vessel.uvi", "vertical": "VESSEL", "title": "T", "description": "D",'
        ' "sources": [{"title": "S", "organisation": "O", "url": "https://example.com"}],'
        ' "items": [{"key": "one", "title": "One"}]}'
    )
    with pytest.raises(ValueError, match="file name"):
        checklist_definitions.load_file(path)


def test_sms_structure_follows_marine_order_504() -> None:
    structure = sms.structure()
    elements = structure.elements
    assert len(elements) >= 16
    for key in ("risk_assessment", "designated_person", "emergency_plan", "drug_alcohol_policy"):
        assert elements[key].required
    assert not elements["crewing_determination"].required
    assert any("504" in s.title for s in structure.sources)
    with pytest.raises(ValueError, match="not part"):
        sms.clean_content({"horoscope": "x"})
    with pytest.raises(ValueError, match="under"):
        sms.clean_content({"risk_assessment": "x" * (sms.MAX_ELEMENT_CHARS + 1)})
    assert sms.clean_content({"risk_assessment": "  "}) == {"risk_assessment": None}


# --- Helpers ---------------------------------------------------------------------------


async def _vessel(user: User, **overrides: Any) -> dict[str, Any]:
    body = {
        "name": "Reef Runner",
        "vessel_type": "MOTOR",
        "length_m": "11.5",
        "propulsion": "OUTBOARD",
        "max_passengers": 4,
        "crew": 1,
        "operating_area": "Trinity Inlet",
        **overrides,
    }
    r = await user.post(f"{_org(user)}/vessels", json=body)
    assert r.status_code == 201, r.text
    return dict(r.json())


async def _project(user: User, vertical: str = "VESSEL", **fields: Any) -> dict[str, Any]:
    r = await user.post(
        f"{_org(user)}/projects", json={"vertical": vertical, "title": "Charter", **fields}
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


async def _submitted(user: User, project: dict[str, Any], **answers: Any) -> None:
    org = _org(user)
    submission = (await user.post(f"{org}/projects/{project['id']}/submissions", json={})).json()
    values = {
        "vessel.name": "Reef Runner",
        "vessel.type": "motor",
        "vessel.length_m": "11.5",
        "vessel.has_uvi": False,
        "vessel.commercial_use": True,
        "vessel.commercial_activities": ["passenger_tours"],
        "vessel.max_passengers": 20,
        "vessel.operating_area_description": "Out to the reef",
        "vessel.operating_area": "within_30nm",
        "vessel.home_state": "QLD",
        "vessel.is_new_build": True,
        **answers,
    }
    r = await user.put(f"{org}/submissions/{submission['id']}/answers", json={"answers": values})
    assert r.status_code == 200, r.text
    r = await user.post(f"{org}/submissions/{submission['id']}/submit")
    assert r.status_code == 200, r.text


async def _publish(admin: User, rule_set_id: str, condition: dict[str, Any], outcomes: Any) -> None:
    ref = await reference(admin)
    r = await admin.post(
        f"{ADMIN}/rule-sets/{rule_set_id}/rules",
        json={"key": unique("rule"), "title": "Vessel rule", "condition": condition},
    )
    assert r.status_code == 201, r.text
    version_id = r.json()["versions"][0]["id"]
    r = await admin.put(
        f"{ADMIN}/rule-versions/{version_id}",
        json=content(condition, [ref["id"]], outcomes=outcomes),
    )
    assert r.status_code == 200, r.text
    r = await admin.post(f"{ADMIN}/rule-versions/{version_id}/publish")
    assert r.status_code == 200, r.text


# --- Rules name checklists --------------------------------------------------------------


@pytest.mark.integration
async def test_rules_may_only_name_reviewed_checklists(api: ApiHarness) -> None:
    staff = await platform_user(api, "STAFF")
    rs = await rule_set(staff, vertical="VESSEL", applies_when=_scope(unique("boat")))
    ref = await reference(staff)
    condition = {"fact": "vessel.has_uvi", "op": "equals", "value": False}
    r = await staff.post(
        f"{ADMIN}/rule-sets/{rs['id']}/rules",
        json={"key": unique("rule"), "title": "Checklist", "condition": condition},
    )
    version_id = r.json()["versions"][0]["id"]
    body = content(condition, [ref["id"]])
    body["outcomes"][0]["payload"] = {"checklists": ["vessel.horoscope"]}
    r = await staff.put(f"{ADMIN}/rule-versions/{version_id}", json=body)
    assert r.status_code == 422
    assert "vessel.horoscope" in r.json()["detail"]["fields"]["outcomes.0.payload"]
    body["outcomes"][0]["payload"] = {"checklists": ["vessel.uvi", "vessel.uvi"]}
    r = await staff.put(f"{ADMIN}/rule-versions/{version_id}", json=body)
    assert r.status_code == 422
    body["outcomes"][0]["payload"] = {"checklists": ["vessel.uvi"]}
    r = await staff.put(f"{ADMIN}/rule-versions/{version_id}", json=body)
    assert r.status_code == 200, r.text
    checks = (await staff.get(f"{ADMIN}/rule-versions/{version_id}/checks")).json()
    assert {c["key"]: c["passed"] for c in checks["checks"]}["checklists"] is True


@pytest.mark.integration
async def test_assessment_adds_named_checklists_once_and_reports_the_pathway(
    api: ApiHarness,
) -> None:
    admin = await platform_user(api, "ADMIN")
    name = unique("Reef Runner")
    rs = await rule_set(admin, vertical="VESSEL", applies_when=_scope(name))
    await _publish(
        admin,
        rs["id"],
        {"fact": "vessel.has_uvi", "op": "equals", "value": False},
        [
            {
                "on_result": "MATCH",
                "outcome_type": "APPROVAL_REQUIRED",
                "title": "Get a UVI",
                "payload": {
                    "approval": {"kind": "UNIQUE_VESSEL_IDENTIFIER", "authority": "AMSA"},
                    "checklists": ["vessel.uvi"],
                    "referral_categories": ["marine_safety_consultant"],
                },
            },
            {"on_result": "NO_MATCH", "outcome_type": "INFO", "title": "Has a UVI"},
        ],
    )
    user = await api.user()
    org = _org(user)
    project = await _project(user)
    await _submitted(user, project, **{"vessel.name": name})
    url = f"{org}/projects/{project['id']}"

    r = await user.post(f"{url}/assessments")
    assert r.status_code == 201, r.text
    assessment = r.json()
    assert [(e["kind"], e["certainty"]) for e in assessment["approval_map"]] == [
        ("UNIQUE_VESSEL_IDENTIFIER", "REQUIRED")
    ]
    lists = (await user.get(f"{url}/checklists")).json()
    assert [(c["key"], c["origin"], c["done"]) for c in lists] == [("vessel.uvi", "RULE", 0)]
    checklist = lists[0]
    assert checklist["finding_id"] in {f["id"] for f in assessment["finding_list"]}
    assert checklist["total"] == len(checklist_definitions.bundled()["vessel.uvi"].items)
    assert checklist["sources"][0]["url"].startswith("https://www.amsa.gov.au/")

    # Tick an item; a re-run neither duplicates the list nor resets it.
    item = checklist["items"][0]
    r = await user.patch(f"{org}/checklist-items/{item['id']}", json={"status": "DONE"})
    assert r.status_code == 200, r.text
    assert r.json()["completed_at"] is not None
    r = await user.post(f"{url}/assessments")
    assert r.status_code == 201, r.text
    lists = (await user.get(f"{url}/checklists")).json()
    assert len(lists) == 1 and lists[0]["done"] == 1

    # A checklist from the assessment can't be removed; a required item needs a reason to skip.
    assert (await user.delete(f"{org}/checklists/{checklist['id']}")).status_code == 409
    required = next(i for i in checklist["items"][1:] if i["required"])
    r = await user.patch(
        f"{org}/checklist-items/{required['id']}", json={"status": "NOT_APPLICABLE"}
    )
    assert r.status_code == 422
    r = await user.patch(
        f"{org}/checklist-items/{required['id']}",
        json={"status": "NOT_APPLICABLE", "note": "Vessel is on the Shipping Register"},
    )
    assert r.status_code == 200, r.text
    r = await user.patch(f"{org}/checklist-items/{required['id']}", json={"status": "OPEN"})
    assert r.json()["completed_at"] is None

    # The pathway report is the vessel default and lists the checklist.
    r = await user.post(f"{org}/assessments/{assessment['id']}/documents", json={"format": "HTML"})
    assert r.status_code == 202, r.text
    assert r.json()["template_key"] == "VESSEL_PATHWAY"
    html = (await user.get(f"{org}/generated-documents/{r.json()['id']}/content")).text
    for expected in (
        "Vessel approvals pathway",
        "Your approvals pathway",
        "Get a UVI",
        "Unique Vessel Identifier (UVI) (1 of",
        "Marine safety consultant",
        "Assumptions",
    ):
        assert expected in html, expected

    # Another organisation can't see or touch any of it.
    other = await api.user()
    r = await other.get(f"{_org(other)}/projects/{project['id']}/checklists")
    assert r.status_code == 404
    r = await other.patch(f"{_org(other)}/checklist-items/{item['id']}", json={"status": "OPEN"})
    assert r.status_code == 404


@pytest.mark.integration
async def test_customer_adds_and_removes_checklists(api: ApiHarness) -> None:
    user = await api.user()
    org = _org(user)
    project = await _project(user)
    url = f"{org}/projects/{project['id']}/checklists"
    defs = (await user.get("/v1/checklists?vertical=VESSEL")).json()
    assert {d["key"] for d in defs} >= {"vessel.initial_survey", "vessel.qld_registration"}

    r = await user.post(url, json={"key": "vessel.initial_survey"})
    assert r.status_code == 201, r.text
    added = r.json()
    assert added["origin"] == "USER" and added["finding_id"] is None
    again = await user.post(url, json={"key": "vessel.initial_survey"})
    assert again.json()["id"] == added["id"]
    assert (await user.post(url, json={"key": "vessel.nope"})).status_code == 422

    business = await _project(user, vertical="BUSINESS")
    r = await user.post(
        f"{org}/projects/{business['id']}/checklists", json={"key": "vessel.initial_survey"}
    )
    assert r.status_code == 422, "vessel checklists belong to vessel projects"

    assert (await user.delete(f"{org}/checklists/{added['id']}")).status_code == 204
    assert (await user.get(url)).json() == []


# --- Vessel certificates ---------------------------------------------------------------


@pytest.mark.integration
async def test_vessel_certificates(api: ApiHarness) -> None:
    user = await api.user()
    org = _org(user)
    vessel = await _vessel(user)
    url = f"{org}/vessels/{vessel['id']}/certificates"
    today = date.today()
    r = await user.post(
        url,
        json={
            "kind": "CERTIFICATE_OF_SURVEY",
            "number": "CoS 12345",
            "issuer": "AMSA",
            "issued_on": str(today - timedelta(days=5 * 365 - 30)),
            "expires_on": str(today + timedelta(days=30)),
        },
    )
    assert r.status_code == 201, r.text
    survey = r.json()
    assert survey["state"] == "EXPIRING"
    r = await user.post(url, json={"kind": "STATE_REGISTRATION"})
    assert r.json()["state"] == "NO_EXPIRY"
    r = await user.post(
        url,
        json={
            "kind": "CERTIFICATE_OF_OPERATION",
            "issued_on": str(today),
            "expires_on": str(today - timedelta(days=1)),
        },
    )
    assert r.status_code == 422
    r = await user.post(url, json={"kind": "EXEMPTION", "uploaded_document_id": str(uuid.uuid4())})
    assert r.status_code == 404

    r = await user.patch(
        f"{org}/vessel-certificates/{survey['id']}",
        json={"expires_on": str(today - timedelta(days=1))},
    )
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "EXPIRED"
    listed = (await user.get(url)).json()
    assert [c["kind"] for c in listed] == ["CERTIFICATE_OF_SURVEY", "STATE_REGISTRATION"]

    other = await api.user()
    assert (
        await other.get(f"{_org(other)}/vessels/{vessel['id']}/certificates")
    ).status_code == 404
    assert (
        await other.delete(f"{_org(other)}/vessel-certificates/{survey['id']}")
    ).status_code == 404
    assert (await user.delete(f"{org}/vessel-certificates/{survey['id']}")).status_code == 204
    assert len((await user.get(url)).json()) == 1


# --- Safety management system builder ---------------------------------------------------


@pytest.mark.integration
async def test_sms_builder_saves_parts_and_makes_a_document(api: ApiHarness) -> None:
    admin = await platform_user(api, "ADMIN")
    name = unique("Reef Runner")
    rs = await rule_set(admin, vertical="VESSEL", applies_when=_scope(name))
    await _publish(
        admin,
        rs["id"],
        {"fact": "vessel.commercial_use", "op": "equals", "value": True},
        [{"on_result": "MATCH", "outcome_type": "APPROVAL_REQUIRED", "title": "Write an SMS"}],
    )
    user = await api.user()
    org = _org(user)
    vessel = await _vessel(user, name="Reef Runner", uvi="ABC123")
    project = await _project(user, vessel_id=vessel["id"])
    url = f"{org}/projects/{project['id']}/sms"

    empty = (await user.get(url)).json()
    assert empty["written"] == 0 and empty["saved_at"] is None
    elements = {e["key"]: e for s in empty["sections"] for e in s["elements"]}
    suggestion = elements["vessel_details"]["suggestion"]
    assert "Reef Runner is a motor vessel of 11.5 metres" in suggestion
    assert "ABC123" in elements["vessel_details"]["suggestion"]
    assert elements["risk_assessment"]["suggestion"] is None

    r = await user.put(
        url,
        json={
            "content": {
                "vessel_details": "Reef Runner, 11.5 m charter boat.",
                "risk_assessment": "Main risks: weather.\n\nControls: check the forecast.",
            }
        },
    )
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["written"] == 2 and saved["required"] == empty["required"]
    assert saved["outdated_structure"] is False
    r = await user.put(url, json={"content": {"vessel_details": None}})
    elements = {e["key"]: e for s in r.json()["sections"] for e in s["elements"]}
    assert elements["vessel_details"]["text"] is None
    assert elements["vessel_details"]["suggestion"], "offered again once empty"
    assert elements["risk_assessment"]["text"].startswith("Main risks")
    assert (await user.put(url, json={"content": {"horoscope": "x"}})).status_code == 422

    # Only vessel projects have one; outsiders get nothing.
    business = await _project(user, vertical="BUSINESS")
    assert (await user.get(f"{org}/projects/{business['id']}/sms")).status_code == 409
    other = await api.user()
    assert (await other.get(f"{_org(other)}/projects/{project['id']}/sms")).status_code == 404

    # The SMS document comes from the latest assessment and shows what is still missing.
    await _submitted(user, project, **{"vessel.name": name})
    assessment = (await user.post(f"{org}/projects/{project['id']}/assessments")).json()
    r = await user.post(
        f"{org}/assessments/{assessment['id']}/documents",
        json={"format": "HTML", "template": "SMS"},
    )
    assert r.status_code == 202, r.text
    generated = r.json()
    assert generated["template_key"] == "SMS"
    assert "safety-management-system" in generated["filename"]
    html = (await user.get(f"{org}/generated-documents/{generated['id']}/content")).text
    for expected in (
        "Safety management system (draft)",
        "Draft written by the operator.",
        "Main risks: weather.",
        "<p>Controls: check the forecast.</p>",
        "Designated person",
        "Not written yet (required).",
        "Marine Order 504",
    ):
        assert expected in html, expected
    r = await user.post(
        f"{org}/assessments/{assessment['id']}/documents",
        json={"format": "PDF", "template": "BUSINESS_APPROVAL_MAP"},
    )
    assert r.status_code == 409


@pytest.mark.integration
async def test_sms_document_needs_some_text(api: ApiHarness) -> None:
    admin = await platform_user(api, "ADMIN")
    name = unique("Empty SMS")
    rs = await rule_set(admin, vertical="VESSEL", applies_when=_scope(name))
    await _publish(
        admin,
        rs["id"],
        {"fact": "vessel.commercial_use", "op": "equals", "value": True},
        [{"on_result": "MATCH", "outcome_type": "INFO", "title": "Commercial"}],
    )
    user = await api.user()
    project = await _project(user)
    await _submitted(user, project, **{"vessel.name": name})
    org = _org(user)
    assessment = (await user.post(f"{org}/projects/{project['id']}/assessments")).json()
    r = await user.post(
        f"{org}/assessments/{assessment['id']}/documents",
        json={"format": "HTML", "template": "SMS"},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "sms_empty"


# --- Prefill ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_vessel_prefills_the_questionnaire(api: ApiHarness) -> None:
    user = await api.user()
    org = _org(user)
    vessel = await _vessel(user, uvi="ABC123", propulsion="INBOARD")
    project = await _project(user, vessel_id=vessel["id"])
    submission = (await user.post(f"{org}/projects/{project['id']}/submissions", json={})).json()
    r = await user.get(f"{org}/submissions/{submission['id']}/prefill")
    assert r.status_code == 200, r.text
    found = {s["key"]: s["value"] for s in r.json()["suggestions"]}
    assert found["vessel.name"] == "Reef Runner"
    assert found["vessel.type"] == "motor"
    assert found["vessel.length_m"] == "11.5"
    assert found["vessel.propulsion"] == "inboard"
    assert found["vessel.has_uvi"] is True
    assert found["vessel.uvi"] == "ABC123"
    assert {s["source"] for s in r.json()["suggestions"]} == {"Your vessel details"}
