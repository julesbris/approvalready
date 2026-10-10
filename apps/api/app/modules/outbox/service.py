"""Email outbox (Milestone 20): queue every email, deliver it from the worker with retries.

``OutboxEmailProvider`` is the ``EmailProvider`` the API and the worker use when
``EMAIL_OUTBOX`` is on (the default). Its ``send`` seals the message into ``email_outbox``,
commits, and asks the worker to deliver it (``email.deliver``); with ``JOBS_MODE=inline`` it
delivers straight away instead. Callers are unchanged: they still call ``send`` after their
own transaction commits.

Delivery (``deliver``) locks the row, hands the message to the real provider (SMTP in
production) and records the outcome. A temporary failure (server down, timeout, 4xx reply,
rejected login) is retried after 1, 5, 15, 60, 180 and 360 minutes, about ten hours in all;
a permanent refusal (an address the server rejects, another 5xx reply) fails at once. Either
way the sealed message is erased once the row is finished. ``email.sweep`` runs every
minute: it delivers anything due (retries, and emails whose ``email.deliver`` never reached
the queue) and removes finished rows after ``EMAIL_OUTBOX_KEEP_DAYS``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import smtplib
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import JobsMode, Settings
from app.core.crypto import SealedValueError, seal, unseal
from app.core.email import EmailProvider, OutgoingEmail
from app.modules.outbox.models import OutboxEmail, OutboxStatus

logger = logging.getLogger(__name__)

PURPOSE = "email_outbox"
DELIVER_TASK = "email.deliver"
# Minutes to wait after each failed attempt; one attempt more than there are delays.
RETRY_DELAYS = (1, 5, 15, 60, 180, 360)
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1
SWEEP_BATCH = 100
ERROR_LIMIT = 500

Dispatch = Callable[[uuid.UUID], Awaitable[None]]


def utcnow() -> datetime:
    return datetime.now(UTC)


def _pack(settings: Settings, message: OutgoingEmail) -> bytes:
    payload = {
        "to": message.to,
        "subject": message.subject,
        "text": message.text,
        "kind": message.kind,
        "links": message.links,
        "headers": message.headers,
    }
    return seal(settings.secret_key.get_secret_value(), PURPOSE, json.dumps(payload).encode())


def _unpack(settings: Settings, value: bytes) -> OutgoingEmail:
    payload = json.loads(unseal(settings.secret_key.get_secret_value(), PURPOSE, value))
    return OutgoingEmail(
        to=payload["to"],
        subject=payload["subject"],
        text=payload["text"],
        kind=payload["kind"],
        links=payload.get("links") or {},
        headers=payload.get("headers") or {},
    )


def is_permanent(exc: BaseException) -> bool:
    """Would sending this email again fail the same way?"""
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return True
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return False  # our login is wrong: retry while staff fix the settings
    if isinstance(exc, smtplib.SMTPResponseException):
        return 500 <= exc.smtp_code < 600
    return False


def _describe(exc: BaseException) -> str:
    """Error text for staff. SMTP replies can echo the address, which stays sealed: keep the
    code and exception type only for refused recipients."""
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        codes = sorted({code for code, _ in exc.recipients.values()})
        return f"SMTPRecipientsRefused: recipient refused ({', '.join(map(str, codes))})"
    text = f"{type(exc).__name__}: {exc}".strip()
    return text[:ERROR_LIMIT]


class OutboxEmailProvider:
    """Queues emails in ``email_outbox`` instead of sending them in the caller's process."""

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        dispatch: Dispatch,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.dispatch = dispatch

    async def send(self, message: OutgoingEmail) -> None:
        email_id = uuid.uuid4()
        async with self.session_factory() as db:
            db.add(
                OutboxEmail(
                    id=email_id,
                    kind=message.kind,
                    status=OutboxStatus.PENDING,
                    sealed=_pack(self.settings, message),
                )
            )
            await db.commit()
        try:
            await self.dispatch(email_id)
        except Exception:
            # Stored and committed: the sweep delivers it within a minute.
            logger.exception("email dispatch failed", extra={"kind": message.kind})


