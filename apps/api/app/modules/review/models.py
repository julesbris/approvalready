"""Professional review (Milestone 7).

Professionals are platform records: a person in a ``PROFESSIONAL_PRACTICE`` organisation,
with credentials and services that staff verify. Review requests and everything said or
changed during a review are tenant rows of the *customer's* organisation, so the customer
always owns the record of their review. A reviewer reaches them only through an assignment
(see ``service.py``), never through membership of the customer's organisation.

Findings are never edited: a reviewer's change is a ``finding_override`` row (append-only,
with a reason and optionally a source), and the latest override of a finding is what the
customer and the report see, next to the original.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
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
from app.modules.rules.models import Confidence, OutcomeType


class Discipline(StrEnum):
    TOWN_PLANNER = "TOWN_PLANNER"
    SURVEYOR = "SURVEYOR"
    BUILDING_CERTIFIER = "BUILDING_CERTIFIER"
    BUILDING_DESIGNER = "BUILDING_DESIGNER"
    ENGINEER = "ENGINEER"
    MARINE_SURVEYOR = "MARINE_SURVEYOR"
    LAWYER = "LAWYER"
    ACCOUNTANT = "ACCOUNTANT"
    GRANT_WRITER = "GRANT_WRITER"
    OTHER = "OTHER"


class ProfessionalStatus(StrEnum):
    PENDING = "PENDING"  # profile created, waiting for staff to check credentials
    ACTIVE = "ACTIVE"  # can be assigned reviews
    SUSPENDED = "SUSPENDED"


class CredentialKind(StrEnum):
    LICENCE = "LICENCE"
    REGISTRATION = "REGISTRATION"
    MEMBERSHIP = "MEMBERSHIP"  # e.g. Planning Institute of Australia
    INSURANCE = "INSURANCE"  # professional indemnity
    QUALIFICATION = "QUALIFICATION"


class CredentialStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ReviewRequestStatus(StrEnum):
    REVIEW_REQUESTED = "REVIEW_REQUESTED"  # waiting for staff to assign a professional
    ASSIGNED = "ASSIGNED"
    IN_REVIEW = "IN_REVIEW"
    CHANGES_REQUIRED = "CHANGES_REQUIRED"  # the customer has something to do, then resubmits
    APPROVED = "APPROVED"  # the reviewer agrees with the assessment (as overridden)
    COMPLETED = "COMPLETED"  # reviewed, not approved: the comments say why
    CANCELLED = "CANCELLED"


OPEN_STATUSES = (
    ReviewRequestStatus.REVIEW_REQUESTED,
    ReviewRequestStatus.ASSIGNED,
    ReviewRequestStatus.IN_REVIEW,
    ReviewRequestStatus.CHANGES_REQUIRED,
)
ASSIGNED_STATUSES = (
    ReviewRequestStatus.ASSIGNED,
    ReviewRequestStatus.IN_REVIEW,
    ReviewRequestStatus.CHANGES_REQUIRED,
    ReviewRequestStatus.APPROVED,
    ReviewRequestStatus.COMPLETED,
)


class Decision(StrEnum):
    CHANGES_REQUIRED = "CHANGES_REQUIRED"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"


class AuthorRole(StrEnum):
    CUSTOMER = "CUSTOMER"
    REVIEWER = "REVIEWER"


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class Professional(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, Base):
    """A person who reviews, in one practice. Platform table (no tenant)."""

    __tablename__ = "professional"
    __table_args__ = (
        UniqueConstraint("user_id", "practice_id"),
        enum_check("discipline", Discipline),
        enum_check("status", ProfessionalStatus),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    )
    practice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organisation.id", ondelete="RESTRICT"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    discipline: Mapped[str] = mapped_column(Text, nullable=False)
    bio: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=ProfessionalStatus.PENDING
    )
    status_changed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProfessionalCredential(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, Base):
    __tablename__ = "professional_credential"
    __table_args__ = (
        enum_check("kind", CredentialKind),
        enum_check("status", CredentialStatus),
        CheckConstraint(
            "status = 'UNVERIFIED' OR (verified_by IS NOT NULL AND verified_at IS NOT NULL)",
            name="checked_has_checker",
        ),
        Index("ix_professional_credential_professional_id", "professional_id"),
    )

    professional_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("professional.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    issuer: Mapped[str] = mapped_column(String(200), nullable=False)
    number: Mapped[str] = mapped_column(String(100), nullable=False)
    expires_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=CredentialStatus.UNVERIFIED
    )
    notes: Mapped[str | None] = mapped_column(String(500))
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProfessionalService(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """What a professional reviews: a vertical and a short description. Prices arrive with
    payments (Milestone 13)."""

    __tablename__ = "professional_service"
    __table_args__ = (
        UniqueConstraint("professional_id", "vertical"),
        enum_check("vertical", Vertical),
    )

    professional_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("professional.id", ondelete="CASCADE"), nullable=False
    )
    vertical: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))


class ReviewRequest(UUIDPrimaryKeyMixin, TimestampMixin, CreatedByMixin, TenantMixin, Base):
    """A customer's request for a professional to check one assessment of a project."""

    __tablename__ = "review_request"
    __table_args__ = (
        UniqueConstraint("organisation_id", "id"),
        tenant_fk("project_id", "project", ondelete="CASCADE"),
        tenant_fk("assessment_id", "assessment", ondelete="CASCADE"),
        enum_check("status", ReviewRequestStatus),
        CheckConstraint(
            f"status NOT IN ({_in(ASSIGNED_STATUSES)}) OR assigned_professional_id IS NOT NULL",
            name="assigned_has_professional",
        ),
        # One open review per project at a time.
        Index(
            "uq_review_request_open_project",
            "project_id",
            unique=True,
            postgresql_where=text(f"status IN ({_in(OPEN_STATUSES)})"),
        ),
        Index("ix_review_request_project_id", "project_id", "created_at"),
        Index("ix_review_request_assigned_professional_id", "assigned_professional_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # The assessment under review; a resubmission after changes can move it to a newer one.
    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=ReviewRequestStatus.REVIEW_REQUESTED
    )
    message: Mapped[str | None] = mapped_column(String(2000))
    assigned_professional_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("professional.id", ondelete="RESTRICT")
    )
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_on: Mapped[date | None] = mapped_column(Date)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReviewComment(UUIDPrimaryKeyMixin, TenantMixin, Base):
    """Append-only conversation between the customer and the reviewer."""

    __tablename__ = "review_comment"
    __table_args__ = (
        tenant_fk("review_request_id", "review_request", ondelete="CASCADE"),
        tenant_fk("finding_id", "assessment_finding", ondelete="CASCADE"),
        enum_check("author_role", AuthorRole),
        CheckConstraint("char_length(btrim(body)) > 0", name="body_not_blank"),
        Index("ix_review_comment_review_request_id", "review_request_id", "created_at"),
    )

    review_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    finding_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    author_role: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(String(4000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class FindingOverride(UUIDPrimaryKeyMixin, TenantMixin, Base):
    """A reviewer's change to a finding's outcome or confidence. Append-only: a later
    override of the same finding replaces it in every view, and both stay on record."""

    __tablename__ = "finding_override"
    __table_args__ = (
        tenant_fk("review_request_id", "review_request", ondelete="CASCADE"),
        tenant_fk("finding_id", "assessment_finding", ondelete="CASCADE"),
        enum_check("previous_outcome_type", OutcomeType, nullable=True),
        enum_check("new_outcome_type", OutcomeType, nullable=True),
        enum_check("previous_confidence", Confidence),
        enum_check("new_confidence", Confidence),
        CheckConstraint("char_length(btrim(reason)) >= 10", name="reason_given"),
        Index("ix_finding_override_finding_id", "finding_id", "created_at"),
        Index("ix_finding_override_review_request_id", "review_request_id"),
    )

    review_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    finding_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # What the customer saw before this override (the finding, or the previous override).
    previous_outcome_type: Mapped[str | None] = mapped_column(Text)
    previous_confidence: Mapped[str] = mapped_column(Text, nullable=False)
    new_outcome_type: Mapped[str | None] = mapped_column(Text)
    new_confidence: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(String(2000), nullable=False)
    source_reference_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_reference.id", ondelete="RESTRICT")
    )
    overridden_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ReviewDecision(UUIDPrimaryKeyMixin, TenantMixin, Base):
    """Append-only: each decision the reviewer made, on the assessment it was made on."""

    __tablename__ = "review_decision"
    __table_args__ = (
        tenant_fk("review_request_id", "review_request", ondelete="CASCADE"),
        tenant_fk("assessment_id", "assessment", ondelete="CASCADE"),
        enum_check("decision", Decision),
        Index("ix_review_decision_review_request_id", "review_request_id", "created_at"),
    )

    review_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(4000))
    professional_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("professional.id", ondelete="RESTRICT"), nullable=False
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
