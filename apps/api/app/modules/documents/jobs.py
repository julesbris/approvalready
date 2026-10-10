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
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import JobsMode, Settings
from app.core.email import EmailProvider
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

if TYPE_CHECKING:
    from app.modules.ai.provider import AIProvider
    from app.modules.ai.service import Prices
    from app.modules.billing.stripe import StripeClient

log = logging.getLogger(__name__)

SCAN_TASK = "documents.scan"
GENERATE_TASK = "documents.generate"
AI_TASK = "ai.run"
BILLING_EVENT_TASK = "billing.process_event"
REFUND_TASK = "billing.send_refund"
LEAD_MATCH_TASK = "leads.match"


def _disabled_ai() -> AIProvider:
    from app.modules.ai.provider import DisabledProvider

    return DisabledProvider()


def _no_prices() -> Prices:
    from app.modules.ai.service import Prices

    return Prices()


@dataclass
class JobContext:
    session_factory: async_sessionmaker[AsyncSession]
    storage: ObjectStorage
    scanner: MalwareScanner
    ai: AIProvider = field(default_factory=_disabled_ai)
    ai_prices: Prices = field(default_factory=_no_prices)
    # For jobs that notify people (lead matching).
    email: EmailProvider | None = None
    settings: Settings | None = None
    # For refunds (Milestone 22); None while payments are switched off.
    stripe: StripeClient | None = None


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


async def ai_job(
    ctx: JobContext, organisation_id: uuid.UUID, job_id: uuid.UUID, *, final_attempt: bool
) -> str | None:
    from app.modules.ai import service as ai
    from app.modules.ai.provider import TransientProviderError

    async with ctx.session_factory() as db:
        await bind_tenant(db, organisation_id)
        try:
            return await ai.run_job(
                db, ctx.ai, ctx.ai_prices, organisation_id, job_id, final_attempt=final_attempt
            )
        except TransientProviderError as exc:
            raise RetryLater(str(exc)) from exc


async def billing_event_job(ctx: JobContext, event_id: uuid.UUID) -> str | None:
    """Apply one stored Stripe webhook event. Not tenant-bound up front: the event names
    its organisation only through its Stripe customer (``billing/webhooks.py``)."""
    from app.modules.billing import refunds, webhooks

    async with ctx.session_factory() as db:
        try:
            result = await webhooks.process_event(db, event_id)
        except webhooks.EventFailed as exc:
            raise RetryLater(str(exc)) from exc
        new = refunds.take_new(db)
    # A payment that arrived for a cancelled review is refunded straight away; the sweep
    # tries again if this fails.
    for organisation_id, refund_id in new:
        try:
            await refund_job(ctx, organisation_id, refund_id, final_attempt=False)
        except RetryLater:
            log.warning("refund not sent yet", extra={"refund_id": str(refund_id)})
    return result


async def refund_job(
    ctx: JobContext, organisation_id: uuid.UUID, refund_id: uuid.UUID, *, final_attempt: bool
) -> str | None:
    """Send one refund to Stripe, then tell the customer (or staff, when it failed)."""
    from app.modules.billing import emails, refunds
    from app.modules.billing.models import RefundStatus
    from app.modules.identity.models import AppUser
    from app.modules.ops import service as ops

    if ctx.stripe is None:
        log.warning("payments are off: refund left pending", extra={"refund_id": str(refund_id)})
        return None
    async with ctx.session_factory() as db:
        sent = await refunds.send(
            db, ctx.stripe, organisation_id, refund_id, final_attempt=final_attempt
        )
        if sent is None:
            return None
        user = await db.get(AppUser, sent.payment.created_by) if sent.payment.created_by else None
        await db.commit()
    if sent.status == RefundStatus.PENDING:
        raise RetryLater(sent.refund.error or "Stripe could not be reached")
    if ctx.email is None or ctx.settings is None:
        return sent.status
    if sent.status == RefundStatus.FAILED:
        await ops.send_alerts(
            ctx.session_factory,
            ctx.email,
            ctx.settings,
            [
                ops.Alert(
                    title="A refund could not be made",
                    body=(
                        f"Stripe did not accept a refund of "
                        f"{emails.money(sent.refund.amount_cents, sent.refund.currency)} "
                        f"(payment {sent.payment.id}): {sent.refund.error or 'no reason given'}. "
                        "Refund it in the Stripe dashboard, or check the payment there."
                    ),
                    dedupe_key=f"refund:{sent.refund.id}:failed",
                )
            ],
        )
    elif user is not None:
        from app.modules.identity import service as identity

        await identity.send_email(
            ctx.email,
            emails.refund_sent(
                ctx.settings,
                user.email,
                user.display_name,
                organisation_id,
                sent.refund.amount_cents,
                sent.refund.currency,
            ),
        )
    return sent.status


