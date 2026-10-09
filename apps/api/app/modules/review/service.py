"""Review requests: the customer asks, staff assign, the professional reviews and decides.

Workflow (``TRANSITIONS``)::

    REVIEW_REQUESTED -> ASSIGNED (staff) -> IN_REVIEW (reviewer starts)
    ASSIGNED -> REVIEW_REQUESTED (reviewer declines, or staff unassign)
    IN_REVIEW -> CHANGES_REQUIRED | APPROVED | COMPLETED (reviewer decides)
    CHANGES_REQUIRED -> IN_REVIEW (customer resubmits, optionally with a newer assessment)
    any open status -> CANCELLED (customer)

How a reviewer reaches a customer's rows. Review rows belong to the customer's organisation
and are protected by row-level security like every tenant row. A reviewer is not a member of
that organisation, so their requests resolve the review's organisation through
``review_request_organisation()`` (a SECURITY DEFINER function that returns one id), bind
that organisation for the request, and then check the assignment on the row itself: only
the assigned professional, acting from their practice, gets anything back. What they see is
limited by this module to the review's project: its assessment, answers, evidence and the
files the customer shared.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from fastapi import status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, not_found
from app.db.tenant import bind_tenant
from app.modules.assessments.models import Assessment, AssessmentFinding
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.documents import service as documents
from app.modules.documents.models import (
    Classification,
    Evidence,
    EvidenceStatus,
    ReviewStatus,
    UploadedDocument,
)
from app.modules.identity.models import AppUser
from app.modules.projects import service as projects
from app.modules.projects.models import Project, ProjectStatus, Task, TaskSource
from app.modules.regulatory import service as regulatory
from app.modules.regulatory.models import SourceDocument, SourceReference, VerificationStatus
from app.modules.review import professionals
from app.modules.review.models import (
    OPEN_STATUSES,
    AuthorRole,
    Decision,
    FindingOverride,
    Professional,
    ReviewComment,
    ReviewDecision,
    ReviewRequest,
)
from app.modules.review.models import ReviewRequestStatus as RS
from app.modules.review.professionals import ProfessionalView
from app.modules.rules.models import Confidence
from app.modules.tenancy import service as tenancy

TRANSITIONS: dict[str, frozenset[str]] = {
    RS.REVIEW_REQUESTED: frozenset({RS.ASSIGNED, RS.CANCELLED}),
    RS.ASSIGNED: frozenset({RS.REVIEW_REQUESTED, RS.IN_REVIEW, RS.CANCELLED}),
    RS.IN_REVIEW: frozenset({RS.CHANGES_REQUIRED, RS.APPROVED, RS.COMPLETED, RS.CANCELLED}),
    RS.CHANGES_REQUIRED: frozenset({RS.IN_REVIEW, RS.CANCELLED}),
    RS.APPROVED: frozenset(),
    RS.COMPLETED: frozenset(),
    RS.CANCELLED: frozenset(),
}
DECISION_STATUS = {
    Decision.CHANGES_REQUIRED: RS.CHANGES_REQUIRED,
    Decision.APPROVED: RS.APPROVED,
    Decision.COMPLETED: RS.COMPLETED,
}
# The reviewer can see the review once assigned, and keeps read access to their past reviews.
REVIEWER_VISIBLE = frozenset(TRANSITIONS) - {RS.REVIEW_REQUESTED, RS.CANCELLED}
# The reviewer can talk and add tasks while the review is in their hands or the customer's.
REVIEWER_ACTIVE = frozenset({RS.ASSIGNED, RS.IN_REVIEW, RS.CHANGES_REQUIRED})


def utcnow() -> datetime:
    return datetime.now(UTC)


def _conflict(code: str, message: str) -> ApiError:
    return ApiError(status.HTTP_409_CONFLICT, code, message)


def _status_words(value: str) -> str:
    return value.replace("_", " ").lower()


def _move(review: ReviewRequest, to: str) -> str:
    if to not in TRANSITIONS[review.status]:
        raise _conflict(
            "invalid_review_status",
            f"A review that is {_status_words(review.status)} can't be moved to "
            f"{_status_words(to)}.",
        )
    previous = review.status
    review.status = to
    return previous


async def _audit(
    db: AsyncSession,
    action: str,
    review: ReviewRequest,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
    details: dict[str, Any] | None = None,
) -> None:
    await audit.record(
        db,
        action,
        actor_user_id=actor_id,
        organisation_id=review.organisation_id,
        target_type="review_request",
        target_id=review.id,
        meta=meta,
        details=details,
    )


# --- Reading ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommentRow:
    comment: ReviewComment
    author_name: str | None


@dataclass(frozen=True)
class OverrideRow:
    override: FindingOverride
    author_name: str | None
    source: SourceReference | None
    citation: str | None


@dataclass(frozen=True)
class ReviewView:
    review: ReviewRequest
    project: Project
    professional: ProfessionalView | None
    comments: list[CommentRow]
    overrides: list[OverrideRow]
    decisions: list[ReviewDecision]


async def _names(db: AsyncSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = await db.execute(select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(wanted)))
    return {i: n for i, n in rows.all()}


async def overrides_for_findings(
    db: AsyncSession, finding_ids: list[uuid.UUID]
) -> list[OverrideRow]:
    """Every override of these findings, oldest first (the last per finding is current)."""
    if not finding_ids:
        return []
    rows = list(
        (
            await db.execute(
                select(FindingOverride)
                .where(FindingOverride.finding_id.in_(finding_ids))
                .order_by(FindingOverride.created_at, FindingOverride.id)
            )
        ).scalars()
    )
    names = await _names(db, {o.overridden_by for o in rows})
    refs = {o.source_reference_id for o in rows if o.source_reference_id}
    sources: dict[uuid.UUID, tuple[SourceReference, str]] = {}
    if refs:
        for ref, document in (
            await db.execute(
                select(SourceReference, SourceDocument)
                .join(SourceDocument, SourceDocument.id == SourceReference.source_document_id)
                .where(SourceReference.id.in_(refs))
            )
        ).all():
            sources[ref.id] = (ref, regulatory.citation(ref, document))
    result = []
    for o in rows:
        found = sources.get(o.source_reference_id) if o.source_reference_id else None
        result.append(
            OverrideRow(
                o,
                names.get(o.overridden_by) if o.overridden_by else None,
                found[0] if found else None,
                found[1] if found else None,
            )
        )
    return result


def current_overrides(rows: list[OverrideRow]) -> dict[uuid.UUID, OverrideRow]:
    latest: dict[uuid.UUID, OverrideRow] = {}
    for row in rows:
        latest[row.override.finding_id] = row
    return latest


async def _finding_ids(db: AsyncSession, assessment_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        (
            await db.execute(
                select(AssessmentFinding.id).where(AssessmentFinding.assessment_id == assessment_id)
            )
        ).scalars()
    )


async def build_view(db: AsyncSession, review: ReviewRequest) -> ReviewView:
    project = await db.get(Project, review.project_id)
    assert project is not None
    professional = (
        await professionals.view(
            db, await professionals.get_professional(db, review.assigned_professional_id)
        )
        if review.assigned_professional_id
        else None
    )
    comments = list(
        (
            await db.execute(
                select(ReviewComment)
                .where(ReviewComment.review_request_id == review.id)
                .order_by(ReviewComment.created_at, ReviewComment.id)
            )
        ).scalars()
    )
    names = await _names(db, {c.author_id for c in comments})
    overrides = [
        o
        for o in await overrides_for_findings(db, await _finding_ids(db, review.assessment_id))
        if o.override.review_request_id == review.id
    ]
    decisions = list(
        (
            await db.execute(
                select(ReviewDecision)
                .where(ReviewDecision.review_request_id == review.id)
                .order_by(ReviewDecision.created_at, ReviewDecision.id)
            )
        ).scalars()
    )
    return ReviewView(
        review,
        project,
        professional,
        [CommentRow(c, names.get(c.author_id) if c.author_id else None) for c in comments],
        overrides,
        decisions,
    )


async def get_review(
    db: AsyncSession, organisation_id: uuid.UUID, review_id: uuid.UUID, *, lock: bool = False
) -> ReviewRequest:
    query = (
        select(ReviewRequest)
        .join(Project, Project.id == ReviewRequest.project_id)
        .where(
            ReviewRequest.id == review_id,
            ReviewRequest.organisation_id == organisation_id,
            Project.deleted_at.is_(None),
        )
    )
    if lock:
        query = query.with_for_update(of=ReviewRequest)
    review = (await db.execute(query)).scalar_one_or_none()
    if review is None:
        raise not_found("Review")
    return review


async def list_for_project(db: AsyncSession, project: Project) -> list[ReviewRequest]:
    return list(
        (
            await db.execute(
                select(ReviewRequest)
                .where(ReviewRequest.project_id == project.id)
                .order_by(ReviewRequest.created_at.desc())
            )
        ).scalars()
    )


async def review_status_for(
    db: AsyncSession, assessment: Assessment
) -> tuple[ReviewStatus, ReviewRequest | None, ReviewDecision | None]:
    """Where this assessment stands with professional review, for reports: an open review
    on it, else the last decision made on it."""
    open_review = (
        await db.execute(
            select(ReviewRequest)
            .where(
                ReviewRequest.assessment_id == assessment.id,
                ReviewRequest.status.in_([RS.REVIEW_REQUESTED, RS.ASSIGNED, RS.IN_REVIEW]),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if open_review is not None:
        return ReviewStatus.IN_REVIEW, open_review, None
    decision = (
        await db.execute(
            select(ReviewDecision)
            .where(ReviewDecision.assessment_id == assessment.id)
            .order_by(ReviewDecision.created_at.desc(), ReviewDecision.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if decision is None:
        return ReviewStatus.NOT_REVIEWED, None, None
    review = await db.get(ReviewRequest, decision.review_request_id)
    mapped = {
        Decision.CHANGES_REQUIRED: ReviewStatus.CHANGES_REQUIRED,
        Decision.APPROVED: ReviewStatus.APPROVED,
        Decision.COMPLETED: ReviewStatus.REVIEWED,
    }[Decision(decision.decision)]
    return mapped, review, decision


async def latest_assessment(db: AsyncSession, project: Project) -> Assessment | None:
    return (
        await db.execute(
            select(Assessment)
            .where(Assessment.project_id == project.id)
            .order_by(Assessment.created_at.desc(), Assessment.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _require_latest(db: AsyncSession, project: Project, assessment_id: uuid.UUID) -> None:
    latest = await latest_assessment(db, project)
    if latest is None or latest.id != assessment_id:
        raise _conflict(
            "not_latest_assessment",
            "Only the project's latest assessment can be reviewed. Open the latest one.",
        )


# --- Customer --------------------------------------------------------------------------


async def request_review(
    db: AsyncSession,
    project: Project,
    *,
    assessment_id: uuid.UUID,
    message: str | None,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> ReviewRequest:
    if project.status == ProjectStatus.ARCHIVED:
        raise _conflict("project_archived", "Move this project back into progress first.")
    await _require_latest(db, project, assessment_id)
    open_review = (
        await db.execute(
            select(ReviewRequest.id).where(
                ReviewRequest.project_id == project.id, ReviewRequest.status.in_(OPEN_STATUSES)
            )
        )
    ).scalar_one_or_none()
    if open_review is not None:
        raise _conflict("review_open", "This project already has a review under way.")
    review = ReviewRequest(
        organisation_id=project.organisation_id,
        project_id=project.id,
        assessment_id=assessment_id,
        status=RS.REVIEW_REQUESTED,
        message=message,
        created_by=actor_id,
    )
    db.add(review)
    await db.flush()
    await _audit(
        db,
        "review.requested",
        review,
        actor_id=actor_id,
        meta=meta,
        details={"project_id": str(project.id), "assessment_id": str(assessment_id)},
    )
    await projects.mark_in_review(db, project, actor_id=actor_id, meta=meta)
    return review


async def _close(
    db: AsyncSession, review: ReviewRequest, *, actor_id: uuid.UUID, meta: RequestMeta | None
) -> None:
    review.closed_at = utcnow()
    project = await db.get(Project, review.project_id)
    assert project is not None
    await projects.end_review(db, project, actor_id=actor_id, meta=meta)


async def cancel(
    db: AsyncSession, review: ReviewRequest, *, actor_id: uuid.UUID, meta: RequestMeta | None
) -> None:
    previous = _move(review, RS.CANCELLED)
    await _close(db, review, actor_id=actor_id, meta=meta)
    await db.flush()
    await _audit(
        db, "review.cancelled", review, actor_id=actor_id, meta=meta, details={"from": previous}
    )


async def resubmit(
    db: AsyncSession,
    review: ReviewRequest,
    *,
    assessment_id: uuid.UUID | None,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> None:
    """After changes were asked for: back to the reviewer, on a newer assessment if the
    customer ran one. Overrides made on the old assessment's findings stay with it."""
    project = await db.get(Project, review.project_id)
    assert project is not None
    if assessment_id is not None and assessment_id != review.assessment_id:
        await _require_latest(db, project, assessment_id)
        review.assessment_id = assessment_id
    _move(review, RS.IN_REVIEW)
    await db.flush()
    await _audit(
        db,
        "review.resubmitted",
        review,
        actor_id=actor_id,
        meta=meta,
        details={"assessment_id": str(review.assessment_id)},
    )


