"""Regulatory sources and provenance: who publishes a source, the document, captured snapshots
of its content, and the atomic citations (references) that rules link to.

Global reference data maintained by ApprovalReady staff, not tenant-owned. Staff record each
source with its provenance (URL, version, effective dates, section/clause/page and the
extracted text). A snapshot is either pasted by staff or read from the document's official
address by the app (Milestone 24, ``source_check``); the app never decides what a source
means, it only notices when the published text changes.

A reference is only trusted once a person with ``source.verify`` has checked it against a
captured snapshot. ``source_review_event`` is the append-only history of those decisions.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    CreatedByMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
)

# Commonwealth, a state or territory, or a local government area (``LGA:QLD_CAIRNS``).
JURISDICTION_PATTERN = r"^(CTH|QLD|NSW|VIC|SA|WA|TAS|NT|ACT|LGA:[A-Z][A-Z0-9_]{1,59})$"
MAX_SNAPSHOT_CHARS = 1_000_000


class SourceOrganisationKind(StrEnum):
    LEGISLATURE = "LEGISLATURE"
    COUNCIL = "COUNCIL"
    STATE_AGENCY = "STATE_AGENCY"
    CTH_AGENCY = "CTH_AGENCY"
    REGULATOR = "REGULATOR"
    GRANT_BODY = "GRANT_BODY"


class SourceType(StrEnum):
    LEGISLATION = "LEGISLATION"
    REGULATION = "REGULATION"
    PLANNING_SCHEME = "PLANNING_SCHEME"
    POLICY = "POLICY"
    GUIDELINE = "GUIDELINE"
    FORM = "FORM"
    FEE_SCHEDULE = "FEE_SCHEDULE"
    WEBPAGE = "WEBPAGE"
    GRANT_GUIDELINES = "GRANT_GUIDELINES"


class VerificationStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"


class ReviewAction(StrEnum):
    CREATED = "CREATED"
    EDITED = "EDITED"  # the citation changed, so any earlier verification no longer holds
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"
    REOPENED = "REOPENED"


class CaptureMethod(StrEnum):
    MANUAL = "MANUAL"  # pasted by staff
    FETCHED = "FETCHED"  # read from the official address by the app


class CheckTrigger(StrEnum):
    SCHEDULED = "SCHEDULED"  # the weekly check
    MANUAL = "MANUAL"  # a staff member pressed "Check now"


class CheckOutcome(StrEnum):
    # First reading by the app (the latest snapshot, if any, was pasted by staff, so a
    # difference from it is not evidence of a change).
    SAVED = "SAVED"
    CHANGED = "CHANGED"  # the text differs from the latest snapshot: a new snapshot
    UNCHANGED = "UNCHANGED"
    # A file whose text the app doesn't read (a PDF): only whether its bytes changed.
    FILE_SEEN = "FILE_SEEN"  # first reading of the file
    FILE_CHANGED = "FILE_CHANGED"
    FILE_UNCHANGED = "FILE_UNCHANGED"
    FAILED = "FAILED"  # not reachable, refused, too large or no readable text


def _jurisdiction_check() -> CheckConstraint:
    return CheckConstraint(f"jurisdiction ~ '{JURISDICTION_PATTERN}'", name="jurisdiction_format")


class SourceOrganisation(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, Base):
    __tablename__ = "source_organisation"
    __table_args__ = (enum_check("kind", SourceOrganisationKind), _jurisdiction_check())

    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(64), nullable=False)
    website: Mapped[str | None] = mapped_column(String(500))


class SourceDocument(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, Base):
    __tablename__ = "source_document"
    __table_args__ = (
        enum_check("source_type", SourceType),
        _jurisdiction_check(),
        CheckConstraint("url ~ '^https?://'", name="url_format"),
        CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from",
            name="effective_range",
        ),
        CheckConstraint(
            "supersedes_id IS NULL OR supersedes_id <> id", name="not_self_superseding"
        ),
        Index("ix_source_document_source_organisation_id", "source_organisation_id"),
    )

    source_organisation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_organisation.id", ondelete="RESTRICT"),
        nullable=False,
    )
    jurisdiction: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    version_label: Mapped[str | None] = mapped_column(String(100))
    # In force from/to (``effective_to`` exclusive). Findings citing a document outside this
    # window on the assessment date cannot be verified.
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    # Licence or attribution terms for reproducing extracts (e.g. "CC BY 4.0").
    licence: Mapped[str | None] = mapped_column(String(200))
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_document.id", ondelete="RESTRICT")
    )
    # Read the official address every week and keep a snapshot when the text changes.
    auto_check: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )


class SourceSnapshot(UUIDPrimaryKeyMixin, Base):
    """What the document said when staff captured it (append-only). The text is kept so a
    cited version can be reproduced; a different content hash from the snapshot a reference
    was verified against means the source changed and the reference needs review.
    Binary snapshots (PDFs) move to object storage with the upload pipeline (Milestone 6)."""

    __tablename__ = "source_snapshot"
    __table_args__ = (
        CheckConstraint("octet_length(content_hash) = 32", name="content_hash_sha256"),
        CheckConstraint(
            f"char_length(content_text) <= {MAX_SNAPSHOT_CHARS}", name="content_text_size"
        ),
        enum_check("capture_method", CaptureMethod),
        Index("ix_source_snapshot_document_captured", "source_document_id", "captured_at"),
    )

    source_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_document.id", ondelete="RESTRICT"), nullable=False
    )
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    captured_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    capture_method: Mapped[str] = mapped_column(
        Text, nullable=False, default=CaptureMethod.MANUAL, server_default=CaptureMethod.MANUAL
    )


class SourceCheck(UUIDPrimaryKeyMixin, Base):
    """One attempt by the app to read a document from its official address (append-only).
    A changed text becomes a new snapshot; files the app can't read as text (PDFs) are
    compared by their bytes so staff know to capture them by hand."""

    __tablename__ = "source_check"
    __table_args__ = (
        enum_check("trigger", CheckTrigger),
        enum_check("outcome", CheckOutcome),
        CheckConstraint(
            "body_sha256 IS NULL OR octet_length(body_sha256) = 32", name="body_sha256_size"
        ),
        Index("ix_source_check_document_checked", "source_document_id", "checked_at"),
    )

    source_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_document.id", ondelete="RESTRICT"), nullable=False
    )
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)  # the address read
    final_url: Mapped[str | None] = mapped_column(String(2000))  # after redirects
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(200))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    body_sha256: Mapped[bytes | None] = mapped_column(LargeBinary)
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_snapshot.id", ondelete="RESTRICT")
    )
    error: Mapped[str | None] = mapped_column(String(500))


class SourceReference(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, Base):
    """The atomic citation: a section/clause/page of a document and its extracted text."""

    __tablename__ = "source_reference"
    __table_args__ = (
        enum_check("verification_status", VerificationStatus),
        CheckConstraint(
            "verification_status <> 'VERIFIED' OR (verified_at IS NOT NULL "
            "AND verified_by IS NOT NULL AND next_review_due IS NOT NULL)",
            name="verified_has_reviewer",
        ),
        Index("ix_source_reference_source_document_id", "source_document_id"),
        Index("ix_source_reference_review_queue", "verification_status", "next_review_due"),
    )

    source_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_document.id", ondelete="RESTRICT"), nullable=False
    )
    section: Mapped[str | None] = mapped_column(String(200))
    clause: Mapped[str | None] = mapped_column(String(100))
    page: Mapped[str | None] = mapped_column(String(20))
    extracted_text: Mapped[str] = mapped_column(String(10000), nullable=False)
    # Staff's plain-language reading of the extract (what a rule encodes).
    interpretation: Mapped[str | None] = mapped_column(String(2000))
    verification_status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=VerificationStatus.UNVERIFIED,
        server_default=VerificationStatus.UNVERIFIED,
    )
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The snapshot the verifier checked the extract against.
    verified_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_snapshot.id", ondelete="RESTRICT")
    )
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_review_due: Mapped[date | None] = mapped_column(Date)


class SourceReviewEvent(UUIDPrimaryKeyMixin, Base):
    """Append-only history of a reference's verification (the app role may only insert)."""

    __tablename__ = "source_review_event"
    __table_args__ = (
        enum_check("action", ReviewAction),
        enum_check("from_status", VerificationStatus, nullable=True),
        enum_check("to_status", VerificationStatus),
        Index("ix_source_review_event_source_reference_id", "source_reference_id"),
    )

    source_reference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_reference.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(String(2000))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