JobFn = Callable[..., Awaitable[str | None]]


async def run_with_own_resources(
    settings: Settings, job: JobFn, organisation_id: str, target_id: str, *, final_attempt: bool
) -> str | None:
    """Run one job with a fresh engine (each Celery task gets its own event loop)."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        ctx = create_job_context(
            settings,
            async_sessionmaker(engine, expire_on_commit=False),
            create_storage(settings),
        )
        return await job(
            ctx, uuid.UUID(organisation_id), uuid.UUID(target_id), final_attempt=final_attempt
        )
    finally:
        await engine.dispose()


def create_job_context(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    storage: ObjectStorage,
    email: EmailProvider | None = None,
    stripe: StripeClient | None = None,
) -> JobContext:
    from app.modules.ai.provider import create_provider
    from app.modules.ai.service import Prices

    return JobContext(
        session_factory=session_factory,
        storage=storage,
        scanner=create_scanner(settings),
        ai=create_provider(settings),
        ai_prices=Prices(
            settings.ai_input_price_per_mtok_usd, settings.ai_output_price_per_mtok_usd
        ),
        email=email,
        settings=settings,
        stripe=stripe,
    )


async def _with_billing_context(
    settings: Settings, job: Callable[[JobContext], Awaitable[str | None]]
) -> str | None:
    """Run a billing job with a fresh engine, a Stripe client and email."""
    from app.core.email import create_email_provider
    from app.modules.billing.stripe import StripeClient

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    stripe = StripeClient(settings) if settings.payments_enabled else None
    try:
        ctx = create_job_context(
            settings,
            async_sessionmaker(engine, expire_on_commit=False),
            create_storage(settings),
            create_email_provider(settings),
            stripe,
        )
        return await job(ctx)
    finally:
        if stripe is not None:
            await stripe.aclose()
        await engine.dispose()


async def run_billing_event(settings: Settings, event_id: str) -> str | None:
    return await _with_billing_context(
        settings, lambda ctx: billing_event_job(ctx, uuid.UUID(event_id))
    )


async def run_refund(
    settings: Settings, organisation_id: str, refund_id: str, *, final_attempt: bool
) -> str | None:
    return await _with_billing_context(
        settings,
        lambda ctx: refund_job(
            ctx, uuid.UUID(organisation_id), uuid.UUID(refund_id), final_attempt=final_attempt
        ),
    )


async def pending_refunds(settings: Settings, older_than_minutes: int) -> list[tuple[str, str]]:
    from app.modules.billing import refunds

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine)() as db:
            return await refunds.pending(db, older_than_minutes)
    finally:
        await engine.dispose()


async def stalled_billing_events(settings: Settings, older_than_minutes: int) -> list[str]:
    from app.modules.billing import webhooks

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine)() as db:
            return [str(i) for i in await webhooks.events_to_requeue(db, older_than_minutes)]
    finally:
        await engine.dispose()


async def stalled_jobs(settings: Settings, older_than_minutes: int) -> list[tuple[str, str, str]]:
    """(kind, id, organisation id) of scans and generations still pending after a while."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            age = {"age": f"{older_than_minutes} minutes"}
            rows = list(
                await conn.execute(
                    text("SELECT kind, id, organisation_id FROM pending_document_jobs(:age)"), age
                )
            )
            rows += list(
                await conn.execute(
                    text("SELECT 'ai', id, organisation_id FROM pending_ai_jobs(:age)"), age
                )
            )
            return [(r[0], str(r[1]), str(r[2])) for r in rows]
    finally:
        await engine.dispose()


