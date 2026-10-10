from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.modules.assessments.schemas import AssessmentOut
from app.modules.billing.models import PaymentStatus, RefundReason, RefundStatus
from app.modules.documents.models import EvidenceStatus, ReviewStatus
from app.modules.documents.schemas import DocumentOut, EvidenceOut
from app.modules.projects.models import ProjectStatus, Vertical
from app.modules.projects.schemas import TaskOut
from app.modules.review.models import (
    AuthorRole,
    CredentialKind,
    CredentialStatus,
    Decision,
    Discipline,
    ProfessionalStatus,
    ReviewRequestStatus,
)
from app.modules.rules.models import Confidence, OutcomeType

Text200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Text100 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Body = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=2000)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


# --- Professionals ---------------------------------------------------------------------


class CredentialIn(BaseModel):
    kind: CredentialKind
    issuer: Text200 = Field(description="Who issued it, e.g. the licensing body or insurer.")
    number: Text100 = Field(description="Licence, registration, membership or policy number.")
    expires_on: date | None = None


class CredentialOut(BaseModel):
    id: uuid.UUID
    kind: CredentialKind
    issuer: str
    number: str
    expires_on: date | None
    status: CredentialStatus
    notes: str | None
    verified_at: datetime | None
    current: bool = Field(description="Verified and not expired today.")


class ServiceIn(BaseModel):
    vertical: Vertical
    description: Note | None = None


class ServicesIn(BaseModel):
    services: list[ServiceIn] = Field(max_length=6)


class ServiceOut(BaseModel):
    vertical: Vertical
    description: str | None


class ProfileIn(BaseModel):
    display_name: Text200
    discipline: Discipline
    bio: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None


class ProfileUpdateIn(BaseModel):
    display_name: Text200 | None = None
    bio: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None


class ProfessionalPublicOut(BaseModel):
    """What a customer sees about their reviewer."""

    id: uuid.UUID
    display_name: str
    discipline: Discipline
    practice_name: str


class ProfessionalOut(ProfessionalPublicOut):
    user_id: uuid.UUID
    practice_id: uuid.UUID
    email: str
    bio: str | None
    status: ProfessionalStatus
    credentials: list[CredentialOut]
    services: list[ServiceOut]
    problems: list[str] = Field(description="Why they can't be assigned reviews today.")
    created_at: datetime


class CredentialCheckIn(BaseModel):
    status: CredentialStatus
    notes: Note | None = None


class ProfessionalStatusIn(BaseModel):
    status: ProfessionalStatus


# --- Reviews ---------------------------------------------------------------------------


class ReviewRequestIn(BaseModel):
    assessment_id: uuid.UUID
    message: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None


class ResubmitIn(BaseModel):
    assessment_id: uuid.UUID | None = Field(
        default=None, description="Move the review to this (the project's latest) assessment."
    )


class CommentIn(BaseModel):
    body: Body
    finding_id: uuid.UUID | None = None


class CommentOut(BaseModel):
    id: uuid.UUID
    finding_id: uuid.UUID | None
    author_name: str | None
    author_role: AuthorRole
    body: str
    created_at: datetime


class OverrideIn(BaseModel):
    finding_id: uuid.UUID
    new_outcome_type: OutcomeType | None = Field(
        default=None, description="Leave out to keep the finding's outcome."
    )
    new_confidence: Confidence
    reason: Reason
    source_reference_id: uuid.UUID | None = None


class OverrideSourceOut(BaseModel):
    id: uuid.UUID
    citation: str
    verification_status: str


class OverrideOut(BaseModel):
    id: uuid.UUID
    review_request_id: uuid.UUID
    finding_id: uuid.UUID
    previous_outcome_type: OutcomeType | None
    previous_confidence: Confidence
    new_outcome_type: OutcomeType | None
    new_confidence: Confidence
    reason: str
    source: OverrideSourceOut | None
    overridden_by_name: str | None
    created_at: datetime
    current: bool = Field(description="The latest change to this finding.")


