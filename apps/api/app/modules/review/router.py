"""Professional review routes.

* ``/v1/organisations/{id}/...``: the customer requests, follows and answers a review.
* ``/v1/professional/...``: a professional's profile and their assigned reviews. These act
  from the practice: the session's active organisation must be a ``PROFESSIONAL_PRACTICE``
  where the user holds ``review.perform``.
* ``/v1/admin/professionals``, ``/v1/admin/reviews``: staff verify professionals and assign
  reviews (``professional.verify``, ``review.assign``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select

from app.api.deps import (
    AuthContext,
    AuthDep,
    DbDep,
    MetaDep,
    OrgContext,
    ResourcesDep,
    SettingsDep,
    require_org_permission,
    require_platform_permission,
)
from app.core.config import Settings
from app.core.errors import ApiError, forbidden, not_found
from app.core.resources import Resources
from app.modules.assessments import service as assessments
from app.modules.assessments.router import assessment_detail
from app.modules.billing import service as billing
from app.modules.billing.models import Payment
from app.modules.billing.router import StripeDep
from app.modules.documents import service as documents
from app.modules.documents.router import _download, document_out, evidence_out
from app.modules.identity import service as identity
from app.modules.identity.models import AppUser
from app.modules.projects import service as projects
from app.modules.projects.models import Project, Task, TaskSource
from app.modules.projects.router import _task_out
from app.modules.review import emails, professionals, service
from app.modules.review.models import (
    AuthorRole,
    Professional,
    ProfessionalStatus,
    ReviewRequest,
)
from app.modules.review.models import ReviewRequestStatus as RS
from app.modules.review.professionals import ProfessionalView
from app.modules.review.schemas import (
    AssessmentReviewOut,
    AssignIn,
    CheckoutOut,
    CommentIn,
    CommentOut,
    CredentialCheckIn,
    CredentialIn,
    CredentialOut,
    DecisionIn,
    DecisionOut,
    DeclineIn,
    EvidenceCheckIn,
    OverrideIn,
    OverrideOut,
    OverrideSourceOut,
    ProfessionalOut,
    ProfessionalPublicOut,
    ProfessionalStatusIn,
    ProfileIn,
    ProfileUpdateIn,
    QueueItemOut,
    ResubmitIn,
    ReviewerWorkspaceOut,
    ReviewOut,
    ReviewPaymentOut,
    ReviewRequestIn,
    ReviewSummary,
    ReviewTaskIn,
    ServiceOut,
    ServicesIn,
    StaffReviewOut,
)
from app.modules.tenancy import service as tenancy
from app.modules.tenancy.models import Organisation, OrganisationKind
from app.modules.tenancy.rbac import Perm

customer_router = APIRouter(prefix="/v1/organisations/{organisation_id}", tags=["review"])
professional_router = APIRouter(prefix="/v1/professional", tags=["review"])
admin_router = APIRouter(prefix="/v1/admin", tags=["review"])

Read = Annotated[OrgContext, Depends(require_org_permission(Perm.PROJECT_READ))]
Write = Annotated[OrgContext, Depends(require_org_permission(Perm.PROJECT_WRITE))]
Verify = Annotated[OrgContext, Depends(require_platform_permission(Perm.PROFESSIONAL_VERIFY))]
Assign = Annotated[OrgContext, Depends(require_platform_permission(Perm.REVIEW_ASSIGN))]


# --- Output ----------------------------------------------------------------------------


def public_out(v: ProfessionalView) -> ProfessionalPublicOut:
    return ProfessionalPublicOut(
        id=v.professional.id,
        display_name=v.professional.display_name,
        discipline=v.professional.discipline,
        practice_name=v.practice.name,
    )


def professional_out(v: ProfessionalView) -> ProfessionalOut:
    today = assessments.assessment_date()
    return ProfessionalOut(
        **public_out(v).model_dump(),
        user_id=v.professional.user_id,
        practice_id=v.professional.practice_id,
        email=v.user.email,
        bio=v.professional.bio,
        status=v.professional.status,
        credentials=[
            CredentialOut(
                id=c.id,
                kind=c.kind,
                issuer=c.issuer,
                number=c.number,
                expires_on=c.expires_on,
                status=c.status,
                notes=c.notes,
                verified_at=c.verified_at,
                current=professionals.credential_current(c, today),
            )
            for c in v.credentials
        ],
        services=[ServiceOut(vertical=s.vertical, description=s.description) for s in v.services],
        problems=professionals.eligibility(v, None, today),
        created_at=v.professional.created_at,
    )


def summary_out(r: ReviewRequest, professional: ProfessionalView | None) -> ReviewSummary:
    return ReviewSummary(
        id=r.id,
        project_id=r.project_id,
        assessment_id=r.assessment_id,
        status=r.status,
        message=r.message,
        professional=public_out(professional) if professional else None,
        due_on=r.due_on,
        created_at=r.created_at,
        assigned_at=r.assigned_at,
        started_at=r.started_at,
        closed_at=r.closed_at,
    )


def overrides_out(rows: list[service.OverrideRow]) -> list[OverrideOut]:
    current = {row.override.id for row in service.current_overrides(rows).values()}
    return [
        OverrideOut(
            id=row.override.id,
            review_request_id=row.override.review_request_id,
            finding_id=row.override.finding_id,
            previous_outcome_type=row.override.previous_outcome_type,
            previous_confidence=row.override.previous_confidence,
            new_outcome_type=row.override.new_outcome_type,
            new_confidence=row.override.new_confidence,
            reason=row.override.reason,
            source=OverrideSourceOut(
                id=row.source.id,
                citation=row.citation or "",
                verification_status=row.source.verification_status,
            )
            if row.source
            else None,
            overridden_by_name=row.author_name,
            created_at=row.override.created_at,
            current=row.override.id in current,
        )
        for row in rows
    ]


def payment_out(payment: Payment | None) -> ReviewPaymentOut | None:
    if payment is None:
        return None
    return ReviewPaymentOut(
        id=payment.id,
        status=payment.status,
        amount_cents=payment.amount_cents,
        currency=payment.currency,
        paid_at=payment.paid_at,
    )


def review_out(v: service.ReviewView) -> ReviewOut:
    return ReviewOut(
        **summary_out(v.review, v.professional).model_dump(exclude={"payment"}),
        payment=payment_out(v.payment),
        project_title=v.project.title,
        project_reference=v.project.reference_code,
        vertical=v.project.vertical,
        comments=[
            CommentOut(
                id=c.comment.id,
                finding_id=c.comment.finding_id,
                author_name=c.author_name,
                author_role=c.comment.author_role,
                body=c.comment.body,
                created_at=c.comment.created_at,
            )
            for c in v.comments
        ],
        overrides=overrides_out(v.overrides),
        decisions=[
            DecisionOut(
                id=d.id,
                assessment_id=d.assessment_id,
                decision=d.decision,
                notes=d.notes,
                created_at=d.created_at,
            )
            for d in v.decisions
        ],
    )


async def _reload(db: DbDep, review: ReviewRequest) -> ReviewOut:
    organisation_id, review_id = review.organisation_id, review.id
    db.expire_all()
    fresh = await service.get_review(db, organisation_id, review_id)
    return review_out(await service.build_view(db, fresh))


async def _user(db: DbDep, user_id: uuid.UUID | None) -> AppUser | None:
    return await db.get(AppUser, user_id) if user_id else None


# --- Customer --------------------------------------------------------------------------


@customer_router.post(
    "/projects/{project_id}/reviews", status_code=status.HTTP_201_CREATED, response_model=ReviewOut
)
async def request_review(
    project_id: uuid.UUID,
    body: ReviewRequestIn,
    ctx: Write,
    db: DbDep,
    meta: MetaDep,
    settings: SettingsDep,
) -> ReviewOut:
    """Ask a professional to check the project's latest assessment. When reviews have a
    price, the review waits in ``PAYMENT_PENDING``: send the customer to ``/checkout``."""
    project = await projects.get_project(db, ctx.organisation.id, project_id)
    price = await billing.review_price(db, project.vertical) if settings.payments_enabled else None
    review = await service.request_review(
        db,
        project,
        assessment_id=body.assessment_id,
        message=body.message,
        actor_id=ctx.auth.user.id,
        meta=meta,
        price=price,
    )
    await db.commit()
    return await _reload(db, review)


@customer_router.post("/reviews/{review_id}/checkout", response_model=CheckoutOut)
async def review_checkout(
    review_id: uuid.UUID,
    ctx: Write,
    db: DbDep,
    settings: SettingsDep,
    stripe: StripeDep,
) -> CheckoutOut:
    """A Stripe Checkout page to pay for a review that is waiting for payment."""
    review = await service.get_review(db, ctx.organisation.id, review_id, lock=True)
    if review.status != RS.PAYMENT_PENDING or review.payment_id is None:
        raise ApiError(409, "payment_not_pending", "This review doesn't need paying for.")
    if stripe is None:
        raise ApiError(409, "payments_disabled", "Payments are switched off on this server.")
    payment = await billing.get_payment(db, ctx.organisation.id, review.payment_id, lock=True)
    back = (
        f"{settings.web_base_url}/projects/{review.project_id}/assessments/{review.assessment_id}"
    )
    url = await billing.checkout_for_payment(
        db,
        stripe,
        organisation=ctx.organisation,
        user=ctx.auth.user,
        payment=payment,
        success_url=f"{back}?payment=done",
        cancel_url=f"{back}?payment=cancelled",
    )
    await db.commit()
    return CheckoutOut(url=url)


@customer_router.get("/projects/{project_id}/reviews", response_model=list[ReviewSummary])
async def list_reviews(project_id: uuid.UUID, ctx: Read, db: DbDep) -> list[ReviewSummary]:
    project = await projects.get_project(db, ctx.organisation.id, project_id)
    result = []
    for r in await service.list_for_project(db, project):
        professional = (
            await professionals.view(
                db, await professionals.get_professional(db, r.assigned_professional_id)
            )
            if r.assigned_professional_id
            else None
        )
        result.append(summary_out(r, professional))
    return result


@customer_router.get("/reviews/{review_id}", response_model=ReviewOut)
async def get_review(review_id: uuid.UUID, ctx: Read, db: DbDep) -> ReviewOut:
    review = await service.get_review(db, ctx.organisation.id, review_id)
    return review_out(await service.build_view(db, review))


@customer_router.get("/assessments/{assessment_id}/review", response_model=AssessmentReviewOut)
async def assessment_review(assessment_id: uuid.UUID, ctx: Read, db: DbDep) -> AssessmentReviewOut:
    """The assessment's review status, the review on it and every reviewer change to its
    findings (shown next to the original findings)."""
    assessment, _, findings = await assessments.get(db, ctx.organisation.id, assessment_id)
    review_status, review, _ = await service.review_status_for(db, assessment)
    if review is None:
        review = (
            await db.execute(
                select(ReviewRequest)
                .where(ReviewRequest.assessment_id == assessment.id)
                .order_by(ReviewRequest.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    return AssessmentReviewOut(
        review_status=review_status,
        review=review_out(await service.build_view(db, review)) if review else None,
        overrides=overrides_out(await service.overrides_for_findings(db, [f.id for f in findings])),
    )


@customer_router.post("/reviews/{review_id}/comments", response_model=ReviewOut)
async def customer_comment(
    review_id: uuid.UUID, body: CommentIn, ctx: Write, db: DbDep, meta: MetaDep
) -> ReviewOut:
    review = await service.get_review(db, ctx.organisation.id, review_id, lock=True)
    await service.add_comment(
        db,
        review,
        body=body.body,
        finding_id=body.finding_id,
        role=AuthorRole.CUSTOMER,
        actor_id=ctx.auth.user.id,
        meta=meta,
    )
    await db.commit()
    return await _reload(db, review)


@customer_router.post("/reviews/{review_id}/cancel", response_model=ReviewOut)
async def cancel_review(
    review_id: uuid.UUID, ctx: Write, db: DbDep, meta: MetaDep, stripe: StripeDep
) -> ReviewOut:
    review = await service.get_review(db, ctx.organisation.id, review_id, lock=True)
    unpaid = await service.cancel(db, review, actor_id=ctx.auth.user.id, meta=meta)
    await db.commit()
    if unpaid is not None and unpaid.stripe_checkout_session_id and stripe is not None:
        await billing.close_checkout(stripe, unpaid.stripe_checkout_session_id)
    return await _reload(db, review)


@customer_router.post("/reviews/{review_id}/resubmit", response_model=ReviewOut)
async def resubmit_review(
    review_id: uuid.UUID,
    body: ResubmitIn,
    ctx: Write,
    db: DbDep,
    meta: MetaDep,
    settings: SettingsDep,
    resources: ResourcesDep,
) -> ReviewOut:
    """Hand the review back to the reviewer after making the changes they asked for."""
    review = await service.get_review(db, ctx.organisation.id, review_id, lock=True)
    await service.resubmit(
        db, review, assessment_id=body.assessment_id, actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    out = await _reload(db, review)
    if review.assigned_professional_id:
        v = await professionals.view(
            db, await professionals.get_professional(db, review.assigned_professional_id)
        )
        await identity.send_email(
            resources.email,
            emails.review_resubmitted(
                settings,
                v.user.email,
                v.professional.display_name,
                review.id,
                out.project_reference,
            ),
        )
    return out


# --- Professional: profile -------------------------------------------------------------


@dataclass
class PracticeContext:
    auth: AuthContext
    practice: Organisation


async def get_practice(auth: AuthDep, db: DbDep) -> PracticeContext:
    active = auth.session.active_organisation_id
    found = await tenancy.membership(db, auth.user.id, active) if active else None
    if (
        found is None
        or found.organisation.kind != OrganisationKind.PROFESSIONAL_PRACTICE
        or Perm.REVIEW_PERFORM not in found.permissions
    ):
        raise forbidden("Switch to the practice you review for.")
    return PracticeContext(auth, found.organisation)


PracticeDep = Annotated[PracticeContext, Depends(get_practice)]


@dataclass
class ReviewerContext:
    auth: AuthContext
    practice: Organisation
    professional: Professional


async def get_reviewer(ctx: PracticeDep, db: DbDep) -> ReviewerContext:
    professional = await professionals.own_profile(db, ctx.auth.user.id, ctx.practice.id)
    if professional is None or professional.status != ProfessionalStatus.ACTIVE:
        raise forbidden("Your reviewer profile isn't active yet.")
    return ReviewerContext(ctx.auth, ctx.practice, professional)


ReviewerDep = Annotated[ReviewerContext, Depends(get_reviewer)]


async def _own(ctx: PracticeContext, db: DbDep, *, lock: bool = False) -> Professional:
    professional = await professionals.own_profile(db, ctx.auth.user.id, ctx.practice.id, lock=lock)
    if professional is None:
        raise not_found("Reviewer profile")
    return professional


@professional_router.get("/profile", response_model=ProfessionalOut)
async def get_profile(ctx: PracticeDep, db: DbDep) -> ProfessionalOut:
    return professional_out(await professionals.view(db, await _own(ctx, db)))


@professional_router.post(
    "/profile", status_code=status.HTTP_201_CREATED, response_model=ProfessionalOut
)
async def create_profile(
    body: ProfileIn, ctx: PracticeDep, db: DbDep, meta: MetaDep
) -> ProfessionalOut:
    """Set up your reviewer profile in this practice. Staff check your credentials and
    activate it before you are assigned reviews."""
    professional = await professionals.create_profile(
        db, user_id=ctx.auth.user.id, practice=ctx.practice, data=body.model_dump(), meta=meta
    )
    await db.commit()
    return professional_out(await professionals.view(db, professional))


@professional_router.patch("/profile", response_model=ProfessionalOut)
async def update_profile(
    body: ProfileUpdateIn, ctx: PracticeDep, db: DbDep, meta: MetaDep
) -> ProfessionalOut:
    professional = await _own(ctx, db, lock=True)
    await professionals.update_profile(
        db,
        professional,
        body.model_dump(exclude_unset=True),
        actor_id=ctx.auth.user.id,
        meta=meta,
    )
    await db.commit()
    return professional_out(await professionals.view(db, professional))


@professional_router.post(
    "/profile/credentials", status_code=status.HTTP_201_CREATED, response_model=ProfessionalOut
)
async def add_credential(
    body: CredentialIn, ctx: PracticeDep, db: DbDep, meta: MetaDep
) -> ProfessionalOut:
    professional = await _own(ctx, db, lock=True)
    await professionals.add_credential(
        db, professional, body.model_dump(), actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    return professional_out(await professionals.view(db, professional))


@professional_router.delete(
    "/profile/credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_credential(
    credential_id: uuid.UUID, ctx: PracticeDep, db: DbDep, meta: MetaDep
) -> Response:
    professional = await _own(ctx, db, lock=True)
    await professionals.remove_credential(
        db, professional, credential_id, actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@professional_router.put("/profile/services", response_model=ProfessionalOut)
async def set_services(
    body: ServicesIn, ctx: PracticeDep, db: DbDep, meta: MetaDep
) -> ProfessionalOut:
    """The kinds of project you review (replaces the list)."""
    professional = await _own(ctx, db, lock=True)
    await professionals.set_services(
        db,
        professional,
        [s.model_dump() for s in body.services],
        actor_id=ctx.auth.user.id,
        meta=meta,
    )
    await db.commit()
    return professional_out(await professionals.view(db, professional))


# --- Professional: reviews -------------------------------------------------------------


def _queue_out(rows: list[service.QueueRow]) -> list[QueueItemOut]:
    return [
        QueueItemOut(
            id=r.id,
            status=r.status,
            project_reference=r.project_reference,
            project_title=r.project_title,
            vertical=r.vertical,
            assigned_professional_id=r.assigned_professional_id,
            created_at=r.created_at,
            due_on=r.due_on,
        )
        for r in rows
    ]


@professional_router.get("/reviews", response_model=list[QueueItemOut])
async def my_reviews(ctx: ReviewerDep, db: DbDep) -> list[QueueItemOut]:
    rows = await service.queue(db, professional_id=ctx.professional.id)
    return _queue_out([r for r in rows if r.status in service.REVIEWER_VISIBLE])


async def _assigned(
    db: DbDep, ctx: ReviewerContext, review_id: uuid.UUID, *, lock: bool = False
) -> ReviewRequest:
    organisation_id = await service.bind_review(db, review_id)
    review = await service.get_review(db, organisation_id, review_id, lock=lock)
    service.require_assigned(review, ctx.professional)
    return review


async def _workspace(db: DbDep, review: ReviewRequest) -> ReviewerWorkspaceOut:
    organisation_id, review_id = review.organisation_id, review.id
    db.expire_all()
    review = await service.get_review(db, organisation_id, review_id)
    # What the customer paid is between them and us.
    view = replace(await service.build_view(db, review), payment=None)
    a, p, findings = await assessments.get(db, review.organisation_id, review.assessment_id)
    shared, evidence = await service.reviewable_documents(db, review)
    tasks = (
        await db.execute(
            select(Task)
            .where(
                Task.project_id == review.project_id,
                Task.source == TaskSource.REVIEWER,
                Task.deleted_at.is_(None),
            )
            .order_by(Task.created_at)
        )
    ).scalars()
    return ReviewerWorkspaceOut(
        review=review_out(view),
        project_status=view.project.status,
        assessment=await assessment_detail(db, a, p, findings),
        shared_documents=[document_out(d) for d in shared],
        evidence=[evidence_out(row) for row in evidence],
        tasks=[_task_out(t) for t in tasks],
    )


@professional_router.get("/reviews/{review_id}", response_model=ReviewerWorkspaceOut)
async def review_workspace(
    review_id: uuid.UUID, ctx: ReviewerDep, db: DbDep
) -> ReviewerWorkspaceOut:
    """The review with the assessment, the customer's answers and the files they shared."""
    return await _workspace(db, await _assigned(db, ctx, review_id))