async def _finding_in(
    db: AsyncSession, review: ReviewRequest, finding_id: uuid.UUID
) -> AssessmentFinding:
    finding = (
        await db.execute(
            select(AssessmentFinding).where(
                AssessmentFinding.id == finding_id,
                AssessmentFinding.assessment_id == review.assessment_id,
            )
        )
    ).scalar_one_or_none()
    if finding is None:
        raise not_found("Finding")
    return finding


async def add_comment(
    db: AsyncSession,
    review: ReviewRequest,
    *,
    body: str,
    finding_id: uuid.UUID | None,
    role: AuthorRole,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> ReviewComment:
    allowed = OPEN_STATUSES if role == AuthorRole.CUSTOMER else REVIEWER_ACTIVE
    if review.status not in allowed:
        raise _conflict("review_closed", "This review is closed to new comments.")
    if finding_id is not None:
        await _finding_in(db, review, finding_id)
    comment = ReviewComment(
        organisation_id=review.organisation_id,
        review_request_id=review.id,
        finding_id=finding_id,
        author_id=actor_id,
        author_role=role,
        body=body,
    )
    db.add(comment)
    await db.flush()
    await _audit(
        db,
        "review.comment_added",
        review,
        actor_id=actor_id,
        meta=meta,
        details={"comment_id": str(comment.id), "role": role},
    )
    return comment


# --- Staff -----------------------------------------------------------------------------


@dataclass(frozen=True)
class QueueRow:
    id: uuid.UUID
    organisation_id: uuid.UUID
    status: str
    project_reference: str
    project_title: str
    vertical: str
    assigned_professional_id: uuid.UUID | None
    created_at: datetime
    due_on: date | None


async def queue(
    db: AsyncSession,
    *,
    professional_id: uuid.UUID | None = None,
    statuses: list[str] | None = None,
) -> list[QueueRow]:
    """Review requests across organisations (summaries only), through the definer function:
    staff see all of them, a professional only theirs."""
    rows = await db.execute(
        text(
            "SELECT id, organisation_id, status, project_reference, project_title, vertical, "
            "assigned_professional_id, created_at, due_on "
            "FROM review_queue(CAST(:professional AS uuid), CAST(:statuses AS text[]))"
        ),
        {"professional": professional_id, "statuses": statuses},
    )
    return [QueueRow(*row) for row in rows.all()]


async def bind_review(db: AsyncSession, review_id: uuid.UUID) -> uuid.UUID:
    """Bind the review's organisation for this request (after the caller's own permission
    check). 404 when there is no such review."""
    organisation_id = (
        await db.execute(text("SELECT review_request_organisation(:id)"), {"id": review_id})
    ).scalar_one_or_none()
    if organisation_id is None:
        raise not_found("Review")
    await bind_tenant(db, organisation_id)
    return uuid.UUID(str(organisation_id))


async def assign(
    db: AsyncSession,
    review: ReviewRequest,
    professional: Professional,
    *,
    due_on: date | None,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
    on: date,
) -> None:
    project = await db.get(Project, review.project_id)
    assert project is not None
    view = await professionals.view(db, professional)
    problems = professionals.eligibility(view, project.vertical, on)
    if await tenancy.membership(db, professional.user_id, review.organisation_id) is not None:
        problems.append("They belong to the customer's organisation.")
    if problems:
        raise _conflict("not_eligible", " ".join(problems))
    _move(review, RS.ASSIGNED)
    review.assigned_professional_id = professional.id
    review.assigned_by = actor_id
    review.assigned_at = utcnow()
    review.due_on = due_on
    await db.flush()
    await _audit(
        db,
        "review.assigned",
        review,
        actor_id=actor_id,
        meta=meta,
        details={"professional_id": str(professional.id), "due_on": str(due_on or "")},
    )


async def unassign(
    db: AsyncSession,
    review: ReviewRequest,
    *,
    reason: str | None,
    action: str,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> None:
    """Back to the queue: the reviewer declined, or staff took it back before it started."""
    professional_id = review.assigned_professional_id
    _move(review, RS.REVIEW_REQUESTED)
    review.assigned_professional_id = None
    review.assigned_by = review.assigned_at = review.due_on = None
    await db.flush()
    await _audit(
        db,
        action,
        review,
        actor_id=actor_id,
        meta=meta,
        details={"professional_id": str(professional_id), "reason": reason or ""},
    )


# --- Reviewer --------------------------------------------------------------------------


def require_assigned(review: ReviewRequest, professional: Professional) -> None:
    if review.assigned_professional_id != professional.id or review.status not in REVIEWER_VISIBLE:
        raise not_found("Review")


def _require(review: ReviewRequest, *statuses: str) -> None:
    if review.status not in statuses:
        raise _conflict(
            "invalid_review_status",
            f"That can't be done while the review is {_status_words(review.status)}.",
        )


async def start(
    db: AsyncSession, review: ReviewRequest, *, actor_id: uuid.UUID, meta: RequestMeta | None
) -> None:
    _move(review, RS.IN_REVIEW)
    review.started_at = utcnow()
    await db.flush()
    await _audit(db, "review.started", review, actor_id=actor_id, meta=meta)


async def override_finding(
    db: AsyncSession,
    review: ReviewRequest,
    *,
    finding_id: uuid.UUID,
    new_outcome_type: str | None,
    new_confidence: str,
    reason: str,
    source_reference_id: uuid.UUID | None,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> FindingOverride:
    """Change what a finding says, with a reason. Confidence can only be set to VERIFIED
    against a verified source, as everywhere else in the platform."""
    _require(review, RS.IN_REVIEW)
    finding = await _finding_in(db, review, finding_id)
    source = None
    if source_reference_id is not None:
        source = await db.get(SourceReference, source_reference_id)
        if source is None:
            raise not_found("Source reference")
    if new_confidence == Confidence.VERIFIED and (
        source is None or source.verification_status != VerificationStatus.VERIFIED
    ):
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "verified_needs_source",
            "Verified needs a source reference that our team has verified. Choose one, "
            "or use Likely.",
        )
    current = current_overrides(await overrides_for_findings(db, [finding.id])).get(finding.id)
    previous_outcome = current.override.new_outcome_type if current else finding.outcome_type
    previous_confidence = current.override.new_confidence if current else finding.confidence
    outcome = new_outcome_type if new_outcome_type is not None else previous_outcome
    if (outcome, new_confidence) == (previous_outcome, previous_confidence):
        raise _conflict("no_change", "That is what the finding already says.")
    override = FindingOverride(
        organisation_id=review.organisation_id,
        review_request_id=review.id,
        finding_id=finding.id,
        previous_outcome_type=previous_outcome,
        previous_confidence=previous_confidence,
        new_outcome_type=outcome,
        new_confidence=new_confidence,
        reason=reason,
        source_reference_id=source_reference_id,
        overridden_by=actor_id,
    )
    db.add(override)
    await db.flush()
    await _audit(
        db,
        "finding.overridden",
        review,
        actor_id=actor_id,
        meta=meta,
        details={
            "override_id": str(override.id),
            "finding_id": str(finding.id),
            "from": [previous_outcome, previous_confidence],
            "to": [outcome, new_confidence],
            "source_reference_id": str(source_reference_id or ""),
        },
    )
    return override


async def reviewable_documents(
    db: AsyncSession, review: ReviewRequest
) -> tuple[list[UploadedDocument], list[documents.EvidenceRow]]:
    """What the reviewer may open: files the customer shared, and files offered as evidence
    for the assessment under review."""
    assessment = await db.get(Assessment, review.assessment_id)
    assert assessment is not None
    evidence = await documents.list_evidence(db, assessment)
    shared = list(
        (
            await db.execute(
                select(UploadedDocument)
                .where(
                    UploadedDocument.project_id == review.project_id,
                    UploadedDocument.classification == Classification.SHARED_WITH_REVIEWER,
                    UploadedDocument.deleted_at.is_(None),
                )
                .order_by(UploadedDocument.created_at)
            )
        ).scalars()
    )
    return shared, evidence


async def reviewable_document(
    db: AsyncSession, review: ReviewRequest, document_id: uuid.UUID
) -> UploadedDocument:
    shared, evidence = await reviewable_documents(db, review)
    for d in [*shared, *(row.document for row in evidence)]:
        if d.id == document_id:
            return d
    raise not_found("Document")


async def check_evidence(
    db: AsyncSession,
    review: ReviewRequest,
    evidence_id: uuid.UUID,
    *,
    new_status: EvidenceStatus,
    note: str | None,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> documents.EvidenceRow:
    _require(review, RS.IN_REVIEW)
    _, rows = await reviewable_documents(db, review)
    row = next((r for r in rows if r.evidence.id == evidence_id), None)
    if row is None:
        raise not_found("Evidence")
    if new_status == EvidenceStatus.REJECTED and not note:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "note_required",
            "Say why the file doesn't meet the requirement.",
        )
    evidence: Evidence = row.evidence
    previous = evidence.status
    evidence.status = new_status
    evidence.review_note = note
    evidence.reviewed_by = actor_id if new_status != EvidenceStatus.SUBMITTED else None
    evidence.reviewed_at = utcnow() if new_status != EvidenceStatus.SUBMITTED else None
    await db.flush()
    await _audit(
        db,
        "evidence.reviewed",
        review,
        actor_id=actor_id,
        meta=meta,
        details={"evidence_id": str(evidence.id), "from": previous, "to": new_status},
    )
    return row


async def add_task(
    db: AsyncSession,
    review: ReviewRequest,
    *,
    title: str,
    notes: str | None,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> Task:
    _require(review, *REVIEWER_ACTIVE)
    project = await db.get(Project, review.project_id)
    assert project is not None
    task = Task(
        organisation_id=review.organisation_id,
        project_id=project.id,
        title=title,
        notes=notes,
        source=TaskSource.REVIEWER,
        created_by=actor_id,
    )
    db.add(task)
    await db.flush()
    await _audit(
        db,
        "review.task_added",
        review,
        actor_id=actor_id,
        meta=meta,
        details={"task_id": str(task.id)},
    )
    return task


async def decide(
    db: AsyncSession,
    review: ReviewRequest,
    professional: Professional,
    *,
    decision: Decision,
    notes: str | None,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> ReviewDecision:
    _require(review, RS.IN_REVIEW)
    if decision != Decision.APPROVED and not notes:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "notes_required",
            "Tell the customer what to change, or why you are not approving.",
        )
    _move(review, DECISION_STATUS[decision])
    row = ReviewDecision(
        organisation_id=review.organisation_id,
        review_request_id=review.id,
        assessment_id=review.assessment_id,
        decision=decision,
        notes=notes,
        professional_id=professional.id,
        decided_by=actor_id,
    )
    db.add(row)
    if decision != Decision.CHANGES_REQUIRED:
        await _close(db, review, actor_id=actor_id, meta=meta)
    await db.flush()
    await _audit(
        db,
        "review.decided",
        review,
        actor_id=actor_id,
        meta=meta,
        details={"decision": decision, "assessment_id": str(review.assessment_id)},
    )
    return row
