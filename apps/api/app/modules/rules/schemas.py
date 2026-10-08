from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.modules.projects.models import Vertical
from app.modules.regulatory.models import JURISDICTION_PATTERN
from app.modules.rules.models import (
    KEY_PATTERN,
    Confidence,
    OutcomeType,
    RuleResult,
    RuleVersionStatus,
    SourceRelationship,
)

Key = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100, pattern=KEY_PATTERN)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Notes = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Jurisdiction = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=JURISDICTION_PATTERN)
]

MAX_OUTCOMES = 3
MAX_SOURCES = 20
MAX_TEST_CASES = 50


def _blank_to_none(value: object) -> object:
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Rule sets -------------------------------------------------------------------------


class RuleSetCreate(_In):
    key: Key
    vertical: Vertical
    jurisdiction: Jurisdiction
    title: Title
    description: Notes | None = None
    applies_when: dict[str, Any] | None = Field(
        default=None, description="Condition AST; omit when the rule set applies everywhere."
    )

    _blank = field_validator("description", mode="before")(_blank_to_none)


class RuleSetUpdate(_In):
    jurisdiction: Jurisdiction | None = None
    title: Title | None = None
    description: Notes | None = None
    applies_when: dict[str, Any] | None = None

    _blank = field_validator("description", mode="before")(_blank_to_none)


class RuleSummary(BaseModel):
    id: uuid.UUID
    key: str
    title: str
    published_version: int | None
    published_version_id: uuid.UUID | None
    draft_version_id: uuid.UUID | None
    latest_version: int


class RuleSetOut(BaseModel):
    id: uuid.UUID
    key: str
    vertical: Vertical
    jurisdiction: str
    title: str
    description: str | None
    applies_when: dict[str, Any] | None
    rules: list[RuleSummary]
    created_at: datetime
    updated_at: datetime


# --- Rules and versions ----------------------------------------------------------------


class RuleCreate(_In):
    key: Key
    title: Title
    condition: dict[str, Any] = Field(description="Condition AST for the first draft.")


class RuleUpdate(_In):
    title: Title


class RuleVersionSummary(BaseModel):
    id: uuid.UUID
    version: int
    status: RuleVersionStatus
    effective_from: date | None
    effective_to: date | None
    published_at: datetime | None
    created_at: datetime


class RuleOut(BaseModel):
    id: uuid.UUID
    rule_set_id: uuid.UUID
    rule_set_key: str
    key: str
    title: str
    versions: list[RuleVersionSummary]


class OutcomeIn(_In):
    on_result: RuleResult
    outcome_type: OutcomeType
    title: Title
    detail: Notes | None = None

    _blank = field_validator("detail", mode="before")(_blank_to_none)


class RuleSourceIn(_In):
    source_reference_id: uuid.UUID
    relationship: SourceRelationship = SourceRelationship.BASIS


class TestCaseIn(_In):
    name: Title
    facts: dict[str, Any] = Field(
        description="Facts by fact path. Decimals may be written as {'$decimal': '1.5'}."
    )
    expected_result: RuleResult


class RuleVersionContent(_In):
    """The whole editable content of a draft (replaces what is stored)."""

    condition: dict[str, Any]
    effective_from: date | None = None
    effective_to: date | None = None
    max_confidence: Confidence = Confidence.VERIFIED
    notes: Notes | None = None
    outcomes: list[OutcomeIn] = Field(default_factory=list, max_length=MAX_OUTCOMES)
    sources: list[RuleSourceIn] = Field(default_factory=list, max_length=MAX_SOURCES)
    test_cases: list[TestCaseIn] = Field(default_factory=list, max_length=MAX_TEST_CASES)

    _blank = field_validator("notes", mode="before")(_blank_to_none)


class OutcomeOut(BaseModel):
    on_result: RuleResult
    outcome_type: OutcomeType
    title: str
    detail: str | None


class RuleSourceOut(BaseModel):
    source_reference_id: uuid.UUID
    relationship: SourceRelationship
    citation: str
    url: str
    verification_status: str


class TestCaseOut(BaseModel):
    name: str
    facts: dict[str, Any]
    expected_result: RuleResult


class RuleVersionOut(BaseModel):
    id: uuid.UUID
    rule_id: uuid.UUID
    rule_key: str
    rule_title: str
    rule_set_id: uuid.UUID
    rule_set_key: str
    vertical: Vertical
    version: int
    status: RuleVersionStatus
    condition: dict[str, Any]
    effective_from: date | None
    effective_to: date | None
    max_confidence: Confidence
    notes: str | None
    outcomes: list[OutcomeOut]
    sources: list[RuleSourceOut]
    test_cases: list[TestCaseOut]
    fact_paths: list[str]
    content_hash: str | None
    created_by: uuid.UUID | None
    published_by: uuid.UUID | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


# --- Publish gate and evaluation -------------------------------------------------------


class TestCaseResultOut(BaseModel):
    name: str
    expected: RuleResult
    actual: RuleResult
    passed: bool
    trace: dict[str, Any]


class PublishCheck(BaseModel):
    key: str
    passed: bool
    message: str


class PublishChecksOut(BaseModel):
    ready: bool = Field(description="Every check passed: the version can be published.")
    checks: list[PublishCheck]
    warnings: list[str] = Field(description="Allowed, but worth knowing before publishing.")
    test_results: list[TestCaseResultOut]


class EvaluateIn(_In):
    facts: dict[str, Any]
    on: date | None = Field(default=None, description="Assessment date; defaults to today.")


class EvaluateOut(BaseModel):
    result: RuleResult
    outcome: OutcomeOut | None
    confidence: Confidence
    confidence_reasons: list[str]
    missing_facts: list[str]
    trace: dict[str, Any]
