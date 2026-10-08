"""Assessment runs and their findings (tenant-owned, append-only).

An assessment evaluates every published rule of the project's vertical against the facts
from a submitted questionnaire, on one date. It stores everything needed to explain and
reproduce the result: the facts (and their hash), the exact rule versions, each rule's
leaf-by-leaf trace, and the state of every cited source at the time. Re-running creates a
new assessment; findings are never edited (reviewer overrides arrive in Milestone 7 as
separate rows).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, UUIDPrimaryKeyMixin, enum_check, tenant_fk
from app.modules.rules.models import Confidence, OutcomeType, RuleResult


class AssessmentStatus(StrEnum):
    COMPLETED = "COMPLETED"
    # No reviewed rules apply yet: said plainly instead of implying "nothing required".
    NO_APPLICABLE_RULES = "NO_APPLICABLE_RULES"


class Assessment(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "assessment"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        tenant_fk("project_id", "project", ondelete="CASCADE"),
        tenant_fk("submission_id", "questionnaire_submission", ondelete="CASCADE"),
        enum_check("status", AssessmentStatus),
        enum_check("overall_confidence", Confidence),
        CheckConstraint("octet_length(facts_hash) = 32", name="facts_hash_sha256"),
        Index("ix_assessment_project_id", "project_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    submission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    assessed_on: Mapped[date] = mapped_column(Date, nullable=False)
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    # Encoded facts (rules/engine.py ``encode_facts``) and SHA-256 of their canonical JSON.
    facts_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    facts_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    overall_confidence: Mapped[str] = mapped_column(Text, nullable=False)
    # Each rule set considered: key, title, scope result, applies_when, missing facts.
    rule_sets: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class AssessmentFinding(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "assessment_finding"
    __table_args__ = (
        UniqueConstraint("assessment_id", "rule_version_id"),
        tenant_fk("assessment_id", "assessment", ondelete="CASCADE"),
        enum_check("result", RuleResult),
        enum_check("outcome_type", OutcomeType, nullable=True),
        enum_check("confidence", Confidence),
        Index("ix_assessment_finding_rule_version_id", "rule_version_id"),
    )

    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule_set.id", ondelete="RESTRICT"), nullable=False
    )
    rule_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule_version.id", ondelete="RESTRICT"), nullable=False
    )
    rule_key: Mapped[str] = mapped_column(String(100), nullable=False)
    rule_title: Mapped[str] = mapped_column(String(200), nullable=False)
    result: Mapped[str] = mapped_column(Text, nullable=False)
    # The rule's outcome for this result, copied so the finding reads the same forever.
    outcome_type: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(200))
    detail: Mapped[str | None] = mapped_column(String(2000))
    confidence: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    trace: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    missing_facts: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    # Each cited source reference as it stood on the assessment date.
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
