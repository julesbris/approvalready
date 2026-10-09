"""Documents: uploads (with malware scanning), evidence, report templates and generated
reports.

Binaries live in object storage (``storage.py``); these rows hold what we know about them.
An upload is unusable until its scan says ``CLEAN``: it cannot be downloaded, attached as
evidence or used as an answer before then.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

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
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    CreatedByMixin,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    tenant_fk,
)


class ScanStatus(StrEnum):
    PENDING = "PENDING"  # stored, waiting for the scanner
    CLEAN = "CLEAN"
    INFECTED = "INFECTED"  # moved to quarantine; never served
    ERROR = "ERROR"  # the scanner could not give an answer after retrying


class Classification(StrEnum):
    PRIVATE = "PRIVATE"  # only the organisation's members
    SHARED_WITH_REVIEWER = "SHARED_WITH_REVIEWER"  # Milestone 7
    RELEASED_TO_PARTNER = "RELEASED_TO_PARTNER"  # Milestone 15


class EvidenceStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"  # set by a professional reviewer (Milestone 7)
    REJECTED = "REJECTED"


class TemplateStatus(StrEnum):
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class TemplateEngine(StrEnum):
    JINJA_HTML = "JINJA_HTML"


class OutputFormat(StrEnum):
    PDF = "PDF"
    DOCX = "DOCX"
    HTML = "HTML"


class GenerationStatus(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    FAILED = "FAILED"


class ReviewStatus(StrEnum):
    NOT_REVIEWED = "NOT_REVIEWED"  # professional review arrives in Milestone 7


class UploadedDocument(
    UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, SoftDeleteMixin, TenantMixin, Base
):
    __tablename__ = "uploaded_document"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        UniqueConstraint("storage_key"),
        tenant_fk("project_id", "project", ondelete="CASCADE"),
        enum_check("scan_status", ScanStatus),
        enum_check("classification", Classification),
        CheckConstraint("octet_length(sha256) = 32", name="sha256_length"),
        CheckConstraint("size_bytes > 0", name="size_positive"),
        Index("ix_uploaded_document_project_id", "project_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(300), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(200), nullable=False)
    extension: Mapped[str] = mapped_column(String(10), nullable=False)
    declared_mime: Mapped[str] = mapped_column(String(200), nullable=False)
    detected_mime: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    scan_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=ScanStatus.PENDING
    )
    scan_engine: Mapped[str | None] = mapped_column(String(40))
    scan_signature: Mapped[str | None] = mapped_column(String(200))
    scan_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    classification: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=Classification.PRIVATE
    )


class Evidence(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, TenantMixin, Base):
    """An uploaded document offered to meet an evidence requirement of an assessment."""

    __tablename__ = "evidence"
    __table_args__ = (
        tenant_fk("project_id", "project", ondelete="CASCADE"),
        tenant_fk("evidence_requirement_id", "evidence_requirement", ondelete="CASCADE"),
        tenant_fk("uploaded_document_id", "uploaded_document", ondelete="CASCADE"),
        enum_check("status", EvidenceStatus),
        UniqueConstraint("evidence_requirement_id", "uploaded_document_id"),
        Index("ix_evidence_project_id", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    evidence_requirement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    uploaded_document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=EvidenceStatus.SUBMITTED
    )
    note: Mapped[str | None] = mapped_column(String(500))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A kind of generated document. Platform reference data, synced from the reviewed
    files in ``templates/`` like questionnaire definitions."""

    __tablename__ = "document_template"
    __table_args__ = (
        UniqueConstraint("key"),
        CheckConstraint("key ~ '^[A-Z][A-Z0-9_]{1,59}$'", name="key_format"),
    )

    key: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    vertical: Mapped[str] = mapped_column(Text, nullable=False)


class DocumentTemplateVersion(UUIDPrimaryKeyMixin, Base):
    """Immutable once stored (trigger): a changed template file becomes a new version and
    every generated document records the exact version it came from."""

    __tablename__ = "document_template_version"
    __table_args__ = (
        UniqueConstraint("template_id", "version"),
        enum_check("status", TemplateStatus),
        enum_check("engine", TemplateEngine),
        CheckConstraint("octet_length(content_hash) = 32", name="content_hash_sha256"),
        CheckConstraint(
            "output_formats <@ ARRAY['PDF', 'DOCX', 'HTML']::text[] "
            "AND cardinality(output_formats) > 0",
            name="output_formats_valid",
        ),
        Index(
            "uq_document_template_version_published",
            "template_id",
            unique=True,
            postgresql_where=text("status = 'PUBLISHED'"),
        ),
    )

    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_template.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    engine: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    output_formats: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class GeneratedDocument(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, TenantMixin, Base):
    __tablename__ = "generated_document"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        tenant_fk("project_id", "project", ondelete="CASCADE"),
        tenant_fk("assessment_id", "assessment", ondelete="CASCADE"),
        enum_check("format", OutputFormat),
        enum_check("status", GenerationStatus),
        enum_check("review_status", ReviewStatus),
        CheckConstraint(
            "status <> 'READY' OR (storage_key IS NOT NULL AND sha256 IS NOT NULL "
            "AND size_bytes IS NOT NULL)",
            name="ready_has_content",
        ),
        Index("ix_generated_document_project_id", "project_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    template_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_template_version.id", ondelete="RESTRICT"),
        nullable=False,
    )
    format: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=GenerationStatus.PENDING
    )
    review_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=ReviewStatus.NOT_REVIEWED
    )
    filename: Mapped[str] = mapped_column(String(200), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(300))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[bytes | None] = mapped_column(LargeBinary)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error: Mapped[str | None] = mapped_column(String(500))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
