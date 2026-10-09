"""BusinessReady (Milestone 8): marketplace categories, the approval map, the business
content pack, business profile prefill and the business approval map report.

BUSINESS rule sets created here are scoped to a business description unique to each test,
so other tests' rule sets are out of scope. The real pack's rules are only checked offline
and loaded inside a transaction that is rolled back.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import cli
from app.modules.assessments import approval_map
from app.modules.assessments.models import ApprovalRequirement
from app.modules.conditions import parse_condition, referenced_facts
from app.modules.marketplace import service as marketplace
from app.modules.marketplace.models import MarketplaceCategory
from app.modules.questionnaires.definition import load_bundled
from app.modules.regulatory.service import Actor
from app.modules.rules import engine, packs
from app.modules.rules.payload import Certainty, parse_payload, validate_payload
from app.modules.tenancy.models import Organisation
from tests.harness import ApiHarness, User, platform_user
from tests.regulatory_helpers import ADMIN, content, reference, rule_set, unique

PACK = "business_qld_cairns"
ADDRESS = {"line1": "1 Esplanade", "suburb": "Cairns", "state": "QLD", "postcode": "4870"}


# --- Approval map (pure) ---------------------------------------------------------------


def _approval(ordinal: int, kind: str, certainty: Certainty, title: str = "") -> Any:
    return ApprovalRequirement(
        id=uuid.uuid4(),
        finding_id=uuid.uuid4(),
        ordinal=ordinal,
        kind=kind,
        title=title or kind.title(),
        authority=None,
        pathway=None,
        certainty=certainty,
        confidence="LIKELY",
    )


def test_approval_map_shows_each_kind_once_at_its_strongest_certainty() -> None:
    gst_none = _approval(1, "GST", Certainty.NOT_IDENTIFIED)
    liquor = _approval(2, "LIQUOR", Certainty.MAY_APPLY)
    food = _approval(3, "FOOD", Certainty.REQUIRED, "Food business licence")
    gst_required = _approval(4, "GST", Certainty.REQUIRED, "Register for GST")
    liquor_again = _approval(5, "LIQUOR", Certainty.NOT_IDENTIFIED)

    entries = approval_map.build([liquor_again, food, gst_none, liquor, gst_required])
    assert [(e.kind, e.certainty) for e in entries] == [
        ("GST", Certainty.REQUIRED),  # seen first, so it leads its column
        ("FOOD", Certainty.REQUIRED),
        ("LIQUOR", Certainty.MAY_APPLY),
    ]
    gst = entries[0]
    assert gst.title == "Register for GST"
    assert gst.finding_ids == [gst_none.finding_id, gst_required.finding_id]
    assert entries[2].requirement_ids == [liquor.id, liquor_again.id]
    assert approval_map.build([]) == []


# --- Marketplace categories ------------------------------------------------------------


def test_category_file_is_valid_and_covers_every_pack() -> None:
    keys = {c.key for c in marketplace.load_bundled()}
    for name in packs.available():
        for rs in packs.load_file(name).rule_sets:
            for rule in rs.rules:
                for outcome in rule.outcomes:
                    used = set(parse_payload(outcome.payload).referral_categories)
                    assert used <= keys, f"{name} {rs.key}.{rule.key}: {used - keys}"


def test_category_file_rejects_duplicates(tmp_path: Any) -> None:
    entry = {
        "key": "town_planner",
        "label": "Town planner",
        "description": "Plans.",
        "verticals": ["PLANNING"],
        "requires_credential": False,
        "restricted": False,
    }
    path = tmp_path / "categories.json"
    path.write_text(json.dumps({"notes": "x", "categories": [entry, entry]}))
    with pytest.raises(ValueError, match="once"):
        marketplace.load_bundled(path)


@pytest.mark.integration
async def test_categories_are_listed_for_signed_in_users(api: ApiHarness) -> None:
    assert (await api.client.get("/v1/marketplace/categories")).status_code == 401
    user = await api.user()
    r = await user.get("/v1/marketplace/categories")
    assert r.status_code == 200
    listed = r.json()
    assert [c["key"] for c in listed] == [c.key for c in marketplace.load_bundled()]
    accountant = next(c for c in listed if c["key"] == "accountant")
    assert accountant["label"] == "Accountant or registered tax agent"
    business = (await user.get("/v1/marketplace/categories?vertical=BUSINESS")).json()
    assert "food_safety_consultant" in {c["key"] for c in business}
    assert "marine_surveyor" not in {c["key"] for c in business}


@pytest.mark.integration
async def test_sync_updates_in_place_and_deactivates_removed_entries(
    owner_sessions: async_sessionmaker[AsyncSession],
) -> None:
    bundled = marketplace.load_bundled()
    async with owner_sessions() as db:
        unchanged = await marketplace.sync(db, bundled)
        assert unchanged.lines() == ["marketplace categories unchanged"]
        renamed = [bundled[0].model_copy(update={"label": "Planner"}), *bundled[2:]]
        report = await marketplace.sync(db, renamed)
        assert report.updated[0] == bundled[0].key
        assert report.deactivated == [bundled[1].key]
        row = (
            await db.execute(
                select(MarketplaceCategory).where(MarketplaceCategory.key == bundled[1].key)
            )
        ).scalar_one()
        assert row.active is False  # kept, so old findings keep their label
        assert await marketplace.unknown_keys(db, [bundled[1].key, "nope"]) == [
            bundled[1].key,
            "nope",
        ]
        await db.rollback()


@pytest.mark.integration
async def test_rules_may_only_name_marketplace_categories(api: ApiHarness) -> None:
    staff = await platform_user(api, "STAFF")
    rs = await rule_set(staff, vertical="BUSINESS", applies_when=_scope(unique("biz")))
    ref = await reference(staff)
    condition = {"fact": "business.sells_alcohol", "op": "equals", "value": True}
    r = await staff.post(
        f"{ADMIN}/rule-sets/{rs['id']}/rules",
        json={"key": unique("rule"), "title": "Referral", "condition": condition},
    )
    version_id = r.json()["versions"][0]["id"]
    body = content(condition, [ref["id"]])
    body["outcomes"][0]["payload"] = {"referral_categories": ["astrologer"]}
    r = await staff.put(f"{ADMIN}/rule-versions/{version_id}", json=body)
    assert r.status_code == 422
    assert "astrologer" in r.json()["detail"]["fields"]["outcomes.0.payload"]
    body["outcomes"][0]["payload"] = {"referral_categories": ["liquor_licensing_consultant"]}
    r = await staff.put(f"{ADMIN}/rule-versions/{version_id}", json=body)
    assert r.status_code == 200, r.text
    checks = (await staff.get(f"{ADMIN}/rule-versions/{version_id}/checks")).json()
    gate = {c["key"]: c["passed"] for c in checks["checks"]}
    assert gate["referral_categories"] is True


# --- The business content pack ---------------------------------------------------------


def test_pack_rules_pass_their_own_test_cases() -> None:
    pack = packs.load_file(PACK)
    assert len(pack.rule_sets) == 8
    for rs in pack.rule_sets:
        assert rs.vertical == "BUSINESS"
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


def test_pack_only_reads_facts_the_business_questionnaire_collects() -> None:
    business = next(d for d in load_bundled() if d.key == "business.general")
    collected = {q.key for q in business.questions()}
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


def test_pack_fills_every_column_of_the_approval_map() -> None:
    """Between them, the outcomes can say required, likely, may apply and not identified."""
    pack = packs.load_file(PACK)
    seen: set[str] = set()
    from app.modules.rules.payload import certainty_for

    for rs in pack.rule_sets:
        for rule in rs.rules:
            for o in rule.outcomes:
                spec = parse_payload(o.payload).approval
                if spec is not None:
                    seen.add(certainty_for(o.outcome_type, spec))
    assert seen >= {"REQUIRED", "MAY_APPLY", "NOT_IDENTIFIED"}


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


# --- Assessments, the map and the report ------------------------------------------------


def _scope(description: str) -> dict[str, Any]:
    return {"fact": "business.description", "op": "equals", "value": description}


def _org(user: User) -> str:
    return f"/v1/organisations/{user.personal_org_id}"


async def _business_project(user: User, description: str, **answers: Any) -> dict[str, Any]:
    org = _org(user)
    r = await user.post(f"{org}/projects", json={"vertical": "BUSINESS", "title": "Reef Cafe"})
    assert r.status_code == 201, r.text
    project = r.json()
    submission = (await user.post(f"{org}/projects/{project['id']}/submissions", json={})).json()
    values = {
        "business.activity": "food_service",
        "business.description": description,
        "business.has_abn": False,
        "business.entity_type": "SOLE_TRADER",
        "business.state": "QLD",
        "business.lga": "cairns",
        "business.premises_type": "leased_commercial",
        "business.premises_address": ADDRESS,
        "business.handles_food": True,
        "business.food_activities": ["prepare_on_site"],
        "business.sells_alcohol": True,
        **answers,
    }
    r = await user.put(
        f"{org}/submissions/{submission['id']}/answers",
        json={"answers": {k: v for k, v in values.items() if v is not None}},
    )
    assert r.status_code == 200, r.text
    r = await user.post(f"{org}/submissions/{submission['id']}/submit")
    assert r.status_code == 200, r.text
    return dict(project)


async def _publish(
    admin: User, rule_set_id: str, condition: dict[str, Any], outcomes: list[Any], ref_id: str
) -> None:
    r = await admin.post(
        f"{ADMIN}/rule-sets/{rule_set_id}/rules",
        json={"key": unique("rule"), "title": "Business rule", "condition": condition},
    )
    assert r.status_code == 201, r.text
    version_id = r.json()["versions"][0]["id"]
    r = await admin.put(
        f"{ADMIN}/rule-versions/{version_id}",
        json=content(condition, [ref_id], outcomes=outcomes),
    )
    assert r.status_code == 200, r.text
    r = await admin.post(f"{ADMIN}/rule-versions/{version_id}/publish")
    assert r.status_code == 200, r.text


def _outcome(on: str, typ: str, title: str, kind: str, **extra: Any) -> dict[str, Any]:
    return {
        "on_result": on,
        "outcome_type": typ,
        "title": title,
        "payload": {"approval": {"kind": kind, "authority": "Test Office"}, **extra},
    }


@pytest.mark.integration
async def test_business_assessment_builds_the_map_and_the_report(api: ApiHarness) -> None:
    staff = await platform_user(api, "STAFF")
    admin = await platform_user(api, "ADMIN")
    description = unique("Test cafe on the esplanade")
    rs = await rule_set(staff, vertical="BUSINESS", applies_when=_scope(description))
    ref = await reference(staff)
    alcohol = {"fact": "business.sells_alcohol", "op": "equals", "value": True}
    footpath = {"fact": "business.footpath_use", "op": "equals", "value": True}
    staff_band = {"fact": "business.employee_band", "op": "not_equals", "value": "NONE"}
    await _publish(
        admin,
        rs["id"],
        alcohol,
        [
            _outcome(
                "MATCH",
                "APPROVAL_REQUIRED",
                "Liquor licence needed",
                "LIQUOR_LICENCE",
                referral_categories=["liquor_licensing_consultant", "lawyer"],
            ),
            _outcome("NO_MATCH", "NOT_REQUIRED", "No liquor licence", "LIQUOR_LICENCE"),
        ],
        ref["id"],
    )
    await _publish(
        admin,
        rs["id"],
        footpath,
        [
            _outcome("MATCH", "APPROVAL_REQUIRED", "Footpath permit needed", "FOOTPATH_PERMIT"),
            _outcome("NO_MATCH", "NOT_REQUIRED", "No footpath permit", "FOOTPATH_PERMIT"),
        ],
        ref["id"],
    )
    await _publish(
        admin,
        rs["id"],
        staff_band,
        [
            _outcome("MATCH", "APPROVAL_REQUIRED", "Workers' compensation", "WORKERS_COMP"),
            _outcome(
                "UNKNOWN",
                "APPROVAL_LIKELY",
                "Workers' compensation may apply",
                "WORKERS_COMP",
            ),
        ],
        ref["id"],
    )

    customer = await api.user()
    project = await _business_project(customer, description, **{"business.footpath_use": False})
    r = await customer.post(f"{_org(customer)}/projects/{project['id']}/assessments")
    assert r.status_code == 201, r.text
    body = r.json()
    ours = {f["id"] for f in body["finding_list"] if f["rule_set_id"] == rs["id"]}
    entries = [e for e in body["approval_map"] if set(e["finding_ids"]) <= ours]
    assert [(e["kind"], e["certainty"]) for e in entries] == [
        ("LIQUOR_LICENCE", "REQUIRED"),
        ("WORKERS_COMP", "LIKELY_REQUIRED"),  # employees not answered: unknown outcome
        ("FOOTPATH_PERMIT", "NOT_IDENTIFIED"),
    ]
    referrals = {c["key"]: c for c in body["referral_categories"]}
    assert referrals["liquor_licensing_consultant"]["label"] == "Liquor licensing consultant"
    assert referrals["lawyer"]["description"]

    r = await customer.post(
        f"{_org(customer)}/assessments/{body['id']}/documents", json={"format": "HTML"}
    )
    assert r.status_code == 202, r.text
    html = (
        await customer.get(f"{_org(customer)}/generated-documents/{r.json()['id']}/content")
    ).content.decode()
    for expected in (
        "Business approval map",
        "Your approval map",
        "Required",
        "Likely required",
        "May apply",
        "Not identified",
        "Liquor licence needed",
        "Liquor licensing consultant",
        "Assumptions",
        "Limitations",
    ):
        assert expected in html, expected
    for fmt, magic in (("PDF", b"%PDF"), ("DOCX", b"PK")):
        r = await customer.post(
            f"{_org(customer)}/assessments/{body['id']}/documents", json={"format": fmt}
        )
        assert r.json()["status"] == "READY", r.text
        content = await customer.get(
            f"{_org(customer)}/generated-documents/{r.json()['id']}/content"
        )
        assert content.content.startswith(magic)


@pytest.mark.integration
async def test_business_profile_prefills_the_questionnaire(api: ApiHarness) -> None:
    user = await api.user()
    org = _org(user)
    r = await user.post(
        f"{org}/business-profiles",
        json={
            "legal_name": "Reef Cafe Pty Ltd",
            "entity_type": "COMPANY",
            "abn": "51 824 753 556",
            "employee_band": "1_4",
            "turnover_band": "75K_2M",
            "address": ADDRESS,
        },
    )
    assert r.status_code == 201, r.text
    r = await user.post(
        f"{org}/projects",
        json={"vertical": "BUSINESS", "title": "Cafe", "business_profile_id": r.json()["id"]},
    )
    assert r.status_code == 201, r.text
    project = r.json()
    submission = (await user.post(f"{org}/projects/{project['id']}/submissions", json={})).json()
    r = await user.get(f"{org}/submissions/{submission['id']}/prefill")
    assert r.status_code == 200, r.text
    found = {s["key"]: s for s in r.json()["suggestions"]}
    assert found["business.abn"]["value"] == "51824753556"
    assert found["business.has_abn"]["value"] is True
    assert found["business.entity_type"]["value"] == "COMPANY"
    assert found["business.employee_band"]["value"] == "1_4"
    assert found["business.turnover_band"]["value"] == "75K_2M"
    assert found["business.state"]["value"] == "QLD"
    assert found["business.premises_address"]["value"] == ADDRESS
    assert {s["source"] for s in found.values()} == {"Your business details"}
