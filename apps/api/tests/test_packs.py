"""The Cairns content pack and its loader (Milestone 5).

The pack's rules are checked offline (conditions parse, payloads are valid, every test case
passes, every fact is collected by the planning questionnaire). Loading with ``--publish``
runs inside a transaction that is rolled back, so the shared test database never gets
published Cairns rules that would change other tests' assessments.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app import cli
from app.modules.conditions import parse_condition, referenced_facts
from app.modules.questionnaires.definition import load_bundled
from app.modules.regulatory.models import SourceReference, VerificationStatus
from app.modules.regulatory.service import Actor
from app.modules.rules import engine, packs
from app.modules.rules.payload import validate_payload
from app.modules.tenancy.models import Organisation
from tests.harness import ApiHarness, platform_user

CAIRNS = "planning_qld_cairns"


def test_pack_is_listed_and_valid() -> None:
    assert CAIRNS in packs.available()
    pack = packs.load_file(CAIRNS)
    assert len(pack.rule_sets) == 3
    with pytest.raises(FileNotFoundError):
        packs.load_file("../definitions/planning")


def test_pack_rules_pass_their_own_test_cases() -> None:
    pack = packs.load_file(CAIRNS)
    for rs in pack.rule_sets:
        assert rs.applies_when is not None
        parse_condition(rs.applies_when)
        assert rs.limitations, f"{rs.key} must say what it doesn't check"
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


def test_pack_only_reads_facts_the_planning_questionnaire_collects() -> None:
    planning = next(d for d in load_bundled() if d.key == "planning.general")
    collected = {q.key for q in planning.questions()}
    pack = packs.load_file(CAIRNS)
    for rs in pack.rule_sets:
        conditions = [rs.applies_when, *(r.condition for r in rs.rules)]
        for condition in conditions:
            assert condition is not None
            for leaf in referenced_facts(parse_condition(condition)):
                assert leaf.fact in collected, f"{rs.key}: {leaf.fact} is never asked"


def test_pack_marks_every_extract_as_a_summary() -> None:
    """Nothing in the pack pretends to be the source's own wording."""
    pack = packs.load_file(CAIRNS)
    for ref in pack.references:
        assert ref.extracted_text.startswith("[Summary, not the source's wording]")
        assert ref.interpretation and "verify" in ref.interpretation


@pytest.mark.integration
async def test_load_and_publish_rolls_back_cleanly(api: ApiHarness) -> None:
    admin = await platform_user(api, "ADMIN")
    pack = packs.load_file(CAIRNS)
    suffix = uuid.uuid4().hex[:8]
    for rs in pack.rule_sets:  # fresh keys so earlier loads in this database don't matter
        rs.key = f"{rs.key}_{suffix}"
    factory = api.app.state.resources.session_factory
    async with factory() as db:
        org = (
            await db.execute(select(Organisation).where(Organisation.kind == "PLATFORM_ADMIN"))
        ).scalar_one()
        actor = Actor(uuid.UUID(admin.id), org.id, cli.CLI_META)
        report = await packs.load(db, pack, actor, publish=True)
        rule_count = sum(len(rs.rules) for rs in pack.rule_sets)
        assert len(report.published) == rule_count, report.lines()
        assert report.not_published == []
        # Published, but every source is unverified, and the gate said so.
        assert any("Not verified yet" in w for w in report.warnings)
        statuses = set(
            (
                await db.execute(
                    select(SourceReference.verification_status).where(
                        SourceReference.extracted_text.startswith("[Summary")
                    )
                )
            ).scalars()
        )
        assert statuses <= {VerificationStatus.UNVERIFIED, VerificationStatus.VERIFIED}

        # Loading again changes nothing.
        again = await packs.load(db, pack, actor, publish=True)
        assert again.created == [] and again.published == []
        await db.rollback()


@pytest.mark.integration
async def test_cli_requires_platform_permissions(api: ApiHarness) -> None:
    customer = await api.user()
    settings = api.app.state.settings
    assert await cli.load_pack(CAIRNS, customer.email, publish=False, settings=settings) == 1
    staff = await platform_user(api, "STAFF")
    # Staff may draft but not publish.
    assert await cli.load_pack(CAIRNS, staff.email, publish=True, settings=settings) == 1
    assert await cli.load_pack("nope", staff.email, publish=False, settings=settings) == 1
