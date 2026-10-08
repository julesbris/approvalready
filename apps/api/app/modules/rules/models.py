"""Versioned regulatory rules: rule set → rule → rule version (+ outcomes, cited sources,
test cases and the facts it reads).

Global reference data authored by staff. A rule version is a draft until someone with
``rule.publish`` publishes it through the publish gate (``service.publish_checks``); from
then on it and everything attached to it are immutable (database triggers, migration
0004). Changing a published rule means a new version. At most one version of a rule is
published at a time; publishing retires the previous one, which stays readable so earlier
assessments keep pointing at exactly what they evaluated.
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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    CreatedByMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
)
from app.modules.projects.models import Vertical
from app.modules.regulatory.models import JURISDICTION_PATTERN

KEY_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$"


class Confidence(StrEnum):
    """How far a finding can be relied on, highest first (see ``rules/engine.py``)."""

    VERIFIED = "VERIFIED"
    LIKELY = "LIKELY"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    UNKNOWN = "UNKNOWN"


class RuleVersionStatus(StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class RuleResult(StrEnum):
    """A rule's condition evaluated against the facts (three-valued)."""

    MATCH = "MATCH"
    NO_MATCH = "NO_MATCH"
    UNKNOWN = "UNKNOWN"


class OutcomeType(StrEnum):
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVAL_LIKELY = "APPROVAL_LIKELY"
    NOT_REQUIRED = "NOT_REQUIRED"
    EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"
    PROFESSIONAL_REQUIRED = "PROFESSIONAL_REQUIRED"
    REFERRAL_CATEGORY = "REFERRAL_CATEGORY"
    CROSS_SELL = "CROSS_SELL"
    WARNING = "WARNING"
    INFO = "INFO"


class SourceRelationship(StrEnum):
    BASIS = "BASIS"  # the provision the rule encodes
    SUPPORTING = "SUPPORTING"
    EXCEPTION = "EXCEPTION"  # a carve-out the rule accounts for


class RuleSet(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, Base):
    __tablename__ = "rule_set"
    __table_args__ = (
        enum_check("vertical", Vertical),
        CheckConstraint(f"key ~ '{KEY_PATTERN}'", name="key_format"),
        CheckConstraint(f"jurisdiction ~ '{JURISDICTION_PATTERN}'", name="jurisdiction_format"),
    )

    key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    vertical: Mapped[str] = mapped_column(Text, nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000))
    # Condition AST deciding whether the rule set applies to a project at all (e.g. the
    # property is in this LGA). FALSE: out of scope. UNKNOWN: more information needed.
    # None: applies to every project of the vertical.
    applies_when: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Rule(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, Base):
    __tablename__ = "rule"
    __table_args__ = (
        UniqueConstraint("rule_set_id", "key"),
        CheckConstraint(f"key ~ '{KEY_PATTERN}'", name="key_format"),
    )

    rule_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule_set.id", ondelete="RESTRICT"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)


class RuleVersion(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, Base):
    __tablename__ = "rule_version"
    __table_args__ = (
        UniqueConstraint("rule_id", "version"),
        enum_check("status", RuleVersionStatus),
        enum_check("max_confidence", Confidence),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "(status = 'DRAFT') = (published_at IS NULL)", name="published_at_when_published"
        ),
        CheckConstraint(
            "status = 'DRAFT' OR (effective_from IS NOT NULL AND content_hash IS NOT NULL)",
            name="published_is_complete",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from",
            name="effective_range",
        ),
        Index(
            "uq_rule_version_published",
            "rule_id",
            unique=True,
            postgresql_where=text("status = 'PUBLISHED'"),
        ),
    )

    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=RuleVersionStatus.DRAFT,
        server_default=RuleVersionStatus.DRAFT,
    )
    # Condition AST (app/modules/conditions), validated before it is stored.
    condition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)  # exclusive
    # Cap on the confidence of this rule's findings, e.g. LIKELY for a rule that simplifies
    # its source.
    max_confidence: Mapped[str] = mapped_column(
        Text, nullable=False, default=Confidence.VERIFIED, server_default=Confidence.VERIFIED
    )
    notes: Mapped[str | None] = mapped_column(String(2000))  # for authors and reviewers
    content_hash: Mapped[bytes | None] = mapped_column(LargeBinary)  # set when published
    published_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RuleOutcome(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """What a result means for the customer. At most one outcome per result."""

    __tablename__ = "rule_outcome"
    __table_args__ = (
        UniqueConstraint("rule_version_id", "on_result"),
        enum_check("on_result", RuleResult),
        enum_check("outcome_type", OutcomeType),
    )

    rule_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule_version.id", ondelete="CASCADE"), nullable=False
    )
    on_result: Mapped[str] = mapped_column(Text, nullable=False)
    outcome_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[str | None] = mapped_column(String(2000))


class RuleSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rule_source"
    __table_args__ = (
        UniqueConstraint("rule_version_id", "source_reference_id"),
        enum_check("relationship", SourceRelationship),
        Index("ix_rule_source_source_reference_id", "source_reference_id"),
    )

    rule_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule_version.id", ondelete="CASCADE"), nullable=False
    )
    source_reference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_reference.id", ondelete="RESTRICT"), nullable=False
    )
    relationship: Mapped[str] = mapped_column(Text, nullable=False)


class RuleTestCase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Facts and the result they must produce. Every case must pass before publishing."""

    __tablename__ = "rule_test_case"
    __table_args__ = (
        UniqueConstraint("rule_version_id", "name"),
        enum_check("expected_result", RuleResult),
    )

    rule_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule_version.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    expected_result: Mapped[str] = mapped_column(Text, nullable=False)


class RuleFactDependency(Base):
    """Fact paths a version's condition reads (answers "which rules use this question?")."""

    __tablename__ = "rule_fact_dependency"
    __table_args__ = (Index("ix_rule_fact_dependency_fact_path", "fact_path"),)

    rule_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rule_version.id", ondelete="CASCADE"),
        primary_key=True,
    )
    fact_path: Mapped[str] = mapped_column(String(120), primary_key=True)