class DecisionIn(BaseModel):
    decision: Decision
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)] | None = None


class DecisionOut(BaseModel):
    id: uuid.UUID
    assessment_id: uuid.UUID
    decision: Decision
    notes: str | None
    created_at: datetime


class EvidenceCheckIn(BaseModel):
    status: EvidenceStatus
    note: Note | None = None


class ReviewTaskIn(BaseModel):
    title: Text200
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None


class DeclineIn(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class AssignIn(BaseModel):
    professional_id: uuid.UUID
    due_on: date | None = None


class RefundOut(BaseModel):
    """Money given back on the review's payment (Milestone 22)."""

    id: uuid.UUID
    amount_cents: int
    currency: str
    reason: RefundReason
    status: RefundStatus = Field(
        description="PENDING: being sent to Stripe. SUBMITTED or SUCCEEDED: on its way to the "
        "card. FAILED: Stripe refused it and staff are following it up."
    )
    created_at: datetime
    sent_at: datetime | None


class StaffRefundOut(RefundOut):
    note: str | None
    error: str | None


class ReviewPaymentOut(BaseModel):
    """The payment for a priced review (Milestone 13), as Stripe last confirmed it."""

    id: uuid.UUID
    status: PaymentStatus
    amount_cents: int
    currency: str
    paid_at: datetime | None
    refunded_cents: int
    refunds: list[RefundOut]


class StaffPaymentOut(BaseModel):
    id: uuid.UUID
    status: PaymentStatus
    amount_cents: int
    currency: str
    paid_at: datetime | None
    refunded_cents: int
    refundable_cents: int = Field(description="What staff can still refund.")
    refunds: list[StaffRefundOut]


class RefundIn(BaseModel):
    amount_cents: int | None = Field(
        default=None, gt=0, description="Leave out to refund everything that is left."
    )
    note: str = Field(min_length=3, max_length=500, description="Why (staff only).")


class ReviewSummary(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    assessment_id: uuid.UUID
    status: ReviewRequestStatus
    message: str | None
    professional: ProfessionalPublicOut | None
    due_on: date | None
    created_at: datetime
    assigned_at: datetime | None
    started_at: datetime | None
    closed_at: datetime | None
    payment: ReviewPaymentOut | None = None
    cancel_refund_cents: int = Field(
        default=0, description="What cancelling now would refund (0: nothing)."
    )


class ReviewOut(ReviewSummary):
    project_title: str
    project_reference: str
    vertical: Vertical
    comments: list[CommentOut]
    overrides: list[OverrideOut]
    decisions: list[DecisionOut]


class CheckoutOut(BaseModel):
    url: str = Field(description="Stripe's hosted checkout page: send the browser there.")


class AssessmentReviewOut(BaseModel):
    """An assessment's review state for the customer's report page."""

    review_status: ReviewStatus
    review: ReviewOut | None = Field(description="The review on this assessment, if any.")
    overrides: list[OverrideOut] = Field(
        description="Every reviewer change to this assessment's findings, oldest first."
    )


class QueueItemOut(BaseModel):
    id: uuid.UUID
    status: ReviewRequestStatus
    project_reference: str
    project_title: str
    vertical: Vertical
    assigned_professional_id: uuid.UUID | None
    created_at: datetime
    due_on: date | None


class ReviewerWorkspaceOut(BaseModel):
    """Everything the assigned reviewer can see."""

    review: ReviewOut
    project_status: ProjectStatus
    assessment: AssessmentOut
    shared_documents: list[DocumentOut]
    evidence: list[EvidenceOut]
    tasks: list[TaskOut] = Field(description="Tasks this review added to the project.")


class StaffReviewOut(BaseModel):
    review: ReviewSummary
    project_title: str
    project_reference: str
    vertical: Vertical
    rule_sets_in_scope: list[str]
    candidates: list[ProfessionalOut] = Field(
        description="Active professionals who can be assigned this review today."
    )
    payment: StaffPaymentOut | None = None
