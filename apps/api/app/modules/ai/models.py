"""AI drafting (Milestone 12): reviewed prompts, jobs and the provider call log.

* ``prompt_version``: platform data. Prompts are reviewed files in ``prompts/``, published by
  the migrate step like report templates; a changed file is a new immutable version. The
  application role can only read them, so no request can change what the model is told.
* ``ai_job`` (tenant): one request for a draft, the IDs of what it was built from, the
  validated output or why it was rejected.
* ``ai_provider_log`` (tenant, append-only): every call to a provider with its model,
  tokens, cost, latency and outcome. It stores no prompt or output text.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
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


class AITask(StrEnum):
    # A plain-language explanation of an assessment's findings.
    ASSESSMENT_EXPLANATION = "ASSESSMENT_EXPLANATION"
    # Notes towards a grant application, from the applicant's own answers.
    GRANT_DRAFT = "GRANT_DRAFT"


class PromptStatus(StrEnum):
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class JobStatus(StrEnum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    # The provider answered but the output failed validation or the post-check.
    REJECTED = "REJECTED"
    # The provider could not be reached, declined, or AI is switched off.
    FAILED = "FAILED"


class CallStatus(StrEnum):
    OK = "OK"
    ERROR = "ERROR"
    REFUSED = "REFUSED"


class PromptVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "prompt_version"
    __table_args__ = (
        UniqueConstraint("task", "version"),
        enum_check("task", AITask),
        enum_check("status", PromptStatus),
        CheckConstraint("octet_length(content_hash) = 32", name="content_hash_sha256"),
        Index(
            "uq_prompt_version_one_published",
            "task",
            unique=True,
            postgresql_where=text("status = 'PUBLISHED'"),
        ),
    )

    task: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    user_template: Mapped[str] = mapped_column(Text, nullable=False)
    output_schema_name: Mapped[str] = mapped_column(String(60), nullable=False)
    output_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class AIJob(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, TenantMixin, Base):
    __tablename__ = "ai_job"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        tenant_fk("project_id", "project", ondelete="CASCADE"),
        tenant_fk("assessment_id", "assessment", ondelete="CASCADE"),
        enum_check("task", AITask),
        enum_check("status", JobStatus),
        CheckConstraint("octet_length(input_hash) = 32", name="input_hash_sha256"),
        CheckConstraint("status <> 'SUCCEEDED' OR output IS NOT NULL", name="succeeded_has_output"),
        Index("ix_ai_job_assessment_id", "assessment_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    # Grant drafts: the program the draft is for. Kept as an id (platform row).
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    prompt_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompt_version.id", ondelete="RESTRICT"), nullable=False
    )
    # What the input was built from, as IDs only (finding ids, fact keys, program id).
    input_refs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # SHA-256 of the canonical input and prompt version: an identical request reuses the job.
    input_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=JobStatus.PENDING)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    validation_errors: Mapped[list[str] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(String(500))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIProviderLog(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "ai_provider_log"
    __table_args__ = (
        tenant_fk("ai_job_id", "ai_job", ondelete="CASCADE"),
        enum_check("task", AITask),
        enum_check("status", CallStatus),
        Index("ix_ai_provider_log_ai_job_id", "ai_job_id"),
        Index("ix_ai_provider_log_created_at", "created_at"),
    )

    ai_job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompt_version.id", ondelete="RESTRICT"), nullable=False
    )
    schema_name: Mapped[str] = mapped_column(String(60), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    request_tokens: Mapped[int | None] = mapped_column(Integer)
    response_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_micros: Mapped[int | None] = mapped_column(BigInteger)  # millionths of a US dollar
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
