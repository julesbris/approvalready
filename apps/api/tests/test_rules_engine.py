"""Rules engine (pure): confidence derivation, scope, effective dates, facts encoding."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app.modules.conditions import parse_condition
from app.modules.rules import engine
from app.modules.rules.models import Confidence as C
from app.modules.rules.models import RuleResult as R

ON = date(2026, 10, 8)
SNAP = uuid.uuid4()


def source(**overrides: Any) -> engine.SourceState:
    base = engine.SourceState(
        reference_id=uuid.uuid4(),
        relationship="BASIS",
        status="VERIFIED",
        document_title="Example Planning Scheme",
        organisation_name="Example Council",
        url="https://example.com/scheme",
        section="Part 6",
        clause="6.2.1",
        page="12",
        effective_from=date(2020, 1, 1),
        effective_to=None,
        next_review_due=date(2027, 1, 1),
        verified_snapshot_id=SNAP,
        latest_snapshot_id=SNAP,
    )
    return replace(base, **overrides)


@pytest.mark.parametrize(
    ("sources", "expected"),
    [
        ([source()], C.VERIFIED),
        ([source(status="UNVERIFIED", verified_snapshot_id=None)], C.LIKELY),
        ([source(status="DISPUTED")], C.REVIEW_REQUIRED),
        ([source(status="SUPERSEDED")], C.REVIEW_REQUIRED),
        ([source(next_review_due=date(2026, 10, 7))], C.REVIEW_REQUIRED),  # overdue
        ([source(next_review_due=ON)], C.VERIFIED),  # due today is not overdue
        ([source(latest_snapshot_id=uuid.uuid4())], C.REVIEW_REQUIRED),  # source changed
        ([source(effective_from=date(2026, 10, 9))], C.REVIEW_REQUIRED),  # not yet in force
        ([source(effective_to=ON)], C.REVIEW_REQUIRED),  # effective_to is exclusive
        ([source(effective_to=date(2026, 10, 9))], C.VERIFIED),
        ([], C.REVIEW_REQUIRED),  # nothing cited
        ([source(relationship="SUPPORTING")], C.REVIEW_REQUIRED),  # no BASIS source
        # A weak supporting source lowers a finding to "likely", never further.
        ([source(), source(relationship="SUPPORTING", status="DISPUTED")], C.LIKELY),
        ([source(), source(relationship="EXCEPTION", status="UNVERIFIED")], C.LIKELY),
        ([source(), source(status="UNVERIFIED"), source(status="DISPUTED")], C.REVIEW_REQUIRED),
    ],
)
def test_confidence_from_sources(sources: list[engine.SourceState], expected: C) -> None:
    level, reasons = engine.derive_confidence(R.MATCH, sources, ON)
    assert level == expected
    assert bool(reasons) == (expected != C.VERIFIED)


def test_unknown_result_is_unknown_confidence_whatever_the_sources() -> None:
    level, reasons = engine.derive_confidence(R.UNKNOWN, [source()], ON)
    assert level == C.UNKNOWN
    assert reasons == ["Some information this rule needs is missing."]


def test_no_match_is_as_reliable_as_its_sources() -> None:
    assert engine.derive_confidence(R.NO_MATCH, [source()], ON)[0] == C.VERIFIED


def test_max_confidence_caps_and_explains() -> None:
    level, reasons = engine.derive_confidence(R.MATCH, [source()], ON, C.LIKELY)
    assert level == C.LIKELY
    assert reasons == ["This rule's confidence is capped at likely."]
    # A cap never raises a lower level.
    level, _ = engine.derive_confidence(R.MATCH, [source(status="DISPUTED")], ON, C.LIKELY)
    assert level == C.REVIEW_REQUIRED


def rule(**overrides: Any) -> engine.RuleSpec:
    base = engine.RuleSpec(
        rule_version_id=uuid.uuid4(),
        rule_set_id=uuid.uuid4(),
        rule_key="secondary_dwelling.size",
        rule_title="Secondary dwelling size",
        condition=parse_condition(
            {"fact": "planning.secondary_dwelling_floor_area_m2", "op": "greater_than", "value": 80}
        ),
        outcomes={
            R.MATCH: engine.OutcomeSpec("APPROVAL_REQUIRED", "Approval likely needed", None),
            R.NO_MATCH: engine.OutcomeSpec("INFO", "Within the size limit", None),
        },
        sources=(source(),),
        effective_from=date(2026, 1, 1),
    )
    return replace(base, **overrides)


def test_evaluate_rule_records_outcome_trace_and_sources() -> None:
    finding = engine.evaluate_rule(
        rule(), {"planning.secondary_dwelling_floor_area_m2": Decimal("92.5")}, ON
    )
    assert finding.result == R.MATCH
    assert finding.outcome is not None and finding.outcome.title == "Approval likely needed"
    assert finding.confidence == C.VERIFIED
    assert finding.trace["actual"] == "92.5"
    assert finding.missing_facts == []
    assert finding.sources[0]["citation"] == "Example Planning Scheme, Part 6, cl. 6.2.1, p. 12"
    assert finding.sources[0]["in_force"] is True

    missing = engine.evaluate_rule(rule(), {}, ON)
    assert missing.result == R.UNKNOWN
    assert missing.outcome is None  # no outcome defined for UNKNOWN
    assert missing.confidence == C.UNKNOWN
    assert missing.missing_facts == ["planning.secondary_dwelling_floor_area_m2"]


def test_rule_set_scope_and_effective_dates() -> None:
    in_force = rule()
    future = rule(rule_key="future", effective_from=date(2027, 7, 1))
    ended = rule(rule_key="ended", effective_to=ON)
    spec = engine.RuleSetSpec(
        id=uuid.uuid4(),
        key="planning.example",
        title="Example",
        applies_when=parse_condition({"fact": "property.lga", "op": "equals", "value": "CAIRNS"}),
        applies_when_json={"fact": "property.lga", "op": "equals", "value": "CAIRNS"},
        rules=(in_force, future, ended),
    )
    facts: dict[str, Any] = {"planning.secondary_dwelling_floor_area_m2": 60}

    outside = engine.evaluate_rule_set(spec, {**facts, "property.lga": "TOWNSVILLE"}, ON)
    assert outside.scope == "OUT_OF_SCOPE" and outside.findings == []

    unknown = engine.evaluate_rule_set(spec, facts, ON)
    assert unknown.scope == "NEEDS_INFORMATION"
    assert unknown.missing_facts == ["property.lga"]
    assert engine.overall_confidence([unknown]) == C.UNKNOWN

    inside = engine.evaluate_rule_set(spec, {**facts, "property.lga": "CAIRNS"}, ON)
    assert inside.scope == "IN_SCOPE"
    assert [f.rule_key for f in inside.findings] == ["secondary_dwelling.size"]
    assert inside.not_in_force == ["future", "ended"]
    assert inside.findings[0].result == R.NO_MATCH
    assert engine.overall_confidence([inside]) == C.VERIFIED
    assert engine.overall_confidence([]) == C.UNKNOWN


def test_overall_confidence_is_the_weakest_finding() -> None:
    weak = rule(rule_key="weak", sources=(source(status="UNVERIFIED"),))
    spec = engine.RuleSetSpec(uuid.uuid4(), "k", "t", None, None, (rule(), weak))
    result = engine.evaluate_rule_set(spec, {"planning.secondary_dwelling_floor_area_m2": 90}, ON)
    assert [f.confidence for f in result.findings] == [C.VERIFIED, C.LIKELY]
    assert engine.overall_confidence([result]) == C.LIKELY


def test_facts_encoding_round_trips_exactly() -> None:
    facts = {
        "b.area": Decimal("812.25"),
        "a.when": date(2026, 7, 1),
        "c.list": ["x", "y"],
        "d.address": {"suburb": "Cairns", "postcode": "4870"},
        "e.flag": False,
        "f.count": 3,
    }
    encoded = engine.encode_facts(facts)
    assert list(encoded) == sorted(facts)
    assert encoded["b.area"] == {"$decimal": "812.25"}
    assert encoded["a.when"] == "2026-07-01"
    decoded = engine.decode_facts(encoded)
    assert decoded["b.area"] == Decimal("812.25") and isinstance(decoded["b.area"], Decimal)
    # Dates come back as ISO strings, which every operator treats as dates.
    node = parse_condition({"fact": "a.when", "op": "greater_equal", "value": "2026-07-01"})
    assert engine.evaluate_rule(rule(condition=node), decoded, ON).result == R.MATCH
    assert engine.canonical_hash(encoded) == engine.canonical_hash(dict(reversed(encoded.items())))


def test_test_cases_compare_expected_and_actual() -> None:
    node = rule().condition
    ok = engine.run_test_case(
        node, "big", {"planning.secondary_dwelling_floor_area_m2": {"$decimal": "80.1"}}, "MATCH"
    )
    assert ok.passed and ok.actual == R.MATCH
    bad = engine.run_test_case(node, "empty", {}, "NO_MATCH")
    assert not bad.passed and bad.actual == R.UNKNOWN
