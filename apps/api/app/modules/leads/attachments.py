"""Files sent in messages: virus scans and downloads.

A file sent with a message (``messages.py``) is stored as ``PENDING`` and scanned after the
request commits, by the worker (``leads.scan_attachment``) or straight away with
``JOBS_MODE=inline``. Until the scan says ``CLEAN`` neither side can download it. An
infected file is moved under ``quarantine/`` and never served. The scheduler re-queues
scans still pending after a while (the queue was down when the file was sent).

Attachments are platform rows like the messages: the API checks that the caller is a side
of the conversation before it looks the file up, and the file must belong to that
conversation.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, not_found
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.documents.models import ScanStatus
from app.modules.documents.scanner import MalwareScanner
from app.modules.documents.service import utcnow
from app.modules.documents.storage import ObjectStorage
from app.modules.leads.models import LeadMessageAttachment


async def get(
    db: AsyncSession, match_id: uuid.UUID, attachment_id: uuid.UUID, *, lock: bool = False
) -> LeadMessageAttachment:
    query = select(LeadMessageAttachment).where(
        LeadMessageAttachment.id == attachment_id,
        LeadMessageAttachment.lead_match_id == match_id,
    )
    if lock:
        query = query.with_for_update()
    found = (await db.execute(query)).scalar_one_or_none()
    if found is None:
        raise not_found("File")
    return found


def _conflict(code: str, message: str) -> ApiError:
    return ApiError(status.HTTP_409_CONFLICT, code, message)


def require_clean(attachment: LeadMessageAttachment) -> None:
    match attachment.scan_status:
        case ScanStatus.CLEAN:
            return
        case ScanStatus.PENDING:
            raise _conflict("document_not_scanned", "This file is still being checked for viruses.")
        case ScanStatus.INFECTED:
            raise _conflict("document_infected", "This file was blocked by the virus check.")
        case _:
            raise _conflict(
                "document_scan_failed",
                "This file couldn't be checked for viruses. Ask for it to be sent again.",
            )


async def record_download(
    db: AsyncSession,
    attachment: LeadMessageAttachment,
    *,
    organisation_id: uuid.UUID,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> None:
    await audit.record(
        db,
        "message_attachment.downloaded",
        actor_user_id=actor_id,
        organisation_id=organisation_id,
        target_type="lead_message_attachment",
        target_id=attachment.id,
        meta=meta,
        details={"lead_match_id": str(attachment.lead_match_id)},
    )


async def scan(
    db: AsyncSession,
    storage: ObjectStorage,
    scanner: MalwareScanner,
    match_id: uuid.UUID,
    attachment_id: uuid.UUID,
) -> str | None:
    """Scan a pending file and record the verdict. Raises ``ScannerUnavailable`` (to retry
    later) when the scanner gives no answer. Returns the new status, or ``None`` when there
    was nothing to do."""
    try:
        attachment = await get(db, match_id, attachment_id, lock=True)
    except ApiError:
        return None
    if attachment.scan_status != ScanStatus.PENDING:
        return None
    data = await storage.get(attachment.storage_key)
    attachment.scanned_at = utcnow()
    if hashlib.sha256(data).digest() != attachment.sha256:
        # The stored bytes are not what was sent: never pass them as clean.
        attachment.scan_status = ScanStatus.ERROR
        attachment.scan_signature = "content changed in storage"
        await db.flush()
        return attachment.scan_status
    result = await scanner.scan(data)
    attachment.scan_engine = scanner.name
    attachment.scan_attempts += 1
    if result.infected:
        quarantine_key = f"quarantine/{attachment.storage_key}"
        await storage.move(attachment.storage_key, quarantine_key)
        attachment.storage_key = quarantine_key
        attachment.scan_status = ScanStatus.INFECTED
        attachment.scan_signature = (result.signature or "unknown")[:200]
        await audit.record(
            db,
            "message_attachment.quarantined",
            target_type="lead_message_attachment",
            target_id=attachment.id,
            details={"signature": attachment.scan_signature, "engine": scanner.name},
        )
    else:
        attachment.scan_status = ScanStatus.CLEAN
    await db.flush()
    return attachment.scan_status


async def record_scan_failure(
    db: AsyncSession, match_id: uuid.UUID, attachment_id: uuid.UUID, *, give_up: bool
) -> None:
    try:
        attachment = await get(db, match_id, attachment_id, lock=True)
    except ApiError:
        return
    if attachment.scan_status != ScanStatus.PENDING:
        return
    attachment.scan_attempts += 1
    if give_up:
        attachment.scan_status = ScanStatus.ERROR
        attachment.scanned_at = utcnow()
    await db.flush()


async def stalled(
    db: AsyncSession, now: datetime, older_than_minutes: int
) -> list[tuple[str, str]]:
    """(match id, attachment id) of files still waiting for their scan after a while."""
    rows = await db.execute(
        select(LeadMessageAttachment.lead_match_id, LeadMessageAttachment.id).where(
            LeadMessageAttachment.scan_status == ScanStatus.PENDING,
            LeadMessageAttachment.created_at < now - timedelta(minutes=older_than_minutes),
        )
    )
    return [(str(m), str(a)) for m, a in rows.all()]