# --- Dispatch from the API -------------------------------------------------------------


class JobRunner(Protocol):
    async def scan(self, organisation_id: uuid.UUID, document_id: uuid.UUID) -> None: ...

    async def generate(self, organisation_id: uuid.UUID, generated_id: uuid.UUID) -> None: ...

    async def ai(self, organisation_id: uuid.UUID, job_id: uuid.UUID) -> None: ...

    async def billing_event(self, event_id: uuid.UUID) -> None: ...

    async def refund(self, organisation_id: uuid.UUID, refund_id: uuid.UUID) -> None: ...

    async def lead_match(self, lead_id: uuid.UUID) -> None: ...


class CeleryJobs:
    async def _send(self, name: str, *args: str) -> None:
        from app.worker import celery_app

        await asyncio.to_thread(celery_app.send_task, name, args=list(args))

    async def scan(self, organisation_id: uuid.UUID, document_id: uuid.UUID) -> None:
        await self._send(SCAN_TASK, str(organisation_id), str(document_id))

    async def generate(self, organisation_id: uuid.UUID, generated_id: uuid.UUID) -> None:
        await self._send(GENERATE_TASK, str(organisation_id), str(generated_id))

    async def ai(self, organisation_id: uuid.UUID, job_id: uuid.UUID) -> None:
        await self._send(AI_TASK, str(organisation_id), str(job_id))

    async def billing_event(self, event_id: uuid.UUID) -> None:
        await self._send(BILLING_EVENT_TASK, str(event_id))

    async def refund(self, organisation_id: uuid.UUID, refund_id: uuid.UUID) -> None:
        await self._send(REFUND_TASK, str(organisation_id), str(refund_id))

    async def lead_match(self, lead_id: uuid.UUID) -> None:
        await self._send(LEAD_MATCH_TASK, str(lead_id))


class InlineJobs:
    def __init__(self, ctx: JobContext) -> None:
        self.ctx = ctx

    async def scan(self, organisation_id: uuid.UUID, document_id: uuid.UUID) -> None:
        await scan_job(self.ctx, organisation_id, document_id, final_attempt=True)

    async def generate(self, organisation_id: uuid.UUID, generated_id: uuid.UUID) -> None:
        await generate_job(self.ctx, organisation_id, generated_id, final_attempt=True)

    async def ai(self, organisation_id: uuid.UUID, job_id: uuid.UUID) -> None:
        await ai_job(self.ctx, organisation_id, job_id, final_attempt=True)

    async def billing_event(self, event_id: uuid.UUID) -> None:
        try:
            await billing_event_job(self.ctx, event_id)
        except RetryLater:
            log.warning("stripe event failed", extra={"event_id": str(event_id)})

    async def refund(self, organisation_id: uuid.UUID, refund_id: uuid.UUID) -> None:
        try:
            await refund_job(self.ctx, organisation_id, refund_id, final_attempt=False)
        except RetryLater:
            log.warning("refund not sent yet", extra={"refund_id": str(refund_id)})

    async def lead_match(self, lead_id: uuid.UUID) -> None:
        from app.modules.leads import jobs as leads

        await leads.match_lead(self.ctx.session_factory, self.ctx.email, self.ctx.settings, lead_id)


def create_job_runner(settings: Settings, ctx: JobContext) -> JobRunner:
    if settings.jobs_mode == JobsMode.INLINE:
        return InlineJobs(ctx)
    return CeleryJobs()
