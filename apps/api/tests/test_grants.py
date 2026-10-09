"""GrantReady (Milestone 10): the grant content pack, match decisions, round states, the
staff screens for programs and rounds, matches on grant assessments, the eligibility
report and grant prefill from a business profile.

GRANT rule sets created here are scoped to a postcode unique to each test, so other tests'
programs come out "not eligible" for these projects and are filtered out by id. The real
pack is only checked offline and loaded inside a transaction that is rolled back.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app import cli
from app.modules.conditions import parse_condition, referenced_facts
from app.modules.grants import matching
from app.modules.grants import service as grants
from app.modules.grants.models import GrantProgram, MatchStatus, RoundStatus
from app.modules.grants.service import today
from app.modules.marketplace import service as marketplace
from app.modules.projects.models import Project
from app.modules.questionnaires.definition import load_bundled
from app.modules.regulatory.service import Actor
from app.modules.rules import engine, packs
from app.modules.rules.payload import parse_payload, validate_payload
from app.modules.tenancy.models import Organisation
from tests.harness import ApiHarness, User, platform_user
from tests.regulatory_helpers import ADMIN, published_rule, reference, rule_set

PACK = "grants_au_qld"


def _org(user: User) -> str:
    return f"/v1/organisations/{user.personal_org_id}"


def _postcode() -> str:
    return f"{uuid.uuid4().int % 9000 + 1000}"


# --- The grant content pack ------------------------------------------------------------


def test_pack_rules_pass_their_own_test_cases() -> None:
    pack = packs.load_file(PACK)
    assert len(pack.rule_sets) == 3
    for rs in pack.rule_sets:
        assert rs.vertical == "GRANT"
        assert rs.limitations, f"{rs.key} must say what it doesn't check"
        assert any("succeed" in text for text in rs.limitations), "no promise of success"
        assert rs.applies_when is not None
        parse_condition(rs.applies_when)
        for rule in rs.rules:
            condition = parse_condition(rule.condition)
            # Every rule is a criterion: it says what happens when met, not met and unknown.
            assert {o.on_result for o in rule.outcomes} == {"MATCH", "NO_MATCH", "UNKNOWN"}
            for outcome in rule.outcomes:
                validate_payload(outcome.outcome_type, outcome.payload)
            results = {case.expected_result for case in rule.test_cases}
            assert {"MATCH", "NO_MATCH", "UNKNOWN"} <= results, f"{rule.key} needs all three"
            for case in rule.test_cases:
                result = engine.run_test_case(
                    condition, case.name, case.facts, case.expected_result
                )
                assert result.passed, f"{rs.key}.{rule.key}: {case.name} gave {result.actual}"


def test_pack_only_reads_facts_the_grant_questionnaire_collects() -> None:
    grant = next(d for d in load_bundled() if d.key == "grant.general")
    collected = {q.key for q in grant.questions()}
    for rs in packs.load_file(PACK).rule_sets:
        for condition in [rs.applies_when, *(r.condition for r in rs.rules)]:
            assert condition is not None
            for leaf in referenced_facts(parse_condition(condition)):
                assert leaf.fact in collected, f"{rs.key}: {leaf.fact} is never asked"


def test_pack_marks_every_extract_as_a_summary_and_names_real_categories() -> None:
    pack = packs.load_file(PACK)
    for ref in pack.references:
        assert ref.extracted_text.startswith("[Summary, not the source's wording]")
        assert ref.interpretation and "verify" in ref.interpretation
    categories = {c.key for c in marketplace.load_bundled()}
    for rs in pack.rule_sets:
        for rule in rs.rules:
            for o in rule.outcomes:
                assert set(parse_payload(o.payload).referral_categories) <= categories


def test_pack_programs_cite_their_round_dates() -> None:
    pack = packs.load_file(PACK)
    assert {p.rule_set for p in pack.grant_programs} == {rs.key for rs in pack.rule_sets}
    for p in pack.grant_programs:
        assert p.rounds, f"{p.key} needs at least one sourced round"
        for r in p.rounds:
            assert r.reference


def test_pack_rejects_a_program_without_its_rule_set() -> None:
    raw = packs.load_file(PACK).model_dump(mode="json")
    raw["grant_programs"][0]["rule_set"] = "grant.nowhere"
    with pytest.raises(ValueError, match=r"no rule set grant\.nowhere"):
        packs.Pack.model_validate(raw)


@pytest.mark.integration
async def test_pack_loads_programs_and_publishes_then_rolls_back(api: ApiHarness) -> None:
    admin = await platform_user(api, "ADMIN")
    pack = packs.load_file(PACK)
    suffix = uuid.uuid4().hex[:8]
    for rs in pack.rule_sets:
        old = rs.key
        rs.key = f"{rs.key}_{suffix}"
        for p in pack.grant_programs:
            if p.rule_set == old:
                p.rule_set = rs.key
    for p in pack.grant_programs:
        p.key = f"{p.key}_{suffix}"
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
        created = [c for c in report.created if c.startswith("grant program")]
        assert len(created) == 6  # 3 programs and their 3 rounds
        found = (
            await db.execute(select(GrantProgram).where(GrantProgram.key.like(f"%_{suffix}")))
        ).scalars()
        assert len(list(found)) == 3
        # Loading again leaves programs (and their rounds) alone.
        again = await packs.load(
            db, pack, Actor(uuid.UUID(admin.id), org.id, cli.CLI_META), publish=False
        )
        assert sum(e.startswith("grant program") for e in again.existing) == 3
        await db.rollback()


# --- Match decisions (pure) ------------------------------------------------------------


@dataclass
class _F:
    result: str
    confidence: str = "VERIFIED"
    missing_facts: list[str] = field(default_factory=list)
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    rule_set_id: uuid.UUID = field(default_factory=uuid.uuid4)
    rule_key: str = "criterion"
    rule_title: str = "A criterion"
    title: str | None = None


IN = {"scope": "IN_SCOPE", "missing_facts": []}


def test_who_can_apply_decides_first() -> None:
    out = matching.decide({"scope": "OUT_OF_SCOPE", "missing_facts": []}, [])
    assert out is not None and out.status == MatchStatus.NOT_ELIGIBLE
    assert out.criteria[0]["kind"] == "WHO_CAN_APPLY"
    out = matching.decide({"scope": "NEEDS_INFORMATION", "missing_facts": ["grant.state"]}, [])
    assert out is not None and out.status == MatchStatus.NEEDS_INFORMATION
    assert out.missing_facts == ["grant.state"]
    assert matching.decide(IN, []) is None


def test_an_unmet_criterion_beats_missing_information() -> None:
    out = matching.decide(
        IN,
        [_F("MATCH"), _F("UNKNOWN", "UNKNOWN", ["grant.innovative"]), _F("NO_MATCH", "LIKELY")],
    )
    assert out is not None
    assert out.status == MatchStatus.NOT_ELIGIBLE
    assert out.confidence == "LIKELY"
    assert out.missing_facts == ["grant.innovative"]  # still listed
    assert [c["result"] for c in out.criteria] == ["MATCH", "UNKNOWN", "NO_MATCH"]


def test_unanswered_criteria_need_information() -> None:
    out = matching.decide(
        IN, [_F("MATCH"), _F("UNKNOWN", "UNKNOWN", ["a", "b"]), _F("UNKNOWN", "UNKNOWN", ["a"])]
    )
    assert out is not None
    assert (out.status, out.missing_facts) == (MatchStatus.NEEDS_INFORMATION, ["a", "b"])


def test_all_met_is_strong_only_when_every_source_holds_up() -> None:
    strong = matching.decide(IN, [_F("MATCH"), _F("MATCH", "LIKELY")])
    assert strong is not None
    assert (strong.status, strong.confidence) == (MatchStatus.STRONG_MATCH, "LIKELY")
    possible = matching.decide(IN, [_F("MATCH"), _F("MATCH", "REVIEW_REQUIRED")])
    assert possible is not None and possible.status == MatchStatus.POSSIBLE_MATCH


# --- Round states (pure) ---------------------------------------------------------------


@dataclass
class _R:
    status: str
    opens_on: date | None = None
    closes_on: date | None = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)


ON = date(2026, 10, 9)


def test_round_state_follows_the_dates() -> None:
    s = matching.round_state(_R("OPEN", ON - timedelta(days=30), ON - timedelta(days=1)), ON)
    assert s.state == RoundStatus.CLOSED and s.days_to_close is None
    s = matching.round_state(_R("OPEN", None, ON + timedelta(days=10)), ON)
    assert (s.state, s.days_to_close, s.closing_soon) == (RoundStatus.OPEN, 10, True)
    s = matching.round_state(_R("OPEN", None, ON + timedelta(days=40)), ON)
    assert (s.days_to_close, s.closing_soon) == (40, False)
    s = matching.round_state(_R("OPEN", None, ON), ON)  # closes today: still open
    assert (s.state, s.days_to_close) == (RoundStatus.OPEN, 0)
    s = matching.round_state(_R("OPEN", ON + timedelta(days=3)), ON)
    assert s.state == RoundStatus.UPCOMING
    s = matching.round_state(_R("UPCOMING", ON - timedelta(days=1)), ON)
    assert (s.state, s.check_source) == (RoundStatus.UPCOMING, True)
    s = matching.round_state(_R("PAUSED"), ON)
    assert (s.state, s.check_source) == (RoundStatus.PAUSED, False)


def test_current_round_prefers_open_then_upcoming() -> None:
    old = _R("CLOSED", ON - timedelta(days=400), ON - timedelta(days=360))
    recent = _R("CLOSED", ON - timedelta(days=60), ON - timedelta(days=30))
    soon = _R("UPCOMING", ON + timedelta(days=5))
    later = _R("UPCOMING", ON + timedelta(days=50))
    open_ = _R("OPEN", ON - timedelta(days=5), ON + timedelta(days=5))
    assert matching.current_round([old, recent, later, soon, open_], ON) is open_
    assert matching.current_round([old, recent, later, soon], ON) is soon
    assert matching.current_round([old, recent], ON) is recent
    assert matching.current_round([], ON) is None


# --- Staff screens ----------------------------------------------------------------------


async def _program(admin: User, rule_set_id: str, **overrides: Any) -> dict[str, Any]:
    org = await admin.post(
        f"{ADMIN}/source-organisations",
        json={
            "name": f"Test Grant Body {uuid.uuid4().hex[:8]}",
            "kind": "GRANT_BODY",
            "jurisdiction": "QLD",
        },
    )
    assert org.status_code == 201, org.text
    body = {
        "key": f"test.grant_{uuid.uuid4().hex[:10]}",
        "title": "Test Growth Grant",
        "summary": "A fictional grant for tests.",
        "administrator_id": org.json()["id"],
        "jurisdiction": "QLD",
        "url": "https://example.com/grant",
        "rule_set_id": rule_set_id,
        "funding_summary": "$10,000 to $20,000",
        "min_amount_cents": 1_000_000,
        "max_amount_cents": 2_000_000,
        **overrides,
    }
    r = await admin.post(f"{ADMIN}/grant-programs", json=body)
    assert r.status_code == 201, r.text
    return dict(r.json())


@pytest.mark.integration
async def test_staff_manage_programs_and_sourced_rounds(api: ApiHarness) -> None:
    staff = await platform_user(api, "STAFF")
    rs = await rule_set(staff, vertical="GRANT")
    ref = await reference(staff, verify=False)

    # Eligibility must be a GRANT rule set, used by one program only.
    vessel_rs = await rule_set(staff, vertical="VESSEL")
    r = await staff.post(
        f"{ADMIN}/grant-programs",
        json={
            "key": "test.bad",
            "title": "Bad",
            "summary": "x",
            "jurisdiction": "QLD",
            "url": "https://example.com",
            "rule_set_id": vessel_rs["id"],
            "administrator_id": ref["id"],
        },
    )
    assert r.status_code in (404, 422)
    program = await _program(staff, rs["id"])
    assert program["rounds"] == [] and program["current_round_id"] is None
    org_id = program["administrator"]["id"]
    r = await staff.post(
        f"{ADMIN}/grant-programs",
        json={
            "key": f"test.again_{uuid.uuid4().hex[:6]}",
            "title": "Again",
            "summary": "x",
            "jurisdiction": "QLD",
            "url": "https://example.com",
            "rule_set_id": rs["id"],
            "administrator_id": org_id,
        },
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "rule_set_taken"

    # Rounds must cite a source and can't close before they open.
    url = f"{ADMIN}/grant-programs/{program['id']}/rounds"
    r = await staff.post(url, json={"title": "Round 1", "status": "OPEN"})
    assert r.status_code == 422
    r = await staff.post(
        url,
        json={
            "title": "Round 1",
            "status": "OPEN",
            "opens_on": "2026-10-01",
            "closes_on": "2026-09-01",
            "source_reference_id": ref["id"],
        },
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "closes_before_opens"
    closes = today() + timedelta(days=7)
    r = await staff.post(
        url,
        json={
            "title": "Round 1",
            "status": "OPEN",
            "opens_on": "2026-01-01",
            "closes_on": closes.isoformat(),
            "dates_note": "5pm AEST",
            "source_reference_id": ref["id"],
        },
    )
    assert r.status_code == 201, r.text
    [round_] = r.json()["rounds"]
    assert r.json()["current_round_id"] == round_["id"]
    assert (round_["state"], round_["days_to_close"], round_["closing_soon"]) == ("OPEN", 7, True)
    assert round_["source"]["verification_status"] == "UNVERIFIED"
    assert round_["source"]["url"] == "https://example.com/planning-scheme"
    r = await staff.post(
        url, json={"title": "Round 1", "status": "UPCOMING", "source_reference_id": ref["id"]}
    )
    assert r.status_code == 409

    # Changing a round re-cites its source; the change is audited.
    r = await staff.patch(f"{ADMIN}/grant-rounds/{round_['id']}", json={"status": "PAUSED"})
    assert r.status_code == 422  # no source cited
    r = await staff.patch(
        f"{ADMIN}/grant-rounds/{round_['id']}",
        json={"status": "PAUSED", "source_reference_id": ref["id"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["rounds"][0]["state"] == "PAUSED"
    r = await staff.patch(f"{ADMIN}/grant-programs/{program['id']}", json={"status": "RETIRED"})
    assert r.status_code == 200 and r.json()["status"] == "RETIRED"
    listed = (await staff.get(f"{ADMIN}/grant-programs")).json()
    assert program["id"] in {p["id"] for p in listed}

    # Customers can't reach the staff screens.
    customer = await api.user()
    assert (await customer.get(f"{ADMIN}/grant-programs")).status_code in (403, 404)


# --- Matches on grant assessments ------------------------------------------------------


GRANT_ANSWERS: dict[str, Any] = {
    "grant.applicant_type": "business",
    "grant.has_abn": True,
    "grant.abn_two_years": True,
    "grant.gst_registered": True,
    "grant.entity_type": "COMPANY",
    "grant.state": "QLD",
    "grant.trading_age": "over_3",
    "grant.employee_band": "5_19",
    "grant.annual_turnover_cents": 150_000_000,
    "grant.project_purpose": ["equipment"],
    "grant.project_description": "Buy a new CNC machine to double production.",
    "grant.total_cost_cents": 20_000_000,
    "grant.co_contribution_available": True,
    "grant.co_contribution_cents": 10_000_000,
    "grant.project_started": False,
}


async def _grant_project(user: User, **fields: Any) -> dict[str, Any]:
    r = await user.post(
        f"{_org(user)}/projects", json={"vertical": "GRANT", "title": "Machine", **fields}
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


async def _submit(user: User, project: dict[str, Any], answers: dict[str, Any]) -> None:
    org = _org(user)
    submission = (await user.post(f"{org}/projects/{project['id']}/submissions", json={})).json()
    r = await user.put(f"{org}/submissions/{submission['id']}/answers", json={"answers": answers})
    assert r.status_code == 200, r.text
    r = await user.post(f"{org}/submissions/{submission['id']}/submit")
    assert r.status_code == 200, r.text


def _criterion(fact: str, op: str, value: Any) -> dict[str, Any]:
    return {"fact": fact, "op": op, "value": value}


@pytest.mark.integration
async def test_grant_assessment_records_matches_and_reports_them(api: ApiHarness) -> None:
    admin = await platform_user(api, "ADMIN")
    postcode = _postcode()
    rs = await rule_set(
        admin, vertical="GRANT", applies_when=_criterion("grant.postcode", "equals", postcode)
    )
    ref = await reference(admin)
    outcomes = [
        {"on_result": "MATCH", "outcome_type": "INFO", "title": "Met"},
        {"on_result": "NO_MATCH", "outcome_type": "WARNING", "title": "Not met"},
    ]
    await published_rule(
        admin,
        rs["id"],
        _criterion("grant.employee_band", "in", ["NONE", "1_4", "5_19"]),
        [ref["id"]],
        outcomes=outcomes,
    )
    await published_rule(
        admin,
        rs["id"],
        _criterion("grant.project_purpose", "contains", "equipment"),
        [ref["id"]],
        outcomes=outcomes,
    )
    program = await _program(admin, rs["id"])
    closes = today() + timedelta(days=20)
    r = await admin.post(
        f"{ADMIN}/grant-programs/{program['id']}/rounds",
        json={
            "title": "Round 2",
            "status": "OPEN",
            "closes_on": closes.isoformat(),
            "source_reference_id": ref["id"],
        },
    )
    assert r.status_code == 201, r.text

    user = await api.user()
    org = _org(user)
    project = await _grant_project(user)
    await _submit(user, project, {**GRANT_ANSWERS, "grant.postcode": postcode})
    r = await user.post(f"{org}/projects/{project['id']}/assessments")
    assert r.status_code == 201, r.text
    assessment = r.json()
    ours = [m for m in assessment["grant_matches"] if m["program"]["id"] == program["id"]]
    assert len(ours) == 1
    match = ours[0]
    assert (match["status"], match["confidence"]) == ("STRONG_MATCH", "VERIFIED")
    assert [c["result"] for c in match["criteria"]] == ["MATCH", "MATCH"]
    assert match["program"]["rounds"][0]["state"] == "OPEN"
    assert match["round_id_at_assessment"] == match["program"]["current_round_id"]
    # Best news first.
    order = [m["status"] for m in assessment["grant_matches"]]
    assert order.index("STRONG_MATCH") == 0

    # The eligibility report is the grant default and lays out the program.
    r = await user.post(f"{org}/assessments/{assessment['id']}/documents", json={"format": "HTML"})
    assert r.status_code == 202, r.text
    assert r.json()["template_key"] == "GRANT_ELIGIBILITY"
    html = " ".join(
        (await user.get(f"{org}/generated-documents/{r.json()['id']}/content")).text.split()
    )
    for expected in (
        "Grant eligibility check",
        "Test Growth Grant",
        "Meets every criterion we check",
        "Round 2",
        "does not mean an application will succeed",
    ):
        assert expected in html, expected

    # A criterion not met makes it not eligible; an unanswered one asks for information.
    project2 = await _grant_project(user)
    await _submit(
        user,
        project2,
        {**GRANT_ANSWERS, "grant.postcode": postcode, "grant.employee_band": "20_199"},
    )
    r = await user.post(f"{org}/projects/{project2['id']}/assessments")
    match = next(m for m in r.json()["grant_matches"] if m["program"]["id"] == program["id"])
    assert match["status"] == "NOT_ELIGIBLE"
    project3 = await _grant_project(user)
    answers = {k: v for k, v in GRANT_ANSWERS.items() if k != "grant.employee_band"}
    await _submit(user, project3, {**answers, "grant.postcode": postcode})
    r = await user.post(f"{org}/projects/{project3['id']}/assessments")
    match = next(m for m in r.json()["grant_matches"] if m["program"]["id"] == program["id"])
    assert (match["status"], match["missing_facts"]) == (
        "NEEDS_INFORMATION",
        ["grant.employee_band"],
    )

    # Somewhere else, who can apply isn't met; retired programs aren't matched at all.
    project4 = await _grant_project(user)
    await _submit(user, project4, {**GRANT_ANSWERS, "grant.postcode": "0000"})
    r = await user.post(f"{org}/projects/{project4['id']}/assessments")
    match = next(m for m in r.json()["grant_matches"] if m["program"]["id"] == program["id"])
    assert match["status"] == "NOT_ELIGIBLE"
    assert match["criteria"][0]["kind"] == "WHO_CAN_APPLY"
    r = await admin.patch(f"{ADMIN}/grant-programs/{program['id']}", json={"status": "RETIRED"})
    assert r.status_code == 200
    r = await user.post(f"{org}/projects/{project4['id']}/assessments")
    assert program["id"] not in {m["program"]["id"] for m in r.json()["grant_matches"]}

    # Other organisations can't read the matches.
    other = await api.user()
    r = await other.get(f"{_org(other)}/assessments/{assessment['id']}")
    assert r.status_code == 404


@pytest.mark.integration
async def test_other_verticals_get_no_grant_matches(api: ApiHarness) -> None:
    factory = api.app.state.resources.session_factory
    async with factory() as db:
        project = Project(vertical="BUSINESS", organisation_id=uuid.uuid4())
        assert await grants.record_matches(db, project, uuid.uuid4(), [], [], today()) == []


@pytest.mark.integration
async def test_business_profile_prefills_the_grant_questionnaire(api: ApiHarness) -> None:
    user = await api.user()
    org = _org(user)
    established = today().replace(year=today().year - 5)
    r = await user.post(
        f"{org}/business-profiles",
        json={
            "legal_name": "Reef Fabrication Pty Ltd",
            "entity_type": "COMPANY",
            "abn": "51 824 753 556",
            "gst_registered": True,
            "established_on": established.isoformat(),
            "employee_band": "5_19",
            "turnover_band": "75K_2M",
            "address": {
                "line1": "1 Esplanade",
                "suburb": "Cairns",
                "state": "QLD",
                "postcode": "4870",
            },
        },
    )
    assert r.status_code == 201, r.text
    project = await _grant_project(user, business_profile_id=r.json()["id"])
    submission = (await user.post(f"{org}/projects/{project['id']}/submissions", json={})).json()
    r = await user.get(f"{org}/submissions/{submission['id']}/prefill")
    assert r.status_code == 200, r.text
    found = {s["key"]: s["value"] for s in r.json()["suggestions"]}
    assert found == {
        "grant.applicant_type": "business",
        "grant.has_abn": True,
        "grant.gst_registered": True,
        "grant.entity_type": "COMPANY",
        "grant.employee_band": "5_19",
        "grant.turnover_band": "75K_2M",
        "grant.trading_age": "over_3",
        "grant.state": "QLD",
        "grant.postcode": "4870",
    }