@professional_router.get(
    "/reviews/{review_id}/documents/{document_id}/content",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}, 303: {}},
)
async def review_document(
    review_id: uuid.UUID,
    document_id: uuid.UUID,
    ctx: ReviewerDep,
    db: DbDep,
    meta: MetaDep,
    resources: ResourcesDep,
) -> Response:
    review = await _assigned(db, ctx, review_id)
    document = await service.reviewable_document(db, review, document_id)
    documents.require_clean(document)
    await documents.record_download(
        db,
        target_type="uploaded_document",
        target_id=document.id,
        organisation_id=review.organisation_id,
        actor_id=ctx.auth.user.id,
        meta=meta,
    )
    await db.commit()
    return await _download(
        resources, document.storage_key, document.original_filename, document.detected_mime
    )


@professional_router.post("/reviews/{review_id}/decline", response_model=list[QueueItemOut])
async def decline_review(
    review_id: uuid.UUID, body: DeclineIn, ctx: ReviewerDep, db: DbDep, meta: MetaDep
) -> list[QueueItemOut]:
    """Hand back a review you can't take on (before starting it)."""
    review = await _assigned(db, ctx, review_id, lock=True)
    await service.unassign(
        db,
        review,
        reason=body.reason,
        action="review.declined",
        actor_id=ctx.auth.user.id,
        meta=meta,
    )
    await db.commit()
    return await my_reviews(ctx, db)


