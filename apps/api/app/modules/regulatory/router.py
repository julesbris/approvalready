"""``/v1/admin/source-*``: regulatory sources for staff (platform organisation active).

``source.manage`` captures and edits sources; ``source.verify`` verifies, disputes,
supersedes and reopens references.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import select

from app.api.deps import DbDep, MetaDep, OrgContext, require_platform_permission
from app.modules.identity.models import AppUser
from app.modules.regulatory import checks, service
from app.modules.regulatory.fetch import SourceFetcher
from app.modules.regulatory.models import (
    CheckOutcome,
    CheckTrigger,
    SourceCheck,
    SourceDocument,
    SourceOrganisation,
    SourceSnapshot,
    VerificationStatus,
)
from app.modules.regulatory.schemas import (
    ReviewEventOut,
    SnapshotCaptured,
    SnapshotCreate,
    SnapshotOut,
    SnapshotSummary,
    SourceCheckOut,
    SourceDocumentCreate,
    SourceDocumentOut,
    SourceDocumentUpdate,
    SourceOrganisationCreate,
    SourceOrganisationOut,
    SourceOrganisationUpdate,
    SourceReferenceCreate,
    SourceReferenceOut,
    SourceReferenceUpdate,
    SourceReview,
)
from app.modules.tenancy.rbac import Perm

router = APIRouter(prefix="/v1/admin", tags=["admin: sources"])

Manage = Annotated[OrgContext, Depends(require_platform_permission(Perm.SOURCE_MANAGE))]
Verify = Annotated[OrgContext, Depends(require_platform_permission(Perm.SOURCE_VERIFY))]


def _actor(ctx: OrgContext, meta: MetaDep | None) -> service.Actor:
    return service.Actor(ctx.auth.user.id, ctx.organisation.id, meta)


def _snapshot_summary(s: SourceSnapshot) -> SnapshotSummary:
    return SnapshotSummary(
        id=s.id,
        retrieved_at=s.retrieved_at,
        captured_at=s.captured_at,
        content_hash=s.content_hash.hex(),
        characters=len(s.content_text),
        capture_method=s.capture_method,
    )


def _check_out(c: SourceCheck) -> SourceCheckOut:
    return SourceCheckOut(
        id=c.id,
        checked_at=c.checked_at,
        trigger=c.trigger,
        outcome=c.outcome,
        outcome_label=checks.OUTCOME_LABELS[CheckOutcome(c.outcome)],
        url=c.url,
        final_url=c.final_url,
        http_status=c.http_status,
        content_type=c.content_type,
        size_bytes=c.size_bytes,
        snapshot_id=c.snapshot_id,
        error=c.error,
    )


async def _documents_out(
    db: DbDep, rows: list[tuple[SourceDocument, SourceOrganisation]]
) -> list[SourceDocumentOut]:
    ids = [d.id for d, _ in rows]
    snapshots = await service.latest_snapshots(db, ids)
    counts = await service.reference_counts(db, ids)
    last = await checks.latest_checks(db, ids)
    return [
        SourceDocumentOut(
            id=d.id,
            source_organisation_id=d.source_organisation_id,
            organisation_name=o.name,
            jurisdiction=d.jurisdiction,
            title=d.title,
            url=d.url,
            source_type=d.source_type,
            version_label=d.version_label,
            effective_from=d.effective_from,
            effective_to=d.effective_to,
            licence=d.licence,
            supersedes_id=d.supersedes_id,
            latest_snapshot=_snapshot_summary(snapshots[d.id]) if d.id in snapshots else None,
            auto_check=d.auto_check,
            last_check=_check_out(last[d.id]) if d.id in last else None,
            reference_counts=counts.get(d.id, {}),
            created_at=d.created_at,
            updated_at=d.updated_at,
        )
        for d, o in rows
    ]


def _reference_out(v: service.ReferenceView) -> SourceReferenceOut:
    r = v.reference
    return SourceReferenceOut(
        id=r.id,
        source_document_id=r.source_document_id,
        document_title=v.document.title,
        organisation_name=v.organisation.name,
        url=v.document.url,
        citation=service.citation(r, v.document),
        section=r.section,
        clause=r.clause,
        page=r.page,
        extracted_text=r.extracted_text,
        interpretation=r.interpretation,
        verification_status=r.verification_status,
        verified_by=r.verified_by,
        verified_at=r.verified_at,
        verified_snapshot_id=r.verified_snapshot_id,
        last_reviewed_at=r.last_reviewed_at,
        next_review_due=r.next_review_due,
        attention=service.attention(r, v.document, v.latest_snapshot_id, service.today()),
        allowed_actions=service.allowed_actions(r),
        rule_versions=v.rule_versions,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


# --- Organisations ---------------------------------------------------------------------


@router.get("/source-organisations", response_model=list[SourceOrganisationOut])
async def list_source_organisations(ctx: Manage, db: DbDep) -> list[SourceOrganisationOut]:
    return [
        SourceOrganisationOut.model_validate(o, from_attributes=True)
        for o in await service.list_organisations(db)
    ]


@router.post(
    "/source-organisations",
    status_code=status.HTTP_201_CREATED,
    response_model=SourceOrganisationOut,
)
async def create_source_organisation(
    body: SourceOrganisationCreate, ctx: Manage, db: DbDep, meta: MetaDep
) -> SourceOrganisationOut:
    org = await service.create_organisation(db, body.model_dump(), _actor(ctx, meta))
    await db.commit()
    return SourceOrganisationOut.model_validate(org, from_attributes=True)


@router.patch(
    "/source-organisations/{source_organisation_id}", response_model=SourceOrganisationOut
)
async def update_source_organisation(
    source_organisation_id: uuid.UUID,
    body: SourceOrganisationUpdate,
    ctx: Manage,
    db: DbDep,
    meta: MetaDep,
) -> SourceOrganisationOut:
    org = await service.get_organisation(db, source_organisation_id)
    await service.update_organisation(
        db, org, body.model_dump(exclude_unset=True), _actor(ctx, meta)
    )
    await db.commit()
    return SourceOrganisationOut.model_validate(org, from_attributes=True)


# --- Documents and snapshots -----------------------------------------------------------


@router.get("/source-documents", response_model=list[SourceDocumentOut])
async def list_source_documents(
    ctx: Manage, db: DbDep, source_organisation_id: uuid.UUID | None = None
) -> list[SourceDocumentOut]:
    return await _documents_out(db, await service.list_documents(db, source_organisation_id))


@router.post(
    "/source-documents", status_code=status.HTTP_201_CREATED, response_model=SourceDocumentOut
)
async def create_source_document(
    body: SourceDocumentCreate, ctx: Manage, db: DbDep, meta: MetaDep
) -> SourceDocumentOut:
    document = await service.create_document(db, body.model_dump(), _actor(ctx, meta))
    await db.commit()
    return (await _documents_out(db, [await service.get_document(db, document.id)]))[0]


@router.get("/source-documents/{document_id}", response_model=SourceDocumentOut)
async def get_source_document(document_id: uuid.UUID, ctx: Manage, db: DbDep) -> SourceDocumentOut:
    return (await _documents_out(db, [await service.get_document(db, document_id)]))[0]


@router.patch("/source-documents/{document_id}", response_model=SourceDocumentOut)
async def update_source_document(
    document_id: uuid.UUID, body: SourceDocumentUpdate, ctx: Manage, db: DbDep, meta: MetaDep
) -> SourceDocumentOut:
    document, org = await service.get_document(db, document_id)
    await service.update_document(
        db, document, body.model_dump(exclude_unset=True), _actor(ctx, meta)
    )
    await db.commit()
    return (await _documents_out(db, [(document, org)]))[0]


@router.get("/source-documents/{document_id}/snapshots", response_model=list[SnapshotSummary])
async def list_document_snapshots(
    document_id: uuid.UUID, ctx: Manage, db: DbDep
) -> list[SnapshotSummary]:
    document, _ = await service.get_document(db, document_id)
    return [_snapshot_summary(s) for s in await service.list_snapshots(db, document)]


@router.post("/source-documents/{document_id}/snapshots", response_model=SnapshotCaptured)
async def capture_document_snapshot(
    document_id: uuid.UUID, body: SnapshotCreate, ctx: Manage, db: DbDep, meta: MetaDep
) -> SnapshotCaptured:
    """Store the document's current content. Unchanged content returns the latest snapshot
    with ``changed: false``."""
    document, _ = await service.get_document(db, document_id)
    snapshot, changed = await service.capture_snapshot(
        db, document, body.content_text, body.retrieved_at, _actor(ctx, meta)
    )
    await db.commit()
    return SnapshotCaptured(
        **_snapshot_summary(snapshot).model_dump(),
        changed=changed,
        content_text=snapshot.content_text,
    )


@router.post(
    "/source-documents/{document_id}/check",
    status_code=status.HTTP_201_CREATED,
    response_model=SourceCheckOut,
)
async def check_source_document(
    document_id: uuid.UUID, request: Request, ctx: Manage, db: DbDep, meta: MetaDep
) -> SourceCheckOut:
    """Read the document from its official address now. A changed text is stored as a new
    snapshot; a failure is recorded with the reason."""
    document, _ = await service.get_document(db, document_id)
    fetcher: SourceFetcher = request.app.state.source_fetcher
    check = await checks.check_document(
        db,
        fetcher,
        document,
        trigger=CheckTrigger.MANUAL,
        requested_by=ctx.auth.user.id,
        organisation_id=ctx.organisation.id,
        meta=meta,
    )
    await db.commit()
    return _check_out(check)


@router.get("/source-documents/{document_id}/checks", response_model=list[SourceCheckOut])
async def list_source_checks(
    document_id: uuid.UUID, ctx: Manage, db: DbDep
) -> list[SourceCheckOut]:
    """The latest automatic and manual checks of the document, newest first."""
    document, _ = await service.get_document(db, document_id)
    return [_check_out(c) for c in await checks.list_checks(db, document)]


@router.get("/source-documents/{document_id}/snapshots/{snapshot_id}", response_model=SnapshotOut)
async def get_document_snapshot(
    document_id: uuid.UUID, snapshot_id: uuid.UUID, ctx: Manage, db: DbDep
) -> SnapshotOut:
    document, _ = await service.get_document(db, document_id)
    snapshot = await service.get_snapshot(db, document, snapshot_id)
    return SnapshotOut(
        **_snapshot_summary(snapshot).model_dump(), content_text=snapshot.content_text
    )


# --- References ------------------------------------------------------------------------


@router.get("/source-references", response_model=list[SourceReferenceOut])
async def list_source_references(
    ctx: Manage,
    db: DbDep,
    source_document_id: uuid.UUID | None = None,
    verification_status: VerificationStatus | None = None,
    needs_attention: Annotated[bool, Query()] = False,
) -> list[SourceReferenceOut]:
    """All references, or the review queue with ``needs_attention=true``."""
    views = await service.list_references(
        db,
        document_id=source_document_id,
        verification_status=verification_status,
        needs_attention=needs_attention,
    )
    return [_reference_out(v) for v in views]


@router.post(
    "/source-documents/{document_id}/references",
    status_code=status.HTTP_201_CREATED,
    response_model=SourceReferenceOut,
)
async def create_source_reference(
    document_id: uuid.UUID, body: SourceReferenceCreate, ctx: Manage, db: DbDep, meta: MetaDep
) -> SourceReferenceOut:
    document, _ = await service.get_document(db, document_id)
    ref = await service.create_reference(db, document, body.model_dump(), _actor(ctx, meta))
    await db.commit()
    return _reference_out(await service.get_reference(db, ref.id))


@router.get("/source-references/{reference_id}", response_model=SourceReferenceOut)
async def get_source_reference(
    reference_id: uuid.UUID, ctx: Manage, db: DbDep
) -> SourceReferenceOut:
    return _reference_out(await service.get_reference(db, reference_id))


@router.patch("/source-references/{reference_id}", response_model=SourceReferenceOut)
async def update_source_reference(
    reference_id: uuid.UUID, body: SourceReferenceUpdate, ctx: Manage, db: DbDep, meta: MetaDep
) -> SourceReferenceOut:
    view = await service.get_reference(db, reference_id)
    await service.update_reference(
        db, view.reference, body.model_dump(exclude_unset=True), _actor(ctx, meta)
    )
    await db.commit()
    return _reference_out(await service.get_reference(db, reference_id))


@router.post("/source-references/{reference_id}/review", response_model=SourceReferenceOut)
async def review_source_reference(
    reference_id: uuid.UUID, body: SourceReview, ctx: Verify, db: DbDep, meta: MetaDep
) -> SourceReferenceOut:
    view = await service.get_reference(db, reference_id)
    await service.review_reference(
        db,
        view,
        body.action,
        notes=body.notes,
        next_review_due=body.next_review_due,
        actor=_actor(ctx, meta),
    )
    await db.commit()
    return _reference_out(await service.get_reference(db, reference_id))


@router.get("/source-references/{reference_id}/events", response_model=list[ReviewEventOut])
async def list_source_reference_events(
    reference_id: uuid.UUID, ctx: Manage, db: DbDep
) -> list[ReviewEventOut]:
    view = await service.get_reference(db, reference_id)
    events = await service.review_events(db, view.reference)
    reviewer_ids = {e.reviewer_id for e in events if e.reviewer_id}
    names = (
        dict(
            (
                await db.execute(
                    select(AppUser.id, AppUser.display_name).where(AppUser.id.in_(reviewer_ids))
                )
            ).all()
        )
        if reviewer_ids
        else {}
    )
    return [
        ReviewEventOut(
            id=e.id,
            action=e.action,
            from_status=e.from_status,
            to_status=e.to_status,
            reviewer_id=e.reviewer_id,
            reviewer_name=names.get(e.reviewer_id) if e.reviewer_id else None,
            notes=e.notes,
            occurred_at=e.occurred_at,
        )
        for e in events
    ]
