"""Operations (Milestone 17): the checks, the watchdog's alerts, the off-site copy of backups,
``/health/jobs``, ``/v1/admin/ops`` and error-tracking scrubbing.

The backup service itself (infrastructure/backup/backup.sh) writes ``backup_run`` rows as the
owner; these tests write the same rows through ``owner_sessions``. The table is emptied
before each test, because the test database is shared.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors_tracking import scrub
from app.modules.notifications.models import Notification, NotificationKind
from app.modules.ops import checks, offsite, service
from app.modules.ops.checks import CheckState
from app.modules.ops.models import BackupRun, OffsiteStatus
from tests.conftest import make_settings
from tests.harness import ApiHarness, platform_user

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 10, 6, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
async def no_backup_runs(
    migrated: None, owner_sessions: async_sessionmaker[AsyncSession]
) -> AsyncIterator[None]:
    async with owner_sessions() as db:
        await db.execute(delete(BackupRun))
        await db.commit()
    yield
    async with owner_sessions() as db:
        await db.execute(delete(BackupRun))
        await db.commit()


async def add_run(
    owner_sessions: async_sessionmaker[AsyncSession],
    *,
    kind: str = "BACKUP",
    status: str = "OK",
    finished: datetime = NOW - timedelta(hours=3),
    **values: Any,
) -> uuid.UUID:
    if kind == "BACKUP" and status == "OK":
        values.setdefault("database_file", "db-20261010T000000Z.dump")
        values.setdefault("database_bytes", 1_000_000)
        values.setdefault("offsite_status", "PENDING")
    run = BackupRun(
        kind=kind,
        status=status,
        started_at=finished - timedelta(minutes=1),
        finished_at=finished,
        **values,
    )
    async with owner_sessions() as db:
        db.add(run)
        await db.commit()
        return run.id


# --- Checks -----------------------------------------------------------------------------


def test_heartbeat_check() -> None:
    s = make_settings()
    assert checks.heartbeat_check(None, s, NOW).state == CheckState.FAILING
    assert checks.heartbeat_check(NOW - timedelta(minutes=4), s, NOW).state == CheckState.OK
    stale = checks.heartbeat_check(NOW - timedelta(minutes=40), s, NOW)
    assert stale.state == CheckState.FAILING
    assert "40 minutes ago" in stale.detail


def test_queue_check() -> None:
    assert checks.queue_check(3).state == CheckState.OK
    assert checks.queue_check(checks.QUEUE_WARNING).state == CheckState.WARNING
    assert checks.queue_check(checks.QUEUE_FAILING).state == CheckState.FAILING


def test_disk_check(tmp_path: Path) -> None:
    # A path that doesn't exist yet is measured on its nearest existing parent.
    check = checks.disk_check(str(tmp_path / "not" / "there"))
    assert check.key == "disk"
    assert "GB free" in check.detail


async def test_backup_checks(owner_sessions: async_sessionmaker[AsyncSession]) -> None:
    s = make_settings()
    async with owner_sessions() as db:
        assert checks.backup_check(None, s, NOW).state == CheckState.FAILING
        await add_run(owner_sessions, finished=NOW - timedelta(hours=30))
        old = await checks.latest_run(db, checks.BackupKind.BACKUP)
        assert checks.backup_check(old, s, NOW).state == CheckState.FAILING
        await add_run(owner_sessions, finished=NOW - timedelta(hours=2))
        good = await checks.latest_run(db, checks.BackupKind.BACKUP)
        ok = checks.backup_check(good, s, NOW)
        assert ok.state == CheckState.OK
        assert "database 1.0 MB" in ok.detail
        await add_run(owner_sessions, status="FAILED", finished=NOW, detail="pg_dump failed: x")
        failed = await checks.latest_run(db, checks.BackupKind.BACKUP)
        check = checks.backup_check(failed, s, NOW)
        assert check.state == CheckState.FAILING
        assert "pg_dump failed" in check.detail
        # The newest *good* backup is still found for the off-site check.
        latest_good = await checks.latest_run(db, checks.BackupKind.BACKUP, ok_only=True)
        assert latest_good is not None and latest_good.id == good.id  # type: ignore[union-attr]


def test_restore_and_offsite_checks() -> None:
    s = make_settings()
    restore = BackupRun(kind="RESTORE_CHECK", status="OK", finished_at=NOW, detail="104 tables")
    assert checks.restore_check(None, NOW).state == CheckState.WARNING
    assert checks.restore_check(restore, NOW).state == CheckState.OK
    assert checks.restore_check(restore, NOW + timedelta(days=9)).state == CheckState.WARNING
    restore.status = "FAILED"
    assert checks.restore_check(restore, NOW).state == CheckState.FAILING

    # Not set up: a warning, never an alert.
    backup = BackupRun(kind="BACKUP", status="OK", finished_at=NOW, offsite_status="PENDING")
    assert checks.offsite_check(backup, s, NOW).state == CheckState.WARNING
    s3 = make_settings(
        backup_s3_bucket="b", backup_s3_access_key_id="k", backup_s3_secret_access_key="s"
    )
    assert checks.offsite_check(backup, s3, NOW + timedelta(hours=1)).state == CheckState.OK
    late = checks.offsite_check(backup, s3, NOW + timedelta(hours=5))
    assert late.state == CheckState.FAILING
    backup.offsite_status = "UPLOADED"
    assert checks.offsite_check(backup, s3, NOW + timedelta(hours=5)).state == CheckState.OK


# --- Off-site copy ----------------------------------------------------------------------


class FakeUploader:
    def __init__(self, fail: bool = False, short: bool = False) -> None:
        self.keys: list[str] = []
        self.fail = fail
        self.short = short

    def upload(self, path: Path, key: str) -> int:
        if self.fail:
            raise RuntimeError("bucket unreachable")
        self.keys.append(key)
        return path.stat().st_size - (1 if self.short else 0)


def s3_settings(backup_dir: Path) -> Settings:
    return make_settings(
        backup_dir=str(backup_dir),
        backup_s3_bucket="approvalready-backups",
        backup_s3_access_key_id="key",
        backup_s3_secret_access_key="secret",
        backup_s3_prefix="prod",
    )


async def offsite_row(owner_sessions: async_sessionmaker[AsyncSession], run_id: uuid.UUID) -> Any:
    async with owner_sessions() as db:
        return await db.get(BackupRun, run_id)


async def test_ship_copies_backups_off_the_server(
    app: FastAPI, tmp_path: Path, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    (tmp_path / "db-1.dump").write_bytes(b"dump" * 10)
    (tmp_path / "uploads-1.tgz").write_bytes(b"tgz" * 5)
    run_id = await add_run(
        owner_sessions,
        finished=datetime.now(UTC),
        database_file="db-1.dump",
        database_bytes=40,
        uploads_file="uploads-1.tgz",
        uploads_bytes=15,
    )
    async with app.router.lifespan_context(app):
        factory = app.state.resources.session_factory
        # Not configured: nothing happens and the backup stays pending.
        assert await offsite.ship(factory, make_settings()) == offsite.ShipResult()
        uploader = FakeUploader()
        result = await offsite.ship(
            factory, s3_settings(tmp_path), uploader_factory=lambda _: uploader
        )
        assert result == offsite.ShipResult(uploaded=1)
        assert uploader.keys == ["prod/db/db-1.dump", "prod/uploads/uploads-1.tgz"]
        row = await offsite_row(owner_sessions, run_id)
        assert row.offsite_status == OffsiteStatus.UPLOADED
        assert row.offsite_at is not None and row.offsite_attempts == 1
        # Done: a second pass uploads nothing.
        again = await offsite.ship(
            factory, s3_settings(tmp_path), uploader_factory=lambda _: uploader
        )
        assert again == offsite.ShipResult()


async def test_ship_records_failures_and_missing_files(
    app: FastAPI, tmp_path: Path, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    (tmp_path / "db-2.dump").write_bytes(b"x" * 10)
    failing = await add_run(
        owner_sessions,
        finished=datetime.now(UTC) - timedelta(hours=1),
        database_file="db-2.dump",
        database_bytes=10,
    )
    missing = await add_run(
        owner_sessions,
        finished=datetime.now(UTC),
        database_file="db-gone.dump",
        database_bytes=10,
    )
    async with app.router.lifespan_context(app):
        factory = app.state.resources.session_factory
        result = await offsite.ship(
            factory, s3_settings(tmp_path), uploader_factory=lambda _: FakeUploader(fail=True)
        )
        assert result == offsite.ShipResult(failed=1, missing=1)
        row = await offsite_row(owner_sessions, failing)
        assert row.offsite_status == OffsiteStatus.FAILED
        assert "bucket unreachable" in row.offsite_error
        assert (await offsite_row(owner_sessions, missing)).offsite_status == "MISSING"
        # A short upload is a failure too, and failed copies are retried.
        result = await offsite.ship(
            factory, s3_settings(tmp_path), uploader_factory=lambda _: FakeUploader(short=True)
        )
        assert result == offsite.ShipResult(failed=1)
        assert "expected 10" in (await offsite_row(owner_sessions, failing)).offsite_error
        result = await offsite.ship(
            factory, s3_settings(tmp_path), uploader_factory=lambda _: FakeUploader()
        )
        assert result == offsite.ShipResult(uploaded=1)


async def test_ship_never_reads_outside_the_backups_volume(
    app: FastAPI, tmp_path: Path, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    inside = tmp_path / "backups"
    inside.mkdir()
    (tmp_path / "secret.dump").write_bytes(b"s")
    run_id = await add_run(
        owner_sessions, finished=datetime.now(UTC), database_file="../secret.dump"
    )
    async with app.router.lifespan_context(app):
        uploader = FakeUploader()
        await offsite.ship(
            app.state.resources.session_factory,
            s3_settings(inside),
            uploader_factory=lambda _: uploader,
        )
    assert uploader.keys == []
    assert (await offsite_row(owner_sessions, run_id)).offsite_status == "MISSING"


async def test_app_role_may_only_record_the_offsite_copy(
    app: FastAPI, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    run_id = await add_run(owner_sessions)
    async with app.router.lifespan_context(app):
        factory = app.state.resources.session_factory
        async with factory() as db:
            await db.execute(
                update(BackupRun)
                .where(BackupRun.id == run_id)
                .values(offsite_status="UPLOADED", offsite_attempts=1)
            )
            await db.commit()
        for stmt in (
            update(BackupRun).where(BackupRun.id == run_id).values(status="FAILED"),
            delete(BackupRun).where(BackupRun.id == run_id),
            text(
                "INSERT INTO backup_run (kind, status, started_at) VALUES ('BACKUP', 'OK', now())"
            ),
        ):
            async with factory() as db:
                with pytest.raises(DBAPIError, match="permission denied"):
                    await db.execute(stmt)


# --- Watchdog ---------------------------------------------------------------------------


async def test_watchdog_alerts_once_repeats_and_recovers(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    admin = await platform_user(api, "ADMIN", name="Ops Admin")
    settings = make_settings(ops_alert_emails=["ops@example.com.au"])
    resources = api.app.state.resources
    redis = resources.redis
    factory = resources.session_factory
    provider = resources.email
    now = datetime.now(UTC)
    await redis.set(checks.HEARTBEAT_KEY, now.isoformat())

    def to(address: str) -> list[str]:
        # Only the backup check is under test (the test machine's disk may be full too).
        outbox = provider.outbox  # type: ignore[attr-defined]
        return [m.subject for m in outbox if m.to == address and "Nightly backup" in m.subject]

    # No backup has ever run: the backup check fails and is announced to both.
    found = {c.key: c for c in await service.watchdog(factory, provider, settings, redis, now)}
    assert found["jobs"].state == CheckState.OK
    assert found["backup"].state == CheckState.FAILING
    assert to("ops@example.com.au") == ["Needs attention: Nightly backup"]
    assert to(admin.email) == ["Needs attention: Nightly backup"]
    async with owner_sessions() as db:
        notes = list(
            (
                await db.execute(
                    select(Notification).where(
                        Notification.recipient_user_id == uuid.UUID(admin.id),
                        Notification.kind == NotificationKind.OPS_ALERT,
                    )
                )
            ).scalars()
        )
    assert [n.link_path for n in notes if "Nightly backup" in n.title] == ["/admin/ops"]

    # Ten minutes later, still failing: nothing new. After 12 hours: a reminder.
    await service.watchdog(factory, provider, settings, redis, now + timedelta(minutes=10))
    assert len(to("ops@example.com.au")) == 1
    later = now + timedelta(hours=13)
    await redis.set(checks.HEARTBEAT_KEY, later.isoformat())
    await service.watchdog(factory, provider, settings, redis, later)
    assert len(to("ops@example.com.au")) == 2

    # A good backup arrives: one recovery message, then quiet.
    await add_run(owner_sessions, finished=later)
    await service.watchdog(factory, provider, settings, redis, later + timedelta(minutes=10))
    assert to("ops@example.com.au")[-1] == "Back to normal: Nightly backup"
    assert to(admin.email)[-1] == "Back to normal: Nightly backup"
    count = len(to("ops@example.com.au"))
    await service.watchdog(factory, provider, settings, redis, later + timedelta(minutes=20))
    assert len(to("ops@example.com.au")) == count


async def test_warnings_are_not_alerted(api: ApiHarness) -> None:
    resources = api.app.state.resources
    alerts = await service.plan_alerts(
        resources.redis,
        [checks.Check("offsite", "Off-site copy", CheckState.WARNING, "server only")],
        NOW,
    )
    assert alerts == []


# --- HTTP -------------------------------------------------------------------------------


async def test_health_jobs_follows_the_heartbeat(api: ApiHarness) -> None:
    redis = api.app.state.resources.redis
    await redis.delete(checks.HEARTBEAT_KEY)
    r = await api.client.get("/health/jobs")
    assert r.status_code == 503
    assert r.json() == {"status": "error"}
    await redis.set(checks.HEARTBEAT_KEY, datetime.now(UTC).isoformat())
    r = await api.client.get("/health/jobs")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    await redis.set(checks.HEARTBEAT_KEY, (datetime.now(UTC) - timedelta(hours=1)).isoformat())
    assert (await api.client.get("/health/jobs")).status_code == 503


async def test_admin_ops_page(
    api: ApiHarness, owner_sessions: async_sessionmaker[AsyncSession]
) -> None:
    await add_run(owner_sessions, finished=datetime.now(UTC))
    await add_run(
        owner_sessions,
        kind="RESTORE_CHECK",
        finished=datetime.now(UTC),
        detail="104 tables, schema 0016",
    )
    admin = await platform_user(api, "ADMIN")
    r = await admin.get("/v1/admin/ops")
    assert r.status_code == 200, r.text
    body = r.json()
    states = {c["key"]: c["state"] for c in body["checks"]}
    assert set(states) == {"jobs", "queue", "backup", "restore_check", "offsite", "disk"}
    assert states["backup"] == "OK"
    assert states["restore_check"] == "OK"
    assert states["offsite"] == "WARNING"
    assert [run["kind"] for run in body["runs"]] == ["RESTORE_CHECK", "BACKUP"]
    assert body["offsite_enabled"] is False
    assert body["error_tracking_enabled"] is False
    # Staff without platform.audit.read, and customers, can't see it.
    staff = await platform_user(api, "STAFF")
    assert (await staff.get("/v1/admin/ops")).status_code == 403
    customer = await api.user()
    assert (await customer.get("/v1/admin/ops")).status_code == 403


# --- Settings and error tracking --------------------------------------------------------


def test_offsite_backups_need_keys_in_production() -> None:
    with pytest.raises(ValueError, match="BACKUP_S3_ACCESS_KEY_ID"):
        make_settings(
            app_env="production",
            secret_key="x" * 40,
            cors_origins=["https://approvalready.com.au"],
            backup_s3_bucket="b",
        )


def test_alert_emails_from_a_comma_separated_list() -> None:
    s = Settings(_env_file=None, ops_alert_emails="a@example.com, b@example.com")  # type: ignore[call-arg]
    assert s.ops_alert_emails == ["a@example.com", "b@example.com"]
    assert Settings(_env_file=None, ops_alert_emails="").ops_alert_emails == []  # type: ignore[call-arg]


def test_error_reports_carry_no_personal_data() -> None:
    event: dict[str, Any] = {
        "request": {
            "url": "https://api.example/v1/auth/login",
            "headers": {
                "Cookie": "__Host-ar_session=secret",
                "User-Agent": "Mozilla",
                "X-Request-ID": "abc",
                "X-CSRF-Token": "t",
            },
            "cookies": {"__Host-ar_session": "secret"},
            "data": {"password": "hunter2"},
            "query_string": "token=secret",
        },
        "user": {"email": "casey@example.com", "ip_address": "1.2.3.4"},
    }
    out = scrub(event)
    assert out is not None
    assert out["request"]["headers"] == {"User-Agent": "Mozilla", "X-Request-ID": "abc"}
    assert "secret" not in repr(out) and "hunter2" not in repr(out)
    assert "user" not in out
