from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.modules.assessments.models import AssessmentStatus
from app.modules.rules.models import Confidence, OutcomeType, RuleResult


class AssessmentSummary(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    submission_id: uuid.UUID
    assessed_on: date
    status: AssessmentStatus
    overall_confidence: Confidence
    findings: int
    created_at: datetime


class RuleSetScopeOut(BaseModel):
    rule_set_id: uuid.UUID
    key: str
    title: str
    scope: str = Field(description="IN_SCOPE, OUT_OF_SCOPE or NEEDS_INFORMATION.")
    missing_facts: list[str]
    not_in_force: list[str] = Field(description="Rules with no version in force that day.")


class FindingSourceOut(BaseModel):
    reference_id: uuid.UUID
    relationship: str
    verification_status: str
    citation: str
    document_title: str
    organisation_name: str
    url: str
    section: str | None
    clause: str | None
    page: str | None
    in_force: bool


class FindingOut(BaseModel):
    id: uuid.UUID
    rule_set_id: uuid.UUID
    rule_version_id: uuid.UUID
    rule_key: str
    rule_title: str
    result: RuleResult
    outcome_type: OutcomeType | None
    title: str | None
    detail: str | None
    confidence: Confidence
    confidence_reasons: list[str]
    missing_facts: list[str]
    trace: dict[str, Any] = Field(description="Leaf-by-leaf evaluation of the rule.")
    sources: list[FindingSourceOut]


class AssessmentOut(AssessmentSummary):
    engine_version: str
    facts_hash: str
    facts: dict[str, Any] = Field(description="The facts assessed (encoded, see rules engine).")
    fact_labels: dict[str, str] = Field(
        description="Question labels for the facts that appear in this assessment."
    )
    rule_sets: list[RuleSetScopeOut]
    finding_list: list[FindingOut]
