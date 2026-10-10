"""TradeReady (Milestone 25): importing and exporting goods. The trade questionnaire, the
trade_au content pack, the trade marketplace categories (customs brokers, freight
forwarders, logistics providers), business profile prefill, the approval map and report,
and introductions to import and logistics companies.

TRADE rule sets created here are scoped to a goods description unique to each test, so other
tests' rule sets are out of scope. The real pack's rules are only checked offline and loaded
inside a transaction that is rolled back.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app import cli
from app.modules.conditions import parse_condition, referenced_facts
from app.modules.marketplace import service as marketplace
from app.modules.projects.models import Vertical
from app.modules.questionnaires.definition import load_bundled
from app.modules.regulatory.service import Actor
from app.modules.rules import engine, packs
from app.modules.rules.payload import certainty_for, parse_payload, validate_payload
from app.modules.tenancy.models import Organisation
from tests.harness import ApiHarness, User, platform_user
from tests.regulatory_helpers import ADMIN, content, reference, rule_set, unique
from tests.test_leads import consent_body, referrals_url

PACK = "trade_au"
ADDRESS = {"line1": "10 Wharf Street", "suburb": "Cairns City", "state": "QLD", "postcode": "4870"}
TRADE_CATEGORIES = {
    "customs_broker",
    "freight_forwarder",
    "logistics_provider",
    "trade_compliance_consultant",
}


# --- Questionnaire and categories --------------------------------------------------------


def _questionnaire() -> Any:
    return next(d for d in load_bundled() if d.key == "trade.general")


def test_trade_questionnaire_is_its_own_vertical() -> None:
    trade = _questionnaire()
    assert trade.vertical == Vertical.TRADE
    keys = {q.key for q in trade.questions()}
    assert {"trade.direction", "trade.goods_categories", "trade.import_value_band"} <= keys
    assert all(k.startswith("trade.") for k in keys)


def test_import_and_logistics_companies_are_marketplace_categories() -> None:
    categories = {c.key: c for c in marketplace.load_bundled()}
    assert set(categories) >= TRADE_CATEGORIES
    for key in TRADE_CATEGORIES:
        assert Vertical.TRADE in categories[key].verticals
    assert categories["customs_broker"].requires_credential
    assert not categories["freight_forwarder"].restricted


# --- The trade content pack ------------------------------------------------------------


def test_pack_rules_pass_their_own_test_cases() -> None:
    pack = packs.load_file(PACK)
    assert len(pack.rule_sets) == 4
    for rs in pack.rule_sets:
        assert rs.vertical == "TRADE"
        assert rs.limitations, f"{rs.key} must say what it doesn't check"
        assert rs.applies_when is not None
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


def test_pack_only_reads_facts_the_trade_questionnaire_collects() -> None:
    collected = {q.key for q in _questionnaire().questions()}
    for rs in packs.load_file(PACK).rule_sets:
        for condition in [rs.applies_when, *(r.condition for r in rs.rules)]:
            if condition is None:
                continue
            for leaf in referenced_facts(parse_condition(condition)):
                assert leaf.fact in collected, f"{rs.key}: {leaf.fact} is never asked"


def test_pack_options_match_the_questionnaire() -> None:
    """Every value a rule compares a SELECT or MULTISELECT fact with is an option of it."""
    options = {
        q.key: {o.value for o in q.options} for q in _questionnaire().questions() if q.options
    }

    def check(node: dict[str, Any]) -> None:
        for child in node.get("all", []) + node.get("any", []):
            check(child)
        if node.get("fact") in options:
            values = node["value"] if isinstance(node["value"], list) else [node["value"]]
            assert set(values) <= options[node["fact"]], node

    for rs in packs.load_file(PACK).rule_sets:
        for condition in [rs.applies_when, *(r.condition for r in rs.rules)]:
            check(condition)


def test_pack_marks_every_extract_as_a_summary() -> None:
    for ref in packs.load_file(PACK).references:
        assert ref.extracted_text.startswith("[Summary, not the source's wording]")
        assert ref.interpretation and "verify" in ref.interpretation


def test_pack_refers_customers_to_import_and_logistics_companies() -> None:
    used: set[str] = set()
    seen: set[str] = set()
    for rs in packs.load_file(PACK).rule_sets:
        for rule in rs.rules:
            for o in rule.outcomes:
                payload = parse_payload(o.payload)
                used |= set(payload.referral_categories)
                if payload.approval is not None:
                    seen.add(certainty_for(o.outcome_type, payload.approval))
    assert {"customs_broker", "freight_forwarder", "logistics_provider"} <= used
    assert seen >= {"REQUIRED", "LIKELY_REQUIRED", "MAY_APPLY", "NOT_IDENTIFIED"}


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


# --- Projects, assessments, the map, the report and introductions ----------------------


def _org(user: User) -> str:
    return f"/v1/organisations/{user.personal_org_id}"


async def _profile(user: User) -> str:
    r = await user.post(
        f"{_org(user)}/business-profiles",
        json={
            "legal_name": "Reef Imports Pty Ltd",
            "entity_type": "COMPANY",
            "abn": "51 824 753 556",
            "gst_registered": True,
            "address": ADDRESS,
        },
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def _trade_project(user: User, description: str, **answers: Any) -> dict[str, Any]:
    org = _org(user)
    r = await user.post(
        f"{org}/projects",
        json={
            "vertical": "TRADE",
            "title": "Espresso machines",
            "business_profile_id": await _profile(user),
        },
    )
    assert r.status_code == 201, r.text
    project = dict(r.json())
    assert project["reference_code"].startswith("TRD-")
    submission = (await user.post(f"{org}/projects/{project['id']}/submissions", json={})).json()
    values = {
        "trade.direction": "import",
        "trade.goods_description": description,
        "trade.goods_categories": ["electrical", "machinery_metal"],
        "trade.import_value_band": "OVER_1000",
        "trade.import_transport": "sea_container",
        "trade.bmsb_risk_country": True,
        "trade.bmsb_season": False,
        "trade.lodge_self": False,
        "trade.household_electrical": True,
        "trade.has_abn": True,
        "trade.gst_registered": True,
        "trade.state": "QLD",
        **answers,
    }
    r = await user.put(
        f"{org}/submissions/{submission['id']}/answers",
        json={"answers": {k: v for k, v in values.items() if v is not None}},
    )
    assert r.status_code == 200, r.text
    r = await user.post(f"{org}/submissions/{submission['id']}/submit")
    assert r.status_code == 200, r.text
    return project


async def _publish(
    admin: User, rule_set_id: str, condition: dict[str, Any], outcomes: list[Any], ref_id: str
) -> None:
    r = await admin.post(
        f"{ADMIN}/rule-sets/{rule_set_id}/rules",
        json={"key": unique("rule"), "title": "Trade rule", "condition": condition},
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
        "payload": {"approval": {"kind": kind, "authority": "Test Border Office"}, **extra},
    }


@pytest.mark.integration
async def test_trade_assessment_maps_approvals_reports_and_refers_to_brokers(
    api: ApiHarness,
) -> None:
    staff = await platform_user(api, "STAFF")
    admin = await platform_user(api, "ADMIN")
    description = unique("Test espresso machines from Italy")
    rs = await rule_set(
        staff,
        vertical="TRADE",
        applies_when={"fact": "trade.goods_description", "op": "equals", "value": description},
    )
    ref = await reference(staff)
    over_1000 = {"fact": "trade.import_value_band", "op": "equals", "value": "OVER_1000"}
    await _publish(
        admin,
        rs["id"],
        over_1000,
        [
            _outcome(
                "MATCH",
                "APPROVAL_REQUIRED",
                "Full import declaration needed",
                "IMPORT_DECLARATION",
                referral_categories=["customs_broker", "freight_forwarder"],
            ),
            _outcome("NO_MATCH", "NOT_REQUIRED", "No declaration", "IMPORT_DECLARATION"),
        ],
        ref["id"],
    )
    vehicles = {"fact": "trade.goods_categories", "op": "contains", "value": "vehicles"}
    await _publish(
        admin,
        rs["id"],
        {"any": [vehicles]},
        [
            _outcome("MATCH", "APPROVAL_REQUIRED", "Vehicle approval", "VEHICLE_IMPORT_APPROVAL"),
            _outcome("NO_MATCH", "NOT_REQUIRED", "No vehicle approval", "VEHICLE_IMPORT_APPROVAL"),
        ],
        ref["id"],
    )

    customer = await api.user()
    project = await _trade_project(customer, description)
    org = _org(customer)
    r = await customer.post(f"{org}/projects/{project['id']}/assessments")
    assert r.status_code == 201, r.text
    assessment = r.json()
    ours = {f["id"] for f in assessment["finding_list"] if f["rule_set_id"] == rs["id"]}
    entries = [e for e in assessment["approval_map"] if set(e["finding_ids"]) <= ours]
    assert [(e["kind"], e["certainty"]) for e in entries] == [
        ("IMPORT_DECLARATION", "REQUIRED"),
        ("VEHICLE_IMPORT_APPROVAL", "NOT_IDENTIFIED"),
    ]
    referrals = {c["key"]: c for c in assessment["referral_categories"]}
    assert referrals["customs_broker"]["label"] == "Licensed customs broker"
    assert referrals["freight_forwarder"]["description"]

    # The trade report is the import and export approval map.
    r = await customer.post(
        f"{org}/assessments/{assessment['id']}/documents", json={"format": "HTML"}
    )
    assert r.status_code == 202, r.text
    html = (await customer.get(f"{org}/generated-documents/{r.json()['id']}/content")).text
    for expected in (
        "Import and export approval map",
        "Your approval map",
        "Full import declaration needed",
        "Licensed customs broker",
        "Freight forwarder",
        "Limitations",
    ):
        assert expected in html, expected

    # The customer can ask to be introduced to customs brokers and freight forwarders.
    body = await consent_body(
        customer, project, assessment, categories=["customs_broker", "freight_forwarder"]
    )
    r = await customer.get(
        f"{referrals_url(customer, project)}/options",
        params={"assessment_id": assessment["id"]},
    )
    options = r.json()
    assert {c["key"] for c in options["categories"]} >= {"customs_broker", "freight_forwarder"}
    assert options["location"]["postcode"] == "4870"
    r = await customer.post(referrals_url(customer, project), json=body)
    assert r.status_code == 201, r.text
    leads = [lead for referral in r.json() for lead in referral["leads"]]
    assert {lead["category_key"] for lead in leads} == {"customs_broker", "freight_forwarder"}


@pytest.mark.integration
async def test_business_profile_prefills_the_trade_questionnaire(api: ApiHarness) -> None:
    user = await api.user()
    org = _org(user)
    r = await user.post(
        f"{org}/projects",
        json={"vertical": "TRADE", "title": "Exports", "business_profile_id": await _profile(user)},
    )
    assert r.status_code == 201, r.text
    project = r.json()
    submission = (await user.post(f"{org}/projects/{project['id']}/submissions", json={})).json()
    r = await user.get(f"{org}/submissions/{submission['id']}/prefill")
    assert r.status_code == 200, r.text
    found = {s["key"]: s["value"] for s in r.json()["suggestions"]}
    assert found == {"trade.has_abn": True, "trade.gst_registered": True, "trade.state": "QLD"}
