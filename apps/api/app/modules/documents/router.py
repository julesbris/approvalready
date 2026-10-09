"""``/v1/organisations/{organisation_id}``: uploads, evidence and generated reports.

Downloads are always ``Content-Disposition: attachment`` with a sandboxing CSP, so a file
is never rendered as a page of our origin. With object storage the API answers with a
redirect to a short-lived signed URL; with local storage it streams the file itself.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable
from typing import Annotated

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from fastapi.responses import RedirectResponse

from app.api.deps import (
    DbDep,
    LimiterDep,
    MetaDep,
    OrgContext,
    ResourcesDep,
    SettingsDep,
    require_org_permission,
)
from app.core.errors import ApiError, rate_limited
from app.core.ratelimit import Limit
from app.modules.assessments import service as assessments
from app.modules.documents import filetypes, service
from app.modules.documents.models import (
    GeneratedDocument,
    GenerationStatus,
    OutputFormat,
    UploadedDocument,
)
from app.modules.documents.schemas import (
    DocumentOut,
    EvidenceIn,
    EvidenceOut,
    GeneratedDocumentOut,
    GenerateIn,
    UploadLimitsOut,
)
from app.modules.documents.service import MIME_TYPES
from app.modules.documents.storage import StorageError, content_disposition
from app.modules.projects import service as projects
from app.modules.tenancy.rbac import Perm

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/organisations/{organisation_id}", tags=["documents"])

Read = Annotated[OrgContext, Depends(require_org_permission(Perm.PROJECT_READ))]
Write = Annotated[OrgContext, Depends(require_org_permission(Perm.PROJECT_WRITE))]

DOWNLOAD_HEADERS = {
    "cache-control": "private, no-store",
    "x-content-type-options": "nosniff",
    "content-security-policy": "default-src 'none'; sandbox",
}
GENERATIONS_PER_USER_PER_HOUR = 30


def document_out(d: UploadedDocument) -> DocumentOut:
    return DocumentOut(
        id=d.id,
        project_id=d.project_id,
        filename=d.original_filename,
        content_type=d.detected_mime,
        size_bytes=d.size_bytes,
        scan_status=d.scan_status,
        created_at=d.created_at,
        created_by=d.created_by,
    )


def generated_out(g: GeneratedDocument) -> GeneratedDocumentOut:
    return GeneratedDocumentOut(
        id=g.id,
        project_id=g.project_id,
        assessment_id=g.assessment_id,
        format=g.format,
        status=g.status,
        review_status=g.review_status,
        filename=g.filename,
        size_bytes=g.size_bytes,
        sha256=g.sha256.hex() if g.sha256 else None,
        error=g.error,
        created_at=g.created_at,
        completed_at=g.completed_at,
    )


async def _dispatch(kind: str, call: Awaitable[None]) -> None:
    """Queue background work after commit. If the queue is down the scheduler's sweep
    re-queues the job later, so the request still succeeds."""
    try:
        await call
    except Exception:
        log.exception("could not queue %s job", kind)


async def _download(
    resources: ResourcesDep, key: str, filename: str, content_type: str
) -> Response:
    signed = await resources.storage.signed_download_url(key, filename, content_type)
    if signed:
        return RedirectResponse(signed, status_code=status.HTTP_303_SEE_OTHER)
    try:
        data = await resources.storage.get(key)
    except StorageError:
        raise ApiError(
            status.HTTP_410_GONE, "content_missing", "This file is no longer available."
        ) from None
    return Response(
        content=data,
        media_type=content_type,
        headers={"content-disposition": content_disposition(filename), **DOWNLOAD_HEADERS},
    )


# --- Uploads ---------------------------------------------------------------------------


@router.get("/upload-limits", response_model=UploadLimitsOut)
async def upload_limits(ctx: Read, settings: SettingsDep) -> UploadLimitsOut:
    return UploadLimitsOut(
        max_bytes=settings.upload_max_bytes,
        extensions=filetypes.ALLOWED_EXTENSIONS,
        accept=",".join(f".{e}" for e in filetypes.ALLOWED_EXTENSIONS),
    )


@router.post(
    "/projects/{project_id}/documents",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentOut,
)
async def upload_document(
    project_id: uuid.UUID,
    ctx: Write,
    db: DbDep,
    meta: MetaDep,
    settings: SettingsDep,
    resources: ResourcesDep,
    limiter: LimiterDep,
    file: Annotated[UploadFile, File(description="The file to upload.")],
) -> DocumentOut:
    """Upload a file to a project. It is checked for viruses before it can be used."""
    max_bytes = settings.upload_max_bytes
    limit = Limit("upload", settings.uploads_per_user_per_hour, 3600)
    subject = str(ctx.auth.user.id)
    if await limiter.exceeded(limit, subject):
        raise rate_limited(await limiter.retry_after(limit, subject))
    project = await projects.get_project(db, ctx.organisation.id, project_id)
    data = await file.read(max_bytes + 1)
    checked = service.check_upload(data, file.filename, file.content_type, max_bytes)
    await limiter.hit(limit, subject)
    document = await service.create_upload(
        db,
        resources.storage,
        project,
        data=data,
        checked=checked,
        max_files=settings.upload_max_files_per_project,
        actor_id=ctx.auth.user.id,
        meta=meta,
    )
    try:
        await db.commit()
    except Exception:
        await resources.storage.delete(document.storage_key)
        raise
    org_id, document_id = ctx.organisation.id, document.id
    await _dispatch("scan", resources.jobs.scan(org_id, document_id))
    db.expire_all()  # an inline scan changed the row in another session
    return document_out(await service.get_document(db, org_id, document_id))


@router.get("/projects/{project_id}/documents", response_model=list[DocumentOut])
async def list_documents(project_id: uuid.UUID, ctx: Read, db: DbDep) -> list[DocumentOut]:
    project = await projects.get_project(db, ctx.organisation.id, project_id)
    return [document_out(d) for d in await service.list_documents(db, project)]


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(document_id: uuid.UUID, ctx: Read, db: DbDep) -> DocumentOut:
    return document_out(await service.get_document(db, ctx.organisation.id, document_id))


@router.get(
    "/documents/{document_id}/content",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}, 303: {}},
)
async def download_document(
    document_id: uuid.UUID, ctx: Read, db: DbDep, meta: MetaDep, resources: ResourcesDep
) -> Response:
    """The file, as a download. Only files that passed the virus check."""
    document = await service.get_document(db, ctx.organisation.id, document_id)
    service.require_clean(document)
    await service.record_download(
        db,
        target_type="uploaded_document",
        target_id=document.id,
        organisation_id=ctx.organisation.id,
        actor_id=ctx.auth.user.id,
        meta=meta,
    )
    await db.commit()
    return await _download(
        resources, document.storage_key, document.original_filename, document.detected_mime
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID, ctx: Write, db: DbDep, meta: MetaDep, resources: ResourcesDep
) -> Response:
    document = await service.get_document(db, ctx.organisation.id, document_id, lock=True)
    key = await service.delete_document(db, document, actor_id=ctx.auth.user.id, meta=meta)
    await db.commit()
    try:
        await resources.storage.delete(key)
    except StorageError:
        log.exception("could not remove deleted document content")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Evidence --------------------------------------------------------------------------


@router.get("/assessments/{assessment_id}/evidence", response_model=list[EvidenceOut])
async def list_evidence(assessment_id: uuid.UUID, ctx: Read, db: DbDep) -> list[EvidenceOut]:
    assessment, _, _ = await assessments.get(db, ctx.organisation.id, assessment_id)
    return [
        EvidenceOut(
            id=row.evidence.id,
            evidence_requirement_id=row.evidence.evidence_requirement_id,
            status=row.evidence.status,
            note=row.evidence.note,
            document=document_out(row.document),
            created_at=row.evidence.created_at,
        )
        for row in await service.list_evidence(db, assessment)
    ]


@router.post("/evidence", status_code=status.HTTP_201_CREATED, response_model=EvidenceOut)
async def add_evidence(body: EvidenceIn, ctx: Write, db: DbDep, meta: MetaDep) -> EvidenceOut:
    """Offer an uploaded (and virus-checked) file for an evidence requirement."""
    row = await service.add_evidence(
        db,
        ctx.organisation.id,
        requirement_id=body.evidence_requirement_id,
        document_id=body.uploaded_document_id,
        note=body.note,
        actor_id=ctx.auth.user.id,
        meta=meta,
    )
    await db.commit()
    return EvidenceOut(
        id=row.evidence.id,
        evidence_requirement_id=row.evidence.evidence_requirement_id,
        status=row.evidence.status,
        note=row.evidence.note,
        document=document_out(row.document),
        created_at=row.evidence.created_at,
    )


@router.delete("/evidence/{evidence_id}", status_code=status.HTTP_204_NO_CONTENT)
async def withdraw_evidence(
    evidence_id: uuid.UUID, ctx: Write, db: DbDep, meta: MetaDep
) -> Response:
    await service.withdraw_evidence(
        db, ctx.organisation.id, evidence_id, actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Generated reports -----------------------------------------------------------------


@router.post(
    "/assessments/{assessment_id}/documents",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=GeneratedDocumentOut,
)
async def generate_report(
    assessment_id: uuid.UUID,
    body: GenerateIn,
    ctx: Write,
    db: DbDep,
    meta: MetaDep,
    resources: ResourcesDep,
    limiter: LimiterDep,
) -> GeneratedDocumentOut:
    """Produce the assessment report as PDF, Word or HTML. Poll until it is READY."""
    limit = Limit("generate", GENERATIONS_PER_USER_PER_HOUR, 3600)
    subject = str(ctx.auth.user.id)
    if await limiter.hit(limit, subject) > limit.max_hits:
        raise rate_limited(await limiter.retry_after(limit, subject))
    assessment, project, _ = await assessments.get(db, ctx.organisation.id, assessment_id)
    generated = await service.request_report(
        db, assessment, project, body.format, actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    org_id, generated_id = ctx.organisation.id, generated.id
    await _dispatch("generate", resources.jobs.generate(org_id, generated_id))
    db.expire_all()  # inline generation changed the row in another session
    return generated_out(await service.get_generated(db, org_id, generated_id))


@router.get("/projects/{project_id}/generated-documents", response_model=list[GeneratedDocumentOut])
async def list_generated(project_id: uuid.UUID, ctx: Read, db: DbDep) -> list[GeneratedDocumentOut]:
    project = await projects.get_project(db, ctx.organisation.id, project_id)
    return [generated_out(g) for g in await service.list_generated(db, project)]


@router.get("/generated-documents/{generated_id}", response_model=GeneratedDocumentOut)
async def get_generated(generated_id: uuid.UUID, ctx: Read, db: DbDep) -> GeneratedDocumentOut:
    return generated_out(await service.get_generated(db, ctx.organisation.id, generated_id))


@router.get(
    "/generated-documents/{generated_id}/content",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}, 303: {}},
)
async def download_generated(
    generated_id: uuid.UUID, ctx: Read, db: DbDep, meta: MetaDep, resources: ResourcesDep
) -> Response:
    generated = await service.get_generated(db, ctx.organisation.id, generated_id)
    if generated.status != GenerationStatus.READY or generated.storage_key is None:
        raise ApiError(status.HTTP_409_CONFLICT, "not_ready", "This report isn't ready yet.")
    await service.record_download(
        db,
        target_type="generated_document",
        target_id=generated.id,
        organisation_id=ctx.organisation.id,
        actor_id=ctx.auth.user.id,
        meta=meta,
    )
    await db.commit()
    return await _download(
        resources,
        generated.storage_key,
        generated.filename,
        MIME_TYPES[OutputFormat(generated.format)],
    )
