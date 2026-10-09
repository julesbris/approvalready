"""Uploads, scanning, evidence and generated documents.

Upload flow: the API checks the size, the file's real type (``filetypes.py``) and the
project's file limit, stores the bytes under a key it generates, records the document as
``PENDING`` and queues a scan. Until the scan says ``CLEAN`` the document cannot be
downloaded, attached as evidence or submitted as an answer. An infected file is moved to
the ``quarantine/`` prefix and is never served again; deleting a document removes its
bytes from storage and keeps the row (soft delete) for the audit trail.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, not_found
from app.db.base import uuid7
from app.modules.assessments.models import Assessment, EvidenceRequirement
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.documents import filetypes
from app.modules.documents.models import (
    Classification,
    DocumentTemplate,
    DocumentTemplateVersion,
    Evidence,
    EvidenceStatus,
    GeneratedDocument,
    GenerationStatus,
    OutputFormat,
    ScanStatus,
    UploadedDocument,
)
from app.modules.documents.scanner import MalwareScanner
from app.modules.documents.storage import ObjectStorage
from app.modules.documents.templates import published
from app.modules.projects.models import Project, ProjectStatus
from app.modules.vessels.models import SafetyManagementSystem

# The report templates available for each vertical's assessments; the first is the default.
ASSESSMENT_TEMPLATES = {
    "PLANNING": ("PLANNING_ASSESSMENT",),
    "BUSINESS": ("BUSINESS_APPROVAL_MAP",),
    "VESSEL": ("VESSEL_PATHWAY", "SMS"),
}
# How each template's files are named (``<reference>-<slug>-<assessment date>``).
FILENAME_SLUGS = {"SMS": "safety-management-system"}
EXTENSIONS = {OutputFormat.PDF: "pdf", OutputFormat.DOCX: "docx", OutputFormat.HTML: "html"}
MIME_TYPES = {
    OutputFormat.PDF: "application/pdf",
    OutputFormat.DOCX: filetypes.DOCX.mime,
    OutputFormat.HTML: "text/html; charset=utf-8",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def _conflict(code: str, message: str) -> ApiError:
    return ApiError(status.HTTP_409_CONFLICT, code, message)


# --- Uploads ---------------------------------------------------------------------------


async def count_documents(db: AsyncSession, project: Project) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(UploadedDocument)
                .where(
                    UploadedDocument.project_id == project.id,
                    UploadedDocument.deleted_at.is_(None),
                )
            )
        ).scalar_one()
    )


def check_upload(
    data: bytes, filename: str | None, declared_mime: str | None, max_bytes: int
) -> filetypes.CheckedFile:
    """``filetypes.check`` with the size limit, as an API error."""
    if len(data) > max_bytes:
        raise ApiError(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "file_too_large",
            f"Files can be up to {max_bytes // (1024 * 1024)} MB.",
        )
    try:
        return filetypes.check(data, filename, declared_mime)
    except filetypes.FileRejected as exc:
        raise ApiError(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "file_rejected", str(exc)) from None


async def create_upload(
    db: AsyncSession,
    storage: ObjectStorage,
    project: Project,
    *,
    data: bytes,
    checked: filetypes.CheckedFile,
    max_files: int,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> UploadedDocument:
    if project.status == ProjectStatus.ARCHIVED:
        raise _conflict("project_archived", "This project is archived. Restore it to add files.")
    if await count_documents(db, project) >= max_files:
        raise _conflict(
            "too_many_files", f"A project can hold up to {max_files} files. Remove some first."
        )
    document_id = uuid7()
    key = f"uploads/{project.organisation_id}/{document_id}"
    await storage.put(key, data, checked.type.mime)
    document = UploadedDocument(
        id=document_id,
        organisation_id=project.organisation_id,
        project_id=project.id,
        storage_key=key,
        original_filename=checked.filename,
        extension=checked.extension,
        declared_mime=checked.declared_mime[:200],
        detected_mime=checked.type.mime,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).digest(),
        scan_status=ScanStatus.PENDING,
        created_by=actor_id,
    )
    db.add(document)
    await db.flush()
    await audit.record(
        db,
        "document.uploaded",
        actor_user_id=actor_id,
        organisation_id=project.organisation_id,
        target_type="uploaded_document",
        target_id=document.id,
        meta=meta,
        details={
            "project_id": str(project.id),
            "type": checked.type.mime,
            "size_bytes": len(data),
            "sha256": document.sha256.hex(),
        },
    )
    return document


async def list_documents(db: AsyncSession, project: Project) -> list[UploadedDocument]:
    return list(
        (
            await db.execute(
                select(UploadedDocument)
                .where(
                    UploadedDocument.project_id == project.id,
                    UploadedDocument.deleted_at.is_(None),
                )
                .order_by(UploadedDocument.created_at)
            )
        ).scalars()
    )


async def get_document(
    db: AsyncSession, organisation_id: uuid.UUID, document_id: uuid.UUID, *, lock: bool = False
) -> UploadedDocument:
    query = select(UploadedDocument).where(
        UploadedDocument.id == document_id,
        UploadedDocument.organisation_id == organisation_id,
        UploadedDocument.deleted_at.is_(None),
    )
    if lock:
        query = query.with_for_update()
    document = (await db.execute(query)).scalar_one_or_none()
    if document is None:
        raise not_found("Document")
    return document


async def documents_by_id(
    db: AsyncSession, project_id: uuid.UUID, ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, UploadedDocument]:
    wanted = set(ids)
    if not wanted:
        return {}
    rows = (
        await db.execute(
            select(UploadedDocument).where(
                UploadedDocument.id.in_(wanted),
                UploadedDocument.project_id == project_id,
                UploadedDocument.deleted_at.is_(None),
            )
        )
    ).scalars()
    return {d.id: d for d in rows}


def require_clean(document: UploadedDocument) -> None:
    match document.scan_status:
        case ScanStatus.CLEAN:
            return
        case ScanStatus.PENDING:
            raise _conflict("document_not_scanned", "This file is still being checked for viruses.")
        case ScanStatus.INFECTED:
            raise _conflict("document_infected", "This file was blocked by the virus check.")
        case _:
            raise _conflict(
                "document_scan_failed",
                "This file couldn't be checked for viruses. Upload it again.",
            )


async def delete_document(
    db: AsyncSession,
    document: UploadedDocument,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> str:
    """Soft-delete the row and withdraw it as evidence. Returns the storage key, which the
    caller deletes once the transaction has committed."""
    document.deleted_at = utcnow()
    await db.execute(delete(Evidence).where(Evidence.uploaded_document_id == document.id))
    await db.flush()
    await audit.record(
        db,
        "document.deleted",
        actor_user_id=actor_id,
        organisation_id=document.organisation_id,
        target_type="uploaded_document",
        target_id=document.id,
        meta=meta,
    )
    return document.storage_key


async def record_download(
    db: AsyncSession,
    *,
    target_type: str,
    target_id: uuid.UUID,
    organisation_id: uuid.UUID,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> None:
    await audit.record(
        db,
        "document.downloaded",
        actor_user_id=actor_id,
        organisation_id=organisation_id,
        target_type=target_type,
        target_id=target_id,
        meta=meta,
    )


async def set_classification(
    db: AsyncSession,
    document: UploadedDocument,
    classification: Classification,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> UploadedDocument:
    if classification == Classification.RELEASED_TO_PARTNER:
        raise _conflict("not_available", "Sharing with partners isn't available yet.")
    if document.classification == classification:
        return document
    previous = document.classification
    document.classification = classification
    await db.flush()
    await audit.record(
        db,
        "document.classification_changed",
        actor_user_id=actor_id,
        organisation_id=document.organisation_id,
        target_type="uploaded_document",
        target_id=document.id,
        meta=meta,
        details={"from": previous, "to": classification},
    )
    return document


# --- Scanning (runs in the worker) -----------------------------------------------------


async def scan_document(
    db: AsyncSession,
    storage: ObjectStorage,
    scanner: MalwareScanner,
    organisation_id: uuid.UUID,
    document_id: uuid.UUID,
) -> str | None:
    """Scan a pending document and record the verdict. Raises ``ScannerUnavailable`` (to
    retry later) when the scanner gives no answer. Returns the new status, or ``None`` when
    there was nothing to do (already scanned, or deleted)."""
    try:
        document = await get_document(db, organisation_id, document_id, lock=True)
    except ApiError:
        return None
    if document.scan_status != ScanStatus.PENDING:
        return None
    data = await storage.get(document.storage_key)
    if hashlib.sha256(data).digest() != document.sha256:
        # The stored bytes are not what was uploaded: never pass them as clean.
        document.scan_status = ScanStatus.ERROR
        document.scan_signature = "content changed in storage"
        document.scanned_at = utcnow()
        await db.flush()
        return document.scan_status
    result = await scanner.scan(data)
    document.scan_engine = scanner.name
    document.scanned_at = utcnow()
    document.scan_attempts += 1
    if result.infected:
        quarantine_key = f"quarantine/{document.organisation_id}/{document.id}"
        await storage.move(document.storage_key, quarantine_key)
        document.storage_key = quarantine_key
        document.scan_status = ScanStatus.INFECTED
        document.scan_signature = (result.signature or "unknown")[:200]
        await db.execute(delete(Evidence).where(Evidence.uploaded_document_id == document.id))
        await audit.record(
            db,
            "document.quarantined",
            organisation_id=document.organisation_id,
            target_type="uploaded_document",
            target_id=document.id,
            details={"signature": document.scan_signature, "engine": scanner.name},
        )
    else:
        document.scan_status = ScanStatus.CLEAN
    await db.flush()
    return document.scan_status


async def record_scan_failure(
    db: AsyncSession, organisation_id: uuid.UUID, document_id: uuid.UUID, *, give_up: bool
) -> None:
    try:
        document = await get_document(db, organisation_id, document_id, lock=True)
    except ApiError:
        return
    if document.scan_status != ScanStatus.PENDING:
        return
    document.scan_attempts += 1
    if give_up:
        document.scan_status = ScanStatus.ERROR
        document.scanned_at = utcnow()
    await db.flush()


# --- Evidence --------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceRow:
    evidence: Evidence
    document: UploadedDocument


async def list_evidence(db: AsyncSession, assessment: Assessment) -> list[EvidenceRow]:
    rows = (
        await db.execute(
            select(Evidence, UploadedDocument)
            .join(EvidenceRequirement, EvidenceRequirement.id == Evidence.evidence_requirement_id)
            .join(UploadedDocument, UploadedDocument.id == Evidence.uploaded_document_id)
            .where(
                EvidenceRequirement.assessment_id == assessment.id,
                UploadedDocument.deleted_at.is_(None),
            )
            .order_by(Evidence.created_at)
        )
    ).all()
    return [EvidenceRow(e, d) for e, d in rows]


async def add_evidence(
    db: AsyncSession,
    organisation_id: uuid.UUID,
    *,
    requirement_id: uuid.UUID,
    document_id: uuid.UUID,
    note: str | None,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> EvidenceRow:
    found = (
        await db.execute(
            select(EvidenceRequirement, Assessment)
            .join(Assessment, Assessment.id == EvidenceRequirement.assessment_id)
            .where(
                EvidenceRequirement.id == requirement_id,
                EvidenceRequirement.organisation_id == organisation_id,
            )
        )
    ).one_or_none()
    if found is None:
        raise not_found("Evidence requirement")
    requirement, assessment = found
    document = await get_document(db, organisation_id, document_id)
    if document.project_id != assessment.project_id:
        raise not_found("Document")
    require_clean(document)
    existing = (
        await db.execute(
            select(Evidence).where(
                Evidence.evidence_requirement_id == requirement.id,
                Evidence.uploaded_document_id == document.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise _conflict("evidence_exists", "That file is already attached here.")
    evidence = Evidence(
        organisation_id=organisation_id,
        project_id=assessment.project_id,
        evidence_requirement_id=requirement.id,
        uploaded_document_id=document.id,
        status=EvidenceStatus.SUBMITTED,
        note=note,
        created_by=actor_id,
    )
    db.add(evidence)
    await db.flush()
    await audit.record(
        db,
        "evidence.submitted",
        actor_user_id=actor_id,
        organisation_id=organisation_id,
        target_type="evidence",
        target_id=evidence.id,
        meta=meta,
        details={"requirement_id": str(requirement.id), "document_id": str(document.id)},
    )
    return EvidenceRow(evidence, document)


async def withdraw_evidence(
    db: AsyncSession,
    organisation_id: uuid.UUID,
    evidence_id: uuid.UUID,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> None:
    evidence = (
        await db.execute(
            select(Evidence).where(
                Evidence.id == evidence_id, Evidence.organisation_id == organisation_id
            )
        )
    ).scalar_one_or_none()
    if evidence is None:
        raise not_found("Evidence")
    if evidence.status != EvidenceStatus.SUBMITTED:
        raise _conflict("evidence_reviewed", "Reviewed evidence can't be withdrawn.")
    await db.delete(evidence)
    await db.flush()
    await audit.record(
        db,
        "evidence.withdrawn",
        actor_user_id=actor_id,
        organisation_id=organisation_id,
        target_type="evidence",
        target_id=evidence_id,
        meta=meta,
    )


# --- Generated documents ---------------------------------------------------------------


async def request_report(
    db: AsyncSession,
    assessment: Assessment,
    project: Project,
    output: OutputFormat,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
    template: str | None = None,
) -> GeneratedDocument:
    available = ASSESSMENT_TEMPLATES.get(project.vertical, ())
    key = template or (available[0] if available else None)
    if key is not None and key not in available:
        raise _conflict("no_template", "That report isn't available for this kind of project.")
    version = await published(db, key) if key else None
    if key is None or version is None:
        raise _conflict("no_template", "Reports aren't available for this kind of project yet.")
    if key == "SMS" and not await _sms_written(db, project):
        raise _conflict(
            "sms_empty", "Write some of your safety management system before downloading it."
        )
    if output not in version.output_formats:
        raise _conflict("format_unavailable", "That format isn't available for this report.")
    generated = GeneratedDocument(
        organisation_id=project.organisation_id,
        project_id=project.id,
        assessment_id=assessment.id,
        template_version_id=version.id,
        format=output,
        status=GenerationStatus.PENDING,
        filename=f"{project.reference_code}-{FILENAME_SLUGS.get(key, 'assessment')}-"
        f"{assessment.assessed_on.isoformat()}.{EXTENSIONS[output]}",
        created_by=actor_id,
    )
    db.add(generated)
    await db.flush()
    await audit.record(
        db,
        "document.generation_requested",
        actor_user_id=actor_id,
        organisation_id=project.organisation_id,
        target_type="generated_document",
        target_id=generated.id,
        meta=meta,
        details={"assessment_id": str(assessment.id), "format": str(output), "template": key},
    )
    return generated


async def template_keys(db: AsyncSession, version_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    wanted = set(version_ids)
    if not wanted:
        return {}
    rows = await db.execute(
        select(DocumentTemplateVersion.id, DocumentTemplate.key)
        .join(DocumentTemplate, DocumentTemplate.id == DocumentTemplateVersion.template_id)
        .where(DocumentTemplateVersion.id.in_(wanted))
    )
    return {version_id: key for version_id, key in rows.all()}


async def _sms_written(db: AsyncSession, project: Project) -> bool:
    content = (
        await db.execute(
            select(SafetyManagementSystem.content).where(
                SafetyManagementSystem.organisation_id == project.organisation_id,
                SafetyManagementSystem.project_id == project.id,
            )
        )
    ).scalar_one_or_none()
    return bool(content)


async def list_generated(db: AsyncSession, project: Project) -> list[GeneratedDocument]:
    return list(
        (
            await db.execute(
                select(GeneratedDocument)
                .where(GeneratedDocument.project_id == project.id)
                .order_by(GeneratedDocument.created_at.desc())
                .limit(100)
            )
        ).scalars()
    )


async def get_generated(
    db: AsyncSession, organisation_id: uuid.UUID, generated_id: uuid.UUID, *, lock: bool = False
) -> GeneratedDocument:
    query = (
        select(GeneratedDocument)
        .join(Project, Project.id == GeneratedDocument.project_id)
        .where(
            GeneratedDocument.id == generated_id,
            GeneratedDocument.organisation_id == organisation_id,
            Project.deleted_at.is_(None),
        )
    )
    if lock:
        query = query.with_for_update(of=GeneratedDocument)
    generated = (await db.execute(query)).scalar_one_or_none()
    if generated is None:
        raise not_found("Document")
    return generated
