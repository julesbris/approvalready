"""Data-driven questionnaires.

Definitions (questionnaire → version → question versions → options) are global reference
data, versioned and immutable once published (database triggers, migration 0003). A
customer's answers live in a tenant-owned submission pinned to one questionnaire version,
so publishing a new version never changes what an existing submission asked.

A question's ``key`` is stable across versions and doubles as the fact path the rules
engine reads (e.g. ``planning.development_type``).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    tenant_fk,
)
from app.modules.projects.models import Vertical


class VersionStatus(StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class QuestionType(StrEnum):
    TEXT = "TEXT"
    TEXTAREA = "TEXTAREA"
    NUMBER = "NUMBER"  # integer
    DECIMAL = "DECIMAL"  # exact decimal, stored as a string
    CURRENCY = "CURRENCY"  # whole cents (AUD), stored as an integer
    BOOLEAN = "BOOLEAN"
    SELECT = "SELECT"
    MULTISELECT = "MULTISELECT"
    DATE = "DATE"  # ISO YYYY-MM-DD
    ADDRESS = "ADDRESS"  # Australian address object
    FILE = "FILE"  # uploaded document ids (upload pipeline arrives in Milestone 6)
    OBJECT = "OBJECT"  # small fixed set of typed fields


class SubmissionStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"


KEY_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$"


class Questionnaire(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "questionnaire"
    __table_args__ = (
        enum_check("vertical", Vertical),
        CheckConstraint(f"key ~ '{KEY_PATTERN}'", name="key_format"),
    )

    key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    vertical: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)


class QuestionnaireVersion(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, Base):
    __tablename__ = "questionnaire_version"
    __table_args__ = (
        UniqueConstraint("questionnaire_id", "version"),
        enum_check("status", VersionStatus),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "(status = 'DRAFT') = (published_at IS NULL)", name="published_at_when_published"
        ),
        # At most one current (published) version per questionnaire.
        Index(
            "uq_questionnaire_version_published",
            "questionnaire_id",
            unique=True,
            postgresql_where=text("status = 'PUBLISHED'"),
        ),
    )

    questionnaire_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("questionnaire.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default=VersionStatus.DRAFT, server_default=VersionStatus.DRAFT
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000))
    # SHA-256 of the canonical definition JSON: re-loading an unchanged definition is a no-op.
    content_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Question(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Stable identity of a question across versions and questionnaires."""

    __tablename__ = "question"
    __table_args__ = (CheckConstraint(f"key ~ '{KEY_PATTERN}'", name="key_format"),)

    key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)


class QuestionVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "question_version"
    __table_args__ = (
        UniqueConstraint("questionnaire_version_id", "question_id"),
        UniqueConstraint("questionnaire_version_id", "ordinal"),
        enum_check("type", QuestionType),
    )

    questionnaire_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questionnaire_version.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("question.id", ondelete="RESTRICT"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    section: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    help_text: Mapped[str | None] = mapped_column(String(1000))
    required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    validation: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    visible_when: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class QuestionOption(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "question_option"
    __table_args__ = (
        UniqueConstraint("question_version_id", "value"),
        UniqueConstraint("question_version_id", "ordinal"),
    )

    question_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("question_version.id", ondelete="CASCADE"), nullable=False
    )
    value: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)


class QuestionnaireSubmission(
    UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, TenantMixin, Base
):
    __tablename__ = "questionnaire_submission"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        tenant_fk("project_id", "project", ondelete="CASCADE"),
        enum_check("status", SubmissionStatus),
        CheckConstraint(
            "(status = 'SUBMITTED') = (submitted_at IS NOT NULL)",
            name="submitted_at_when_submitted",
        ),
        Index("ix_questionnaire_submission_project_id", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    questionnaire_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questionnaire_version.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=SubmissionStatus.IN_PROGRESS,
        server_default=SubmissionStatus.IN_PROGRESS,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )


class QuestionResponse(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "question_response"
    __table_args__ = (
        UniqueConstraint("submission_id", "question_version_id"),
        tenant_fk("submission_id", "questionnaire_submission", ondelete="CASCADE"),
    )

    submission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    question_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("question_version.id", ondelete="RESTRICT"), nullable=False
    )
    # Normalised by the engine for the question's type (see questionnaires/engine.py).
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    answered_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
