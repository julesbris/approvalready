from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.modules.assessments.models import AssessmentStatus
from app.modules.grants.schemas import GrantMatchOut
from app.modules.rules.models import Confidence, OutcomeType, RuleResult
from app.modules.rules.payload import Certainty


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
    limitations: list[str] = Field(
        default_factory=list, description="What the rule set does not check."
    )


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
    referral_categories: list[str] = Field(description="Kinds of professional who can help.")


class ApprovalRequirementOut(BaseModel):
    id: uuid.UUID
    finding_id: uuid.UUID
    kind: str
    title: str
    authority: str | None
    pathway: str | None
    certainty: Certainty
    confidence: Confidence


class EvidenceRequirementOut(BaseModel):
    id: uuid.UUID
    finding_id: uuid.UUID
    kind: str
    title: str
    detail: str | None
    confidence: Confidence


class ApprovalMapEntryOut(BaseModel):
    kind: str
    title: str
    certainty: Certainty = Field(description="The strongest certainty any finding gave it.")
    confidence: Confidence
    authority: str | None
    pathway: str | None
    requirement_ids: list[uuid.UUID]
    finding_ids: list[uuid.UUID]


class ReferralCategoryOut(BaseModel):
    key: str
    label: str = Field(description="The marketplace category's name.")
    description: str | None
    finding_ids: list[uuid.UUID]


class AssessmentOut(AssessmentSummary):
    engine_version: str
    facts_hash: str
    facts: dict[str, Any] = Field(description="The facts assessed (encoded, see rules engine).")
    fact_labels: dict[str, str] = Field(
        description="Question labels for the facts that appear in this assessment."
    )
    rule_sets: list[RuleSetScopeOut]
    finding_list: list[FindingOut]
    approval_requirements: list[ApprovalRequirementOut]
    evidence_requirements: list[EvidenceRequirementOut]
    approval_map: list[ApprovalMapEntryOut] = Field(
        description="Each kind of approval once, strongest certainty first (Required, Likely "
        "required, May apply, Not identified)."
    )
    referral_categories: list[ReferralCategoryOut] = Field(
        description="Who can help, from every finding that names a kind of professional."
    )
    limitations: list[str] = Field(
        description="What the applicable rule sets do not check, without repeats."
    )
    grant_matches: list[GrantMatchOut] = Field(
        default_factory=list,
        description="Grant projects: each grant program's match, best first, with its rounds "
        "as they stand today.",
    )
