"""Email outbox (Milestone 20): queueing, delivery, retries, permanent failures, clean-up."""

from __future__ import annotations

import smtplib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import JobsMode, Settings
from app.core.email import MemoryEmailProvider, OutgoingEmail
from app.modules.ops import checks
from app.modules.outbox import service as outbox
from app.modules.outbox.models import OutboxEmail, OutboxStatus
from tests.conftest import TEST_APP_DATABASE_URL, make_settings
from tests.harness import unique_email

pytestmark = pytest.mark.integration


@pytest.fixture
async def sessions(migrated: None) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessions as the application role, as the API and worker connect."""
    engine = create_async_engine(TEST_APP_DATABASE_URL, poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


class FailingTransport:
    def __init__(self, exc: BaseException) -> None:
        self.exc = exc
        self.calls = 0

    async def send(self, message: OutgoingEmail) -> None:
        self.calls += 1
        raise self.exc


def _settings(**overrides: object) -> Settings:
    return make_settings(email_outbox=True, **overrides)


def _message(kind: str | None = None) -> OutgoingEmail:
    return OutgoingEmail(
        to="someone@example.com",
        subject="Reset your password",
        text="Open https://app.example/reset?token=secret-token-123",
        kind=kind or f"test.{uuid.uuid4().hex[:8]}",
        links={"reset": "https://app.example/reset?token=secret-token-123"},
    )


async def _queue(
    sessions: async_sessionmaker[AsyncSession], settings: Settings, message: OutgoingEmail
) -> uuid.UUID:
    """Queue without delivering (as when the worker queue is unreachable)."""
    queued: list[uuid.UUID] = []

    async def dispatch(email_id: uuid.UUID) -> None:
        queued.append(email_id)

    await outbox.OutboxEmailProvider(settings, sessions, dispatch).send(message)
    return queued[0]


async def _row(sessions: async_sessionmaker[AsyncSession], email_id: uuid.UUID) -> OutboxEmail:
    async with sessions() as db:
        row = await db.get(OutboxEmail, email_id)
        assert row is not None
        return row


async def _make_due(sessions: async_sessionmaker[AsyncSession], email_id: uuid.UUID) -> None:
    async with sessions() as db:
        await db.execute(
            update(OutboxEmail)
            .where(OutboxEmail.id == email_id)
            .values(next_attempt_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await db.commit()


async def test_inline_sender_delivers_and_erases_the_message(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    settings = _settings(jobs_mode=JobsMode.INLINE)
    transport = MemoryEmailProvider()
    sender = outbox.create_sender(settings, sessions, transport)
    assert isinstance(sender, outbox.OutboxEmailProvider)
    message = _message()
    await sender.send(message)
    assert transport.outbox == [message]
    async with sessions() as db:
        row = (
            await db.execute(select(OutboxEmail).where(OutboxEmail.kind == message.kind))
        ).scalar_one()
    assert row.status == OutboxStatus.SENT
    assert row.sent_at is not None
    assert row.attempts == 1
    assert row.sealed is None


def test_sender_is_the_transport_when_the_outbox_is_off() -> None:
    transport = MemoryEmailProvider()
    settings = make_settings(email_outbox=False)
    assert outbox.create_sender(settings, None, transport) is transport  # type: ignore[arg-type]


async def test_queued_message_is_sealed_and_swept(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    settings = _settings()
    message = _message()
    email_id = await _queue(sessions, settings, message)
    row = await _row(sessions, email_id)
    assert row.status == OutboxStatus.PENDING
    assert row.sealed is not None
    assert b"secret-token-123" not in row.sealed
    assert b"someone@example.com" not in row.sealed

    transport = MemoryEmailProvider()
    assert await outbox.deliver_due(sessions, transport, settings) >= 1
    assert message in transport.outbox
    assert (await _row(sessions, email_id)).status == OutboxStatus.SENT
    # Delivering again does nothing.
    assert await outbox.deliver(sessions, transport, settings, email_id) is None
    assert transport.outbox.count(message) == 1


async def test_dispatch_failure_keeps_the_email_queued(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async def broken(email_id: uuid.UUID) -> None:
        raise ConnectionError("queue down")

    message = _message()
    await outbox.OutboxEmailProvider(_settings(), sessions, broken).send(message)
    async with sessions() as db:
        row = (
            await db.execute(select(OutboxEmail).where(OutboxEmail.kind == message.kind))
        ).scalar_one()
    assert row.status == OutboxStatus.PENDING


async def test_temporary_failures_back_off_then_give_up(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    settings = _settings()
    email_id = await _queue(sessions, settings, _message())
    transport = FailingTransport(ConnectionRefusedError("mail server down"))

    before = datetime.now(UTC)
    assert await outbox.deliver(sessions, transport, settings, email_id) == OutboxStatus.PENDING
    row = await _row(sessions, email_id)
    assert row.attempts == 1
    assert row.sealed is not None
    assert row.last_error is not None and "mail server down" in row.last_error
    assert row.next_attempt_at >= before + timedelta(minutes=outbox.RETRY_DELAYS[0])
    # Not due yet: left alone.
    assert await outbox.deliver(sessions, transport, settings, email_id) is None
    assert transport.calls == 1

    for _ in range(outbox.MAX_ATTEMPTS - 1):
        await _make_due(sessions, email_id)
        await outbox.deliver(sessions, transport, settings, email_id)
    row = await _row(sessions, email_id)
    assert row.status == OutboxStatus.FAILED
    assert row.attempts == outbox.MAX_ATTEMPTS
    assert row.sealed is None
    assert row.failed_at is not None


async def test_refused_recipient_fails_at_once_without_the_address(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    settings = _settings()
    email_id = await _queue(sessions, settings, _message())
    refused = smtplib.SMTPRecipientsRefused(
        {"someone@example.com": (550, b"5.1.1 <someone@example.com> no such user")}
    )
    assert (
        await outbox.deliver(sessions, FailingTransport(refused), settings, email_id)
        == OutboxStatus.FAILED
    )
    row = await _row(sessions, email_id)
    assert row.attempts == 1
    assert row.last_error is not None
    assert "550" in row.last_error
    assert "someone@example.com" not in row.last_error


@pytest.mark.parametrize(
    ("exc", "permanent"),
    [
        (smtplib.SMTPDataError(554, b"rejected"), True),
        (smtplib.SMTPSenderRefused(553, b"bad sender", "x@y"), True),
        (smtplib.SMTPDataError(451, b"try later"), False),
        (smtplib.SMTPAuthenticationError(535, b"bad login"), False),
        (smtplib.SMTPServerDisconnected("gone"), False),
        (TimeoutError(), False),
    ],
)
def test_permanent_or_temporary(exc: BaseException, permanent: bool) -> None:
    assert outbox.is_permanent(exc) is permanent


async def test_message_sealed_with_another_key_fails(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    email_id = await _queue(sessions, _settings(), _message())
    other = _settings(secret_key=SecretStr("another-secret-key-" + "x" * 40))
    transport = MemoryEmailProvider()
    assert await outbox.deliver(sessions, transport, other, email_id) == OutboxStatus.FAILED
    assert transport.outbox == []
    row = await _row(sessions, email_id)
    assert row.last_error is not None and "Cannot open" in row.last_error


async def test_purge_removes_old_finished_rows_only(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    settings = _settings()
    old = datetime.now(UTC) - timedelta(days=settings.email_outbox_keep_days + 1)
    ids = {status: uuid.uuid4() for status in OutboxStatus}
    async with sessions() as db:
        for status, email_id in ids.items():
            db.add(OutboxEmail(id=email_id, kind="test.purge", status=status, created_at=old))
        await db.commit()
    assert await outbox.purge(sessions, settings, datetime.now(UTC)) >= 2
    async with sessions() as db:
        left = set(
            (
                await db.execute(select(OutboxEmail.id).where(OutboxEmail.id.in_(ids.values())))
            ).scalars()
        )
    assert left == {ids[OutboxStatus.PENDING]}
    async with sessions() as db:  # don't leave a stale pending row for the stats tests
        await db.execute(
            update(OutboxEmail)
            .where(OutboxEmail.id == ids[OutboxStatus.PENDING])
            .values(status=OutboxStatus.FAILED)
        )
        await db.commit()


def test_email_check_states() -> None:
    now = datetime.now(UTC)
    ok = outbox.OutboxStats(12, 0, 0, None, None)
    assert checks.email_check(ok, now).state == checks.CheckState.OK
    assert "12 sent" in checks.email_check(ok, now).detail
    retrying = outbox.OutboxStats(3, 0, 1, now - timedelta(minutes=5), "TimeoutError: ")
    assert checks.email_check(retrying, now).state == checks.CheckState.WARNING
    failed = outbox.OutboxStats(3, 2, 0, None, "SMTPDataError: (554, 'rejected')")
    warning = checks.email_check(failed, now)
    assert warning.state == checks.CheckState.WARNING
    assert "554" in warning.detail
    stuck = outbox.OutboxStats(0, 0, 4, now - timedelta(hours=2), "ConnectionRefusedError")
    failing = checks.email_check(stuck, now)
    assert failing.state == checks.CheckState.FAILING
    assert "2 hours ago" in failing.detail
    assert checks.email_check(None, now).state == checks.CheckState.OK


async def test_stats_count_the_outbox(sessions: async_sessionmaker[AsyncSession]) -> None:
    settings = _settings()
    now = datetime.now(UTC)
    async with sessions() as db:
        before = await outbox.stats(db, now)
    email_id = await _queue(sessions, settings, _message())
    await outbox.deliver(sessions, FailingTransport(TimeoutError("slow")), settings, email_id)
    async with sessions() as db:
        after = await outbox.stats(db, datetime.now(UTC))
    assert after.retrying == before.retrying + 1
    assert after.oldest_pending is not None
    assert after.last_error is not None and "slow" in after.last_error
    await _make_due(sessions, email_id)
    await outbox.deliver(sessions, MemoryEmailProvider(), settings, email_id)


async def test_registration_email_goes_through_the_outbox(
    client_factory,
    sessions: async_sessionmaker[AsyncSession],  # type: ignore[no-untyped-def]
) -> None:
    client: AsyncClient
    async with client_factory(email_outbox=True) as client:
        app_email = client._transport.app.state.resources.email  # type: ignore[attr-defined]
        assert isinstance(app_email, outbox.OutboxEmailProvider)
        started = datetime.now(UTC)
        r = await client.post(
            "/v1/auth/register",
            json={
                "email": unique_email(),
                "password": "a long passphrase 1",
                "display_name": "X",
                "accept_terms": True,
            },
        )
        assert r.status_code == 202, r.text
    async with sessions() as db:
        statuses = list(
            (
                await db.execute(
                    select(OutboxEmail.status).where(
                        OutboxEmail.kind == "auth.verify_email",
                        OutboxEmail.created_at >= started,
                    )
                )
            ).scalars()
        )
    assert statuses == [OutboxStatus.SENT]