@professional_router.post("/reviews/{review_id}/start", response_model=ReviewerWorkspaceOut)
async def start_review(
    review_id: uuid.UUID, ctx: ReviewerDep, db: DbDep, meta: MetaDep
) -> ReviewerWorkspaceOut:
    review = await _assigned(db, ctx, review_id, lock=True)
    await service.start(db, review, actor_id=ctx.auth.user.id, meta=meta)
    await db.commit()
    return await _workspace(db, review)


@professional_router.post("/reviews/{review_id}/comments", response_model=ReviewerWorkspaceOut)
async def reviewer_comment(
    review_id: uuid.UUID, body: CommentIn, ctx: ReviewerDep, db: DbDep, meta: MetaDep
) -> ReviewerWorkspaceOut:
    review = await _assigned(db, ctx, review_id, lock=True)
    await service.add_comment(
        db,
        review,
        body=body.body,
        finding_id=body.finding_id,
        role=AuthorRole.REVIEWER,
        actor_id=ctx.auth.user.id,
        meta=meta,
    )
    await db.commit()
    return await _workspace(db, review)


@professional_router.post("/reviews/{review_id}/overrides", response_model=ReviewerWorkspaceOut)
async def override_finding(
    review_id: uuid.UUID, body: OverrideIn, ctx: ReviewerDep, db: DbDep, meta: MetaDep
) -> ReviewerWorkspaceOut:
    """Change a finding's outcome or confidence, with a reason (audited; the original stays
    on record)."""
    review = await _assigned(db, ctx, review_id, lock=True)
    await service.override_finding(
        db,
        review,
        finding_id=body.finding_id,
        new_outcome_type=body.new_outcome_type,
        new_confidence=body.new_confidence,
        reason=body.reason,
        source_reference_id=body.source_reference_id,
        actor_id=ctx.auth.user.id,
        meta=meta,
    )
    await db.commit()
    return await _workspace(db, review)


