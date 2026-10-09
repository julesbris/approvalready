"""PropertyReady (Milestone 11): the Queensland selling and renting content pack and checklists.

The pack's rules are checked offline (conditions parse, payloads are valid, every test case
passes, every fact is collected by the sell or rent questionnaire). Loading with
``--publish`` runs inside a transaction that is rolled back, so the shared test database
never gets published property rules that would change other tests' assessments.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app import cli
from app.modules.checklists import definition as checklist_definitions
from app.modules.conditions import parse_condition, referenced_facts
from app.modules.marketplace import service as marketplace
from app.modules.projects.models import Vertical
from app.modules.questionnaires.definition import load_bundled
from app.modules.regulatory.service import Actor
from app.modules.rules import engine, packs
from app.modules.rules.models import OutcomeType
from app.modules.rules.payload import parse_payload, validate_payload
from app.modules.tenancy.models import Organisation
from tests.harness import ApiHarness, platform_user

PACK = "property_qld"
QUESTIONNAIRES = {"SELL": "sell.general", "RENT": "rent.general"}


def _collected(vertical: str) -> set[str]:
    """Every fact path the vertical's questionnaire provides (address fields included)."""
    definition = next(d for d in load_bundled() if d.key == QUESTIONNAIRES[vertical])
    return {fact for q in definition.questions() for fact in q.fact_types()}


def _uses_not(node: Any) -> bool:
    if isinstance(node, dict):
        return "not" in node or any(_uses_not(v) for v in node.values())
    if isinstance(node, list):
        return any(_uses_not(v) for v in node)
    return False


def test_pack_is_listed_and_valid() -> None:
    assert PACK in packs.available()
    pack = packs.load_file(PACK)
    assert {rs.key for rs in pack.rule_sets} == {
        "sell.qld.seller_disclosure",
        "rent.qld.residential_tenancy",
    }
    assert {rs.vertical for rs in pack.rule_sets} == {"SELL", "RENT"}


def test_pack_rules_pass_their_own_test_cases() -> None:
    pack = packs.load_file(PACK)
    for rs in pack.rule_sets:
        assert rs.jurisdiction == "QLD"
        assert rs.applies_when == {
            "fact": "property.address.state",
            "op": "equals",
            "value": "QLD",
        }
        parse_condition(rs.applies_when)
        assert rs.limitations, f"{rs.key} must say what it doesn't check"
        for rule in rs.rules:
            assert not _uses_not(rule.condition), f"{rs.key}.{rule.key}: no 'not'"
            assert rule.effective_from == "2026-10-09"
            assert rule.max_confidence == "LIKELY"
            assert any(s.relationship == "BASIS" for s in rule.sources)
            condition = parse_condition(rule.condition)
            for outcome in rule.outcomes:
                validate_payload(outcome.outcome_type, outcome.payload)
            assert rule.test_cases
            for case in rule.test_cases:
                result = engine.run_test_case(
                    condition, case.name, case.facts, case.expected_result
                )
                assert result.passed, f"{rs.key}.{rule.key}: {case.name} gave {result.actual}"


def test_pack_only_reads_facts_the_questionnaires_collect() -> None:
    for rs in packs.load_file(PACK).rule_sets:
        collected = _collected(rs.vertical)
        for rule in rs.rules:
            for case in rule.test_cases:
                assert set(case.facts) <= collected, f"{rs.key}.{rule.key}: {case.name}"
        for rule_condition in [rs.applies_when, *(r.condition for r in rs.rules)]:
            assert rule_condition is not None
            for leaf in referenced_facts(parse_condition(rule_condition)):
                assert leaf.fact in collected, f"{rs.key}: {leaf.fact} is never asked"


def test_pack_marks_every_extract_as_a_summary() -> None:
    pack = packs.load_file(PACK)
    for ref in pack.references:
        assert ref.extracted_text.startswith("[Summary, not the source's wording]")
        assert ref.interpretation and "verify" in ref.interpretation
    cited = {s.reference for rs in pack.rule_sets for r in rs.rules for s in r.sources}
    assert cited == {r.ref for r in pack.references}, "every reference is cited by a rule"


def test_pack_names_only_real_checklists_and_categories() -> None:
    categories = {c.key: c for c in marketplace.load_bundled()}
    named: set[str] = set()
    for rs in packs.load_file(PACK).rule_sets:
        for rule in rs.rules:
            for o in rule.outcomes:
                payload = parse_payload(o.payload)
                for key in payload.referral_categories:
                    assert key in categories, f"{rs.key}.{rule.key}: no category {key}"
                    assert rs.vertical in categories[key].verticals, f"{key} not for {rs.vertical}"
                assert checklist_definitions.unknown_keys(payload.checklists) == []
                for key in payload.checklists:
                    assert checklist_definitions.bundled()[key].vertical == rs.vertical
                named |= set(payload.checklists)
    property_checklists = {
        d.key for vertical in ("SELL", "RENT") for d in checklist_definitions.for_vertical(vertical)
    }
    assert named == property_checklists, "every property checklist is reachable from a rule"


def test_cross_sell_outcomes_are_few_and_sensible() -> None:
    offers: list[tuple[str, list[str]]] = []
    for rs in packs.load_file(PACK).rule_sets:
        for rule in rs.rules:
            for o in rule.outcomes:
                payload = parse_payload(o.payload)
                if o.outcome_type == OutcomeType.CROSS_SELL:
                    assert payload.cross_sell, f"{rs.key}.{rule.key}: offers nothing"
                    assert rs.vertical not in payload.cross_sell, "never offer the same product"
                    assert set(payload.cross_sell) <= {v.value for v in Vertical}
                    offers.append((f"{rs.key}.{rule.key}", list(payload.cross_sell)))
                else:
                    assert not payload.cross_sell
    assert ("sell.qld.seller_disclosure.tenanted_sale_rent_ready", ["RENT"]) in offers
    assert len(offers) <= 3


def test_property_checklists_are_valid_and_cite_sources() -> None:
    found = checklist_definitions.bundled()
    assert set(found) >= {
        "sell.qld_disclosure",
        "sell.preparing_to_sell",
        "rent.qld_start_of_tenancy",
        "rent.qld_minimum_standards",
        "rent.qld_smoke_alarms",
        "rent.qld_end_of_tenancy",
    }
    for d in found.values():
        if d.vertical in ("SELL", "RENT"):
            assert d.sources and d.items
            assert all(str(s.url).startswith("https://") for s in d.sources)


def test_new_questions_only_collect_facts() -> None:
    sell = next(d for d in load_bundled() if d.key == "sell.general")
    questions = {q.key: q for q in sell.questions()}
    for key in ("sell.body_corporate", "sell.owner_builder_work"):
        assert {o.value for o in questions[key].options} == {"yes", "no", "unsure"}
        assert not questions[key].required


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
