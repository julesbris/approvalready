"""Pure decisions for GrantReady: a program's match status from its rule set's findings,
and a round's state on a date. No database access, so both are easy to test and replay.

Every rule in a program's eligibility rule set is one criterion, written so that it
**matches when the criterion is met**. The rule set's ``applies_when`` is "who can apply".

* Who can apply is not met (out of scope) → ``NOT_ELIGIBLE``; not known → ``NEEDS_INFORMATION``.
* Any criterion not met → ``NOT_ELIGIBLE`` (unanswered ones are still listed).
* Otherwise any criterion unanswered → ``NEEDS_INFORMATION``.
* Every criterion met → ``STRONG_MATCH`` when every finding is at least likely, else
  ``POSSIBLE_MATCH`` (a source is disputed, out of date or overdue for review).

There is no success percentage (R5): meeting the criteria we check says nothing about how a
competitive round will be decided, and the screens say so.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from app.modules.grants.models import MatchStatus, RoundStatus
from app.modules.rules.engine import lowest
from app.modules.rules.models import Confidence, RuleResult

CLOSING_SOON_DAYS = 14
STRONG = (Confidence.VERIFIED, Confidence.LIKELY)


class FindingLike(Protocol):
    id: uuid.UUID
    rule_set_id: uuid.UUID
    rule_key: str
    rule_title: str
    result: str
    title: str | None
    confidence: str
    missing_facts: list[str]


@dataclass
class MatchDecision:
    status: MatchStatus
    confidence: Confidence
    criteria: list[dict[str, Any]] = field(default_factory=list)
    missing_facts: list[str] = field(default_factory=list)


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


def decide(rule_set: dict[str, Any], findings: Sequence[FindingLike]) -> MatchDecision | None:
    """``rule_set`` is the assessment's stored entry for the program's rule set (key, scope,
    missing facts); ``findings`` are that rule set's findings. ``None`` when there is
    nothing to decide on (in scope but no criterion in force)."""
    scope = rule_set.get("scope")
    if scope in ("OUT_OF_SCOPE", "NEEDS_INFORMATION"):
        missing = list(rule_set.get("missing_facts") or [])
        return MatchDecision(
            status=MatchStatus.NOT_ELIGIBLE
            if scope == "OUT_OF_SCOPE"
            else MatchStatus.NEEDS_INFORMATION,
            confidence=Confidence.LIKELY if scope == "OUT_OF_SCOPE" else Confidence.UNKNOWN,
            criteria=[
                {
                    "kind": "WHO_CAN_APPLY",
                    "title": "Who can apply",
                    "result": RuleResult.NO_MATCH
                    if scope == "OUT_OF_SCOPE"
                    else RuleResult.UNKNOWN,
                    "missing_facts": missing,
                }
            ],
            missing_facts=missing,
        )
    if not findings:
        return None
    criteria = [
        {
            "kind": "CRITERION",
            "finding_id": str(f.id),
            "rule_key": f.rule_key,
            "title": f.rule_title,
            "result": f.result,
            "outcome": f.title,
            "missing_facts": list(f.missing_facts),
        }
        for f in findings
    ]
    results = {f.result for f in findings}
    missing = _unique(m for f in findings for m in f.missing_facts)
    if RuleResult.NO_MATCH in results:
        unmet = [f for f in findings if f.result == RuleResult.NO_MATCH]
        return MatchDecision(
            MatchStatus.NOT_ELIGIBLE,
            lowest(Confidence(f.confidence) for f in unmet),
            criteria,
            missing,
        )
    if RuleResult.UNKNOWN in results:
        return MatchDecision(MatchStatus.NEEDS_INFORMATION, Confidence.UNKNOWN, criteria, missing)
    confidence = lowest(Confidence(f.confidence) for f in findings)
    status = MatchStatus.STRONG_MATCH if confidence in STRONG else MatchStatus.POSSIBLE_MATCH
    return MatchDecision(status, confidence, criteria, [])


# --- Rounds ----------------------------------------------------------------------------


class RoundLike(Protocol):
    id: uuid.UUID
    status: str
    opens_on: date | None
    closes_on: date | None


@dataclass(frozen=True)
class RoundState:
    state: RoundStatus  # what the dates make of the recorded status
    days_to_close: int | None  # open rounds with a closing date
    closing_soon: bool
    # The recorded status no longer fits the dates (an upcoming round whose opening date
    # has passed): staff need to check the source.
    check_source: bool


def round_state(r: RoundLike, on: date) -> RoundState:
    status = RoundStatus(r.status)
    check = False
    if status == RoundStatus.OPEN:
        if r.closes_on is not None and r.closes_on < on:
            status = RoundStatus.CLOSED
        elif r.opens_on is not None and r.opens_on > on:
            status = RoundStatus.UPCOMING
    elif status == RoundStatus.UPCOMING and r.opens_on is not None and r.opens_on <= on:
        check = True
    days = (r.closes_on - on).days if status == RoundStatus.OPEN and r.closes_on else None
    return RoundState(
        state=status,
        days_to_close=days,
        closing_soon=days is not None and days <= CLOSING_SOON_DAYS,
        check_source=check,
    )


_PREFERENCE = {
    RoundStatus.OPEN: 0,
    RoundStatus.UPCOMING: 1,
    RoundStatus.PAUSED: 2,
    RoundStatus.CLOSED: 3,
}


def current_round[R: RoundLike](rounds: Sequence[R], on: date) -> R | None:
    """The round to show first: open, else upcoming (soonest), else paused, else the one
    that closed last."""
    if not rounds:
        return None

    def key(r: R) -> tuple[int, int]:
        state = round_state(r, on).state
        if state == RoundStatus.UPCOMING:
            when = (r.opens_on or date.max).toordinal()
        else:
            when = -(r.closes_on or r.opens_on or date.min).toordinal()
        return _PREFERENCE[state], when

    return min(rounds, key=key)
