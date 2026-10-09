"""Background work for documents: malware scans and report generation.

Jobs run in the Celery worker (``app/worker.py``) as the application database role, bound
to the job's organisation, so row-level security applies exactly as it does to requests.
With ``JOBS_MODE=inline`` (tests, or development without a worker) the API runs the same
job straight after the request commits.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import JobsMode, Settings
from app.core.errors import ApiError
from app.db.tenant import bind_tenant
from app.modules.audit import service as audit
from app.modules.documents import service
from app.modules.documents.models import GenerationStatus
from app.modules.documents.render import RenderError
from app.modules.documents.report import render_document
from app.modules.documents.scanner import MalwareScanner, ScannerUnavailable, create_scanner
from app.modules.documents.service import MIME_TYPES, utcnow
from app.modules.documents.storage import ObjectStorage, StorageError, create_storage

log = logging.getLogger(__name__)

SCAN_TASK = "documents.scan"
GENERATE_TASK = "documents.generate"


@dataclass
class JobContext:
    session_factory: async_sessionmaker[AsyncSession]
    storage: ObjectStorage
    scanner: MalwareScanner


class RetryLater(Exception):
    """Transient failure: the worker should retry the job."""


async def scan_job(
    ctx: JobContext, organisation_id: uuid.UUID, document_id: uuid.UUID, *, final_attempt: bool
) -> str | None:
    async with ctx.session_factory() as db:
        await bind_tenant(db, organisation_id)
        try:
            result = await service.scan_document(
                db, ctx.storage, ctx.scanner, organisation_id, document_id
            )
            await db.commit()
            return result
        except (ScannerUnavailable, StorageError) as exc:
            await db.rollback()
            log.warning("document scan failed", extra={"document_id": str(document_id)})
            await service.record_scan_failure(
                db, organisation_id, document_id, give_up=final_attempt
            )
            await db.commit()
            if final_attempt:
                return "ERROR"
            raise RetryLater(str(exc)) from exc


async def generate_job(
    ctx: JobContext, organisation_id: uuid.UUID, generated_id: uuid.UUID, *, final_attempt: bool
) -> str | None:
    async with ctx.session_factory() as db:
        await bind_tenant(db, organisation_id)
        try:
            generated = await service.get_generated(db, organisation_id, generated_id, lock=True)
        except ApiError:
            return None
        if generated.status != GenerationStatus.PENDING:
            return None
        generated.attempts += 1
        error: str | None = None
        try:
            content = await render_document(db, generated)
            key = f"generated/{organisation_id}/{generated.id}"
            await ctx.storage.put(key, content, MIME_TYPES[generated.format])  # type: ignore[index]
        except RenderError as exc:
            log.error("report rendering failed: %s", exc)
            error = "The report could not be produced from its template."
        except (StorageError, OSError) as exc:
            if not final_attempt:
                await db.rollback()
                raise RetryLater(str(exc)) from exc
            error = "The report could not be saved. Try again."
        if error is None:
            generated.status = GenerationStatus.READY
            generated.storage_key = key
            generated.size_bytes = len(content)
            generated.sha256 = hashlib.sha256(content).digest()
        else:
            generated.status = GenerationStatus.FAILED
            generated.error = error
        generated.completed_at = utcnow()
        await db.flush()
        await audit.record(
            db,
            "document.generated" if error is None else "document.generation_failed",
            organisation_id=organisation_id,
            target_type="generated_document",
            target_id=generated.id,
            details={"format": generated.format}
            | ({"sha256": generated.sha256.hex()} if generated.sha256 else {}),
        )
        await db.commit()
        return generated.status


JobFn = Callable[..., Awaitable[str | None]]


async def run_with_own_resources(
    settings: Settings, job: JobFn, organisation_id: str, target_id: str, *, final_attempt: bool
) -> str | None:
    """Run one job with a fresh engine (each Celery task gets its own event loop)."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        ctx = JobContext(
            session_factory=async_sessionmaker(engine, expire_on_commit=False),
            storage=create_storage(settings),
            scanner=create_scanner(settings),
        )
        return await job(
            ctx, uuid.UUID(organisation_id), uuid.UUID(target_id), final_attempt=final_attempt
        )
    finally:
        await engine.dispose()


async def stalled_jobs(settings: Settings, older_than_minutes: int) -> list[tuple[str, str, str]]:
    """(kind, id, organisation id) of scans and generations still pending after a while."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT kind, id, organisation_id FROM pending_document_jobs(:age)"),
                {"age": f"{older_than_minutes} minutes"},
            )
            return [(r[0], str(r[1]), str(r[2])) for r in rows]
    finally:
        await engine.dispose()


# --- Dispatch from the API -------------------------------------------------------------


class JobRunner(Protocol):
    async def scan(self, organisation_id: uuid.UUID, document_id: uuid.UUID) -> None: ...

    async def generate(self, organisation_id: uuid.UUID, generated_id: uuid.UUID) -> None: ...


class CeleryJobs:
    async def _send(self, name: str, *args: str) -> None:
        from app.worker import celery_app

        await asyncio.to_thread(celery_app.send_task, name, args=list(args))

    async def scan(self, organisation_id: uuid.UUID, document_id: uuid.UUID) -> None:
        await self._send(SCAN_TASK, str(organisation_id), str(document_id))

    async def generate(self, organisation_id: uuid.UUID, generated_id: uuid.UUID) -> None:
        await self._send(GENERATE_TASK, str(organisation_id), str(generated_id))


class InlineJobs:
    def __init__(self, ctx: JobContext) -> None:
        self.ctx = ctx

    async def scan(self, organisation_id: uuid.UUID, document_id: uuid.UUID) -> None:
        await scan_job(self.ctx, organisation_id, document_id, final_attempt=True)

    async def generate(self, organisation_id: uuid.UUID, generated_id: uuid.UUID) -> None:
        await generate_job(self.ctx, organisation_id, generated_id, final_attempt=True)


def create_job_runner(settings: Settings, ctx: JobContext) -> JobRunner:
    if settings.jobs_mode == JobsMode.INLINE:
        return InlineJobs(ctx)
    return CeleryJobs()