async def deliver(
    factory: async_sessionmaker[AsyncSession],
    transport: EmailProvider,
    settings: Settings,
    email_id: uuid.UUID,
) -> str | None:
    """Try to send one queued email if it is due. Returns its status afterwards, or None when
    it was not due (already sent, waiting for a retry, or being sent by another worker)."""
    async with factory() as db:
        row = (
            await db.execute(
                select(OutboxEmail)
                .where(
                    OutboxEmail.id == email_id,
                    OutboxEmail.status == OutboxStatus.PENDING,
                    OutboxEmail.next_attempt_at <= func.now(),
                )
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if row is None:
            await db.commit()
            return None
        now = utcnow()
        row.attempts += 1
        try:
            if row.sealed is None:
                raise SealedValueError("no message")
            message = _unpack(settings, row.sealed)
        except (SealedValueError, ValueError, KeyError) as exc:
            # Sealed with another SECRET_KEY, or damaged: it can never be sent.
            _finish(row, OutboxStatus.FAILED, now, f"Cannot open the queued message: {exc}")
            logger.error("queued email unreadable", extra={"kind": row.kind})
            await db.commit()
            return row.status
        try:
            await transport.send(message)
        except Exception as exc:
            error = _describe(exc)
            if is_permanent(exc) or row.attempts >= MAX_ATTEMPTS:
                _finish(row, OutboxStatus.FAILED, now, error)
                logger.error("email failed", extra={"kind": row.kind, "attempts": row.attempts})
            else:
                row.last_error = error
                row.next_attempt_at = now + timedelta(minutes=RETRY_DELAYS[row.attempts - 1])
                logger.warning(
                    "email will be retried",
                    extra={"kind": row.kind, "attempts": row.attempts, "error": error},
                )
        else:
            _finish(row, OutboxStatus.SENT, now, None)
        await db.commit()
        return row.status


def _finish(row: OutboxEmail, status: OutboxStatus, now: datetime, error: str | None) -> None:
    row.status = status
    row.sealed = None  # erase the message (it can carry sign-in links)
    if status == OutboxStatus.SENT:
        row.sent_at = now
    else:
        row.failed_at = now
        row.last_error = error


async def deliver_due(
    factory: async_sessionmaker[AsyncSession],
    transport: EmailProvider,
    settings: Settings,
    *,
    limit: int = SWEEP_BATCH,
) -> int:
    """Deliver queued emails that are due, oldest first. Returns how many were sent."""
    async with factory() as db:
        ids = list(
            (
                await db.execute(
                    select(OutboxEmail.id)
                    .where(
                        OutboxEmail.status == OutboxStatus.PENDING,
                        OutboxEmail.next_attempt_at <= func.now(),
                    )
                    .order_by(OutboxEmail.next_attempt_at, OutboxEmail.created_at)
                    .limit(limit)
                )
            ).scalars()
        )
        await db.commit()
    sent = 0
    for email_id in ids:
        if await deliver(factory, transport, settings, email_id) == OutboxStatus.SENT:
            sent += 1
    return sent


async def purge(
    factory: async_sessionmaker[AsyncSession], settings: Settings, now: datetime
) -> int:
    """Remove sent and failed rows older than ``EMAIL_OUTBOX_KEEP_DAYS``."""
    cutoff = now - timedelta(days=settings.email_outbox_keep_days)
    async with factory() as db:
        result = await db.execute(
            delete(OutboxEmail).where(
                OutboxEmail.status != OutboxStatus.PENDING, OutboxEmail.created_at < cutoff
            )
        )
        await db.commit()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


@dataclass(frozen=True)
class OutboxStats:
    sent_last_day: int
    failed_last_day: int
    retrying: int
    oldest_pending: datetime | None
    last_error: str | None


async def stats(db: AsyncSession, now: datetime) -> OutboxStats:
    day_ago = now - timedelta(days=1)

    async def count(*where: object) -> int:
        return int(
            (await db.execute(select(func.count()).select_from(OutboxEmail).where(*where)))  # type: ignore[arg-type]
            .scalar_one()
        )

    pending = OutboxEmail.status == OutboxStatus.PENDING
    oldest = (
        await db.execute(select(func.min(OutboxEmail.created_at)).where(pending))
    ).scalar_one_or_none()
    last_error = (
        await db.execute(
            select(OutboxEmail.last_error)
            .where(OutboxEmail.last_error.is_not(None), OutboxEmail.created_at >= day_ago)
            .order_by(OutboxEmail.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return OutboxStats(
        sent_last_day=await count(
            OutboxEmail.status == OutboxStatus.SENT, OutboxEmail.sent_at >= day_ago
        ),
        failed_last_day=await count(
            OutboxEmail.status == OutboxStatus.FAILED, OutboxEmail.failed_at >= day_ago
        ),
        retrying=await count(pending, OutboxEmail.attempts > 0),
        oldest_pending=oldest,
        last_error=last_error,
    )


# --- Wiring ----------------------------------------------------------------------------


async def _celery_dispatch(email_id: uuid.UUID) -> None:
    from app.worker import celery_app

    await asyncio.to_thread(celery_app.send_task, DELIVER_TASK, args=[str(email_id)])


def create_sender(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    transport: EmailProvider,
) -> EmailProvider:
    """The provider callers use: the outbox when ``EMAIL_OUTBOX`` is on, else ``transport``."""
    if not settings.email_outbox:
        return transport
    if settings.jobs_mode == JobsMode.INLINE:

        async def inline(email_id: uuid.UUID) -> None:
            await deliver(session_factory, transport, settings, email_id)

        return OutboxEmailProvider(settings, session_factory, inline)
    return OutboxEmailProvider(settings, session_factory, _celery_dispatch)
