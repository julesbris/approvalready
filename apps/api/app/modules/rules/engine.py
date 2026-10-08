"""Pure rule evaluation: results, confidence derivation, traces, facts encoding.

No database access, so the same functions serve assessments, the admin "try it" and test
case runs, and replaying a stored assessment to prove it is reproducible.

Confidence (ARCHITECTURE.md §1). A finding starts at ``VERIFIED`` and is lowered by every
problem found, never raised:

* the result is ``UNKNOWN`` (information missing) → ``UNKNOWN``;
* no source is cited → ``REVIEW_REQUIRED``;
* a cited reference is disputed or superseded, its document is not in force on the
  assessment date, its review date has passed, or the document's latest snapshot differs
  from the one it was verified against → ``REVIEW_REQUIRED``;
* a cited reference is not verified yet → ``LIKELY``;
* problems with ``SUPPORTING``/``EXCEPTION`` sources lower a finding to ``LIKELY`` at most;
  only the ``BASIS`` sources can make it ``REVIEW_REQUIRED``;
* finally the rule version's ``max_confidence`` caps the result.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.modules.conditions import Tri, missing_facts, trace
from app.modules.conditions.ast import All, AnyOf, Leaf, Not
from app.modules.regulatory.models import VerificationStatus
from app.modules.rules.models import Confidence, RuleResult, SourceRelationship

ENGINE_VERSION = "rules-engine/1"

C = Confidence
_RANK = {C.UNKNOWN: 0, C.REVIEW_REQUIRED: 1, C.LIKELY: 2, C.VERIFIED: 3}

Condition = All | AnyOf | Not | Leaf


def lowest(levels: Iterable[Confidence], default: Confidence = C.VERIFIED) -> Confidence:
    found = list(levels)
    return min(found, key=_RANK.__getitem__) if found else default


def result_of(value: Tri) -> RuleResult:
    return {Tri.TRUE: RuleResult.MATCH, Tri.FALSE: RuleResult.NO_MATCH}.get(
        value, RuleResult.UNKNOWN
    )


# --- Facts -----------------------------------------------------------------------------


def encode_facts(facts: Mapping[str, Any]) -> dict[str, Any]:
    """Facts as JSON that decodes back to the same typed values. Decimals are tagged
    (``{"$decimal": "812.5"}``) so precision survives; dates become ISO strings, which the
    evaluator already treats as dates."""

    def enc(value: Any) -> Any:
        if isinstance(value, Decimal):
            return {"$decimal": str(value)}
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, list):
            return [enc(v) for v in value]
        if isinstance(value, dict):
            return {str(k): enc(v) for k, v in value.items()}
        return value

    return {k: enc(v) for k, v in sorted(facts.items())}


def decode_facts(encoded: Mapping[str, Any]) -> dict[str, Any]:
    def dec(value: Any) -> Any:
        if isinstance(value, dict):
            if set(value) == {"$decimal"} and isinstance(value["$decimal"], str):
                return Decimal(value["$decimal"])
            return {k: dec(v) for k, v in value.items()}
        if isinstance(value, list):
            return [dec(v) for v in value]
        return value

    return {k: dec(v) for k, v in encoded.items()}


def canonical_hash(document: Any) -> bytes:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).digest()


# --- Sources ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceState:
    """A cited reference as it stands: what confidence derivation looks at."""

    reference_id: uuid.UUID
    relationship: str
    status: str
    document_title: str
    organisation_name: str
    url: str
    section: str | None
    clause: str | None
    page: str | None
    effective_from: date | None
    effective_to: date | None
    next_review_due: date | None
    verified_snapshot_id: uuid.UUID | None
    latest_snapshot_id: uuid.UUID | None

    def citation(self) -> str:
        parts = [p for p in (self.section, self.clause and f"cl. {self.clause}") if p]
        if self.page:
            parts.append(f"p. {self.page}")
        return f"{self.document_title}{', ' + ', '.join(parts) if parts else ''}"

    def in_force(self, on: date) -> bool:
        return (self.effective_from is None or self.effective_from <= on) and (
            self.effective_to is None or on < self.effective_to
        )

    def problems(self, on: date) -> list[tuple[Confidence, str]]:
        """What stops this reference supporting a verified finding on ``on``."""
        found: list[tuple[Confidence, str]] = []
        name = self.citation()
        if self.status in (VerificationStatus.DISPUTED, VerificationStatus.SUPERSEDED):
            found.append((C.REVIEW_REQUIRED, f"{name} is {self.status.lower()}."))
        if not self.in_force(on):
            found.append((C.REVIEW_REQUIRED, f"{name} is not in force on {on.isoformat()}."))
        if self.status == VerificationStatus.UNVERIFIED:
            found.append((C.LIKELY, f"{name} has not been verified yet."))
        if self.status == VerificationStatus.VERIFIED:
            if self.next_review_due is not None and self.next_review_due < on:
                found.append((C.REVIEW_REQUIRED, f"{name} is overdue for review."))
            if self.latest_snapshot_id is not None and (
                self.latest_snapshot_id != self.verified_snapshot_id
            ):
                found.append((C.REVIEW_REQUIRED, f"{name} has changed since it was verified."))
        if self.relationship != SourceRelationship.BASIS:
            # Supporting sources can weaken a finding, but not below "likely".
            found = [(max(level, C.LIKELY, key=_RANK.__getitem__), r) for level, r in found]
        return found

    def as_json(self, on: date) -> dict[str, Any]:
        return {
            "reference_id": str(self.reference_id),
            "relationship": self.relationship,
            "verification_status": self.status,
            "citation": self.citation(),
            "document_title": self.document_title,
            "organisation_name": self.organisation_name,
            "url": self.url,
            "section": self.section,
            "clause": self.clause,
            "page": self.page,
            "in_force": self.in_force(on),
        }


def derive_confidence(
    result: RuleResult,
    sources: Sequence[SourceState],
    on: date,
    max_confidence: Confidence = C.VERIFIED,
) -> tuple[Confidence, list[str]]:
    if result == RuleResult.UNKNOWN:
        return C.UNKNOWN, ["Some information this rule needs is missing."]
    problems: list[tuple[Confidence, str]] = []
    if not any(s.relationship == SourceRelationship.BASIS for s in sources):
        problems.append((C.REVIEW_REQUIRED, "No source is cited as the basis for this rule."))
    for source in sources:
        problems.extend(source.problems(on))
    level = lowest(p[0] for p in problems)
    reasons = [r for _, r in problems]
    if _RANK[max_confidence] < _RANK[level]:
        level = max_confidence
        reasons.append(f"This rule's confidence is capped at {max_confidence.lower()}.")
    return level, reasons


# --- Rules -----------------------------------------------------------------------------


@dataclass(frozen=True)
class OutcomeSpec:
    outcome_type: str
    title: str
    detail: str | None


@dataclass(frozen=True)
class RuleSpec:
    rule_version_id: uuid.UUID
    rule_set_id: uuid.UUID
    rule_key: str
    rule_title: str
    condition: Condition
    outcomes: Mapping[str, OutcomeSpec]  # by RuleResult
    sources: tuple[SourceState, ...]
    max_confidence: Confidence = C.VERIFIED
    effective_from: date | None = None
    effective_to: date | None = None

    def in_force(self, on: date) -> bool:
        return (self.effective_from is None or self.effective_from <= on) and (
            self.effective_to is None or on < self.effective_to
        )


@dataclass(frozen=True)
class Finding:
    rule_version_id: uuid.UUID
    rule_set_id: uuid.UUID
    rule_key: str
    rule_title: str
    result: RuleResult
    outcome: OutcomeSpec | None
    confidence: Confidence
    confidence_reasons: list[str]
    trace: dict[str, Any]
    missing_facts: list[str]
    sources: list[dict[str, Any]] = field(default_factory=list)


def evaluate_rule(spec: RuleSpec, facts: Mapping[str, Any], on: date) -> Finding:
    traced = trace(spec.condition, facts)
    result = result_of(Tri(traced["result"]))
    confidence, reasons = derive_confidence(result, spec.sources, on, spec.max_confidence)
    return Finding(
        rule_version_id=spec.rule_version_id,
        rule_set_id=spec.rule_set_id,
        rule_key=spec.rule_key,
        rule_title=spec.rule_title,
        result=result,
        outcome=spec.outcomes.get(result),
        confidence=confidence,
        confidence_reasons=reasons,
        trace=traced,
        missing_facts=missing_facts(traced),
        sources=[s.as_json(on) for s in spec.sources],
    )


@dataclass(frozen=True)
class RuleSetSpec:
    id: uuid.UUID
    key: str
    title: str
    applies_when: Condition | None
    applies_when_json: dict[str, Any] | None
    rules: tuple[RuleSpec, ...]


@dataclass(frozen=True)
class RuleSetResult:
    spec: RuleSetSpec
    scope: str  # IN_SCOPE, OUT_OF_SCOPE, NEEDS_INFORMATION
    scope_trace: dict[str, Any] | None
    missing_facts: list[str]
    findings: list[Finding]
    not_in_force: list[str]  # rule keys skipped because no version is in force on the date

    def as_json(self) -> dict[str, Any]:
        return {
            "rule_set_id": str(self.spec.id),
            "key": self.spec.key,
            "title": self.spec.title,
            "scope": self.scope,
            "applies_when": self.spec.applies_when_json,
            "scope_trace": self.scope_trace,
            "missing_facts": self.missing_facts,
            "not_in_force": self.not_in_force,
        }


def evaluate_rule_set(spec: RuleSetSpec, facts: Mapping[str, Any], on: date) -> RuleSetResult:
    """Scope first (R8: a location outside the rule set is never given the nearest match),
    then every rule in force on ``on``."""
    scope_trace = trace(spec.applies_when, facts) if spec.applies_when is not None else None
    scope = Tri(scope_trace["result"]) if scope_trace else Tri.TRUE
    if scope is not Tri.TRUE:
        return RuleSetResult(
            spec=spec,
            scope="OUT_OF_SCOPE" if scope is Tri.FALSE else "NEEDS_INFORMATION",
            scope_trace=scope_trace,
            missing_facts=missing_facts(scope_trace) if scope_trace else [],
            findings=[],
            not_in_force=[],
        )
    findings = [evaluate_rule(r, facts, on) for r in spec.rules if r.in_force(on)]
    return RuleSetResult(
        spec=spec,
        scope="IN_SCOPE",
        scope_trace=scope_trace,
        missing_facts=[],
        findings=findings,
        not_in_force=[r.rule_key for r in spec.rules if not r.in_force(on)],
    )


def overall_confidence(results: Sequence[RuleSetResult]) -> Confidence:
    """The weakest finding; ``UNKNOWN`` when a rule set could not be checked or there is
    nothing to rely on."""
    if not results or any(r.scope == "NEEDS_INFORMATION" for r in results):
        return C.UNKNOWN
    findings = [f for r in results for f in r.findings]
    if not findings:
        return C.UNKNOWN
    return lowest(f.confidence for f in findings)


# --- Test cases ------------------------------------------------------------------------


@dataclass(frozen=True)
class TestCaseResult:
    name: str
    expected: RuleResult
    actual: RuleResult
    trace: dict[str, Any]

    @property
    def passed(self) -> bool:
        return self.expected == self.actual


def run_test_case(
    condition: Condition, name: str, facts: Mapping[str, Any], expected: str
) -> TestCaseResult:
    traced = trace(condition, decode_facts(facts))
    return TestCaseResult(
        name=name,
        expected=RuleResult(expected),
        actual=result_of(Tri(traced["result"])),
        trace=traced,
    )