@professional_router.post(
    "/reviews/{review_id}/evidence/{evidence_id}", response_model=ReviewerWorkspaceOut
)
async def check_evidence(
    review_id: uuid.UUID,
    evidence_id: uuid.UUID,
    body: EvidenceCheckIn,
    ctx: ReviewerDep,
    db: DbDep,
    meta: MetaDep,
) -> ReviewerWorkspaceOut:
    review = await _assigned(db, ctx, review_id, lock=True)
    await service.check_evidence(
        db,
        review,
        evidence_id,
        new_status=body.status,
        note=body.note,
        actor_id=ctx.auth.user.id,
        meta=meta,
    )
    await db.commit()
    return await _workspace(db, review)


@professional_router.post("/reviews/{review_id}/tasks", response_model=ReviewerWorkspaceOut)
async def add_task(
    review_id: uuid.UUID, body: ReviewTaskIn, ctx: ReviewerDep, db: DbDep, meta: MetaDep
) -> ReviewerWorkspaceOut:
    """Add a task to the customer's project."""
    review = await _assigned(db, ctx, review_id, lock=True)
    await service.add_task(
        db, review, title=body.title, notes=body.notes, actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    return await _workspace(db, review)


async def _notify_decision(
    db: DbDep, settings: Settings, resources: Resources, review: ReviewRequest, decision: str
) -> None:
    requester = await _user(db, review.created_by)
    project = await db.get(Project, review.project_id)
    if requester is None or project is None:
        return
    await identity.send_email(
        resources.email,
        emails.review_decided(
            settings,
            requester.email,
            requester.display_name,
            decision,
            project.id,
            review.assessment_id,
            project.reference_code,
        ),
    )


@professional_router.post("/reviews/{review_id}/decision", response_model=ReviewerWorkspaceOut)
async def decide(
    review_id: uuid.UUID,
    body: DecisionIn,
    ctx: ReviewerDep,
    db: DbDep,
    meta: MetaDep,
    settings: SettingsDep,
    resources: ResourcesDep,
) -> ReviewerWorkspaceOut:
    """Approve, finish with comments, or ask the customer for changes."""
    review = await _assigned(db, ctx, review_id, lock=True)
    await service.decide(
        db,
        review,
        ctx.professional,
        decision=body.decision,
        notes=body.notes,
        actor_id=ctx.auth.user.id,
        meta=meta,
    )
    await db.commit()
    out = await _workspace(db, review)
    await _notify_decision(db, settings, resources, review, body.decision)
    return out


# --- Staff -----------------------------------------------------------------------------


@admin_router.get("/professionals", response_model=list[ProfessionalOut])
async def list_professionals(
    ctx: Verify,
    db: DbDep,
    status_filter: Annotated[ProfessionalStatus | None, Query(alias="status")] = None,
) -> list[ProfessionalOut]:
    found = await professionals.list_professionals(db, status_filter)
    return [professional_out(v) for v in await professionals.views(db, found)]


@admin_router.get("/professionals/{professional_id}", response_model=ProfessionalOut)
async def get_professional(professional_id: uuid.UUID, ctx: Verify, db: DbDep) -> ProfessionalOut:
    return professional_out(
        await professionals.view(db, await professionals.get_professional(db, professional_id))
    )


@admin_router.post(
    "/professionals/{professional_id}/credentials/{credential_id}",
    response_model=ProfessionalOut,
)
async def check_credential(
    professional_id: uuid.UUID,
    credential_id: uuid.UUID,
    body: CredentialCheckIn,
    ctx: Verify,
    db: DbDep,
    meta: MetaDep,
) -> ProfessionalOut:
    """Record that a credential was checked against the issuer's register (or rejected)."""
    professional = await professionals.get_professional(db, professional_id, lock=True)
    await professionals.check_credential(
        db,
        professional,
        credential_id,
        body.status,
        body.notes,
        actor_id=ctx.auth.user.id,
        meta=meta,
    )
    await db.commit()
    return professional_out(await professionals.view(db, professional))


@admin_router.post("/professionals/{professional_id}/status", response_model=ProfessionalOut)
async def set_professional_status(
    professional_id: uuid.UUID,
    body: ProfessionalStatusIn,
    ctx: Verify,
    db: DbDep,
    meta: MetaDep,
) -> ProfessionalOut:
    professional = await professionals.get_professional(db, professional_id, lock=True)
    await professionals.set_status(
        db,
        professional,
        body.status,
        actor_id=ctx.auth.user.id,
        meta=meta,
        on=assessments.assessment_date(),
    )
    await db.commit()
    return professional_out(await professionals.view(db, professional))


@admin_router.get("/reviews", response_model=list[QueueItemOut])
async def review_queue(
    ctx: Assign,
    db: DbDep,
    status_filter: Annotated[list[RS] | None, Query(alias="status")] = None,
) -> list[QueueItemOut]:
    statuses = [str(s) for s in status_filter] if status_filter else None
    return _queue_out(await service.queue(db, statuses=statuses))


async def _staff_view(db: DbDep, review: ReviewRequest) -> StaffReviewOut:
    organisation_id, review_id = review.organisation_id, review.id
    db.expire_all()
    review = await service.get_review(db, organisation_id, review_id)
    project = await db.get(Project, review.project_id)
    assert project is not None
    a, _, _ = await assessments.get(db, review.organisation_id, review.assessment_id)
    professional = (
        await professionals.view(
            db, await professionals.get_professional(db, review.assigned_professional_id)
        )
        if review.assigned_professional_id
        else None
    )
    candidates = await professionals.eligible_for(
        db, project.vertical, assessments.assessment_date()
    )
    candidates = [
        c
        for c in candidates
        if await tenancy.membership(db, c.professional.user_id, review.organisation_id) is None
    ]
    return StaffReviewOut(
        review=summary_out(review, professional),
        project_title=project.title,
        project_reference=project.reference_code,
        vertical=project.vertical,
        rule_sets_in_scope=[rs["title"] for rs in a.rule_sets if rs.get("scope") == "IN_SCOPE"],
        candidates=[professional_out(c) for c in candidates],
    )


async def _staff_review(db: DbDep, review_id: uuid.UUID, *, lock: bool = False) -> ReviewRequest:
    organisation_id = await service.bind_review(db, review_id)
    return await service.get_review(db, organisation_id, review_id, lock=lock)


@admin_router.get("/reviews/{review_id}", response_model=StaffReviewOut)
async def staff_review(review_id: uuid.UUID, ctx: Assign, db: DbDep) -> StaffReviewOut:
    """A review request with the professionals who could take it. Staff see the project's
    name and what was assessed, not the customer's answers or files."""
    return await _staff_view(db, await _staff_review(db, review_id))


@admin_router.post("/reviews/{review_id}/assign", response_model=StaffReviewOut)
async def assign_review(
    review_id: uuid.UUID,
    body: AssignIn,
    ctx: Assign,
    db: DbDep,
    meta: MetaDep,
    settings: SettingsDep,
    resources: ResourcesDep,
) -> StaffReviewOut:
    review = await _staff_review(db, review_id, lock=True)
    professional = await professionals.get_professional(db, body.professional_id)
    await service.assign(
        db,
        review,
        professional,
        due_on=body.due_on,
        actor_id=ctx.auth.user.id,
        meta=meta,
        on=assessments.assessment_date(),
    )
    await db.commit()
    out = await _staff_view(db, review)
    v = await professionals.view(db, professional)
    await identity.send_email(
        resources.email,
        emails.review_assigned(
            settings, v.user.email, professional.display_name, review.id, out.project_reference
        ),
    )
    return out


@admin_router.post("/reviews/{review_id}/unassign", response_model=StaffReviewOut)
async def unassign_review(
    review_id: uuid.UUID, body: DeclineIn, ctx: Assign, db: DbDep, meta: MetaDep
) -> StaffReviewOut:
    """Take a review back from a professional who hasn't started it."""
    review = await _staff_review(db, review_id, lock=True)
    await service.unassign(
        db,
        review,
        reason=body.reason,
        action="review.unassigned",
        actor_id=ctx.auth.user.id,
        meta=meta,
    )
    await db.commit()
    return await _staff_view(db, review)
