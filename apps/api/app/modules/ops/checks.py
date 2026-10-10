"""Operational checks (Milestone 17): is the platform looking after itself?

Each check reads one signal and says ``OK``, ``WARNING`` (shown at ``/admin/ops`` only) or
``FAILING`` (shown there and alerted by the watchdog):

* ``jobs``: the scheduler's heartbeat (``system.heartbeat`` every 5 minutes, run by the
  worker) is recent, so reminders, scans, referrals and these checks themselves are running.
* ``queue``: jobs waiting in the worker's queue.
* ``backup``: the latest nightly backup succeeded and is recent.
* ``restore_check``: the latest weekly restore check succeeded.
* ``offsite``: the latest backup was copied off the server (when that is set up).
* ``disk``: free space on the disk holding the database, uploads and backups.
* ``privacy``: privacy requests waiting for an answer (Milestone 19); failing once one is
  past the 30 days the Australian Privacy Principles expect.

The checks never include customer data: counts, sizes, times and error text only.
"""

from __future__ import annotations

import shutil
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import cast

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.ops.models import BackupKind, BackupRun, BackupStatus, OffsiteStatus
from app.modules.privacy.models import PrivacyRequest, PrivacyRequestStatus

HEARTBEAT_KEY = "ops:heartbeat"
CELERY_QUEUE = "default"  # task_default_queue in app.worker

QUEUE_WARNING = 200
QUEUE_FAILING = 1000
RESTORE_CHECK_MAX_AGE = timedelta(days=8)  # weekly, with a day's slack
OFFSITE_GRACE = timedelta(hours=3)  # the worker copies new backups every 30 minutes
DISK_WARNING_FREE = 0.20
DISK_FAILING_FREE = 0.10


class CheckState(StrEnum):
    OK = "OK"
    WARNING = "WARNING"
    FAILING = "FAILING"


@dataclass(frozen=True)
class Check:
    key: str
    label: str
    state: CheckState
    detail: str


def _mb(size: int | None) -> str:
    if size is None:
        return "?"
    return f"{size / 1_000_000:,.1f} MB"


def _ago(moment: datetime, now: datetime) -> str:
    minutes = int((now - moment).total_seconds() // 60)
    if minutes < 2:
        return "just now"
    if minutes < 120:
        return f"{minutes} minutes ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} hours ago"
    return f"{hours // 24} days ago"


def heartbeat_check(beat: datetime | None, settings: Settings, now: datetime) -> Check:
    label = "Background jobs"
    if beat is None:
        return Check(
            "jobs",
            label,
            CheckState.FAILING,
            "No heartbeat from the scheduler and worker yet. Check that the scheduler and "
            "worker services are running.",
        )
    if now - beat > timedelta(minutes=settings.heartbeat_max_age_minutes):
        return Check(
            "jobs",
            label,
            CheckState.FAILING,
            f"Last heartbeat {_ago(beat, now)}: reminders, virus scans and referrals are not "
            "being processed. Check the scheduler and worker services.",
        )
    return Check("jobs", label, CheckState.OK, f"Last heartbeat {_ago(beat, now)}.")


def queue_check(waiting: int) -> Check:
    label = "Job queue"
    detail = f"{waiting} job{'s' if waiting != 1 else ''} waiting."
    if waiting >= QUEUE_FAILING:
        return Check("queue", label, CheckState.FAILING, detail + " The worker is falling behind.")
    if waiting >= QUEUE_WARNING:
        return Check("queue", label, CheckState.WARNING, detail)
    return Check("queue", label, CheckState.OK, detail)


def backup_check(latest: BackupRun | None, settings: Settings, now: datetime) -> Check:
    label = "Nightly backup"
    if latest is None:
        return Check(
            "backup",
            label,
            CheckState.FAILING,
            "No backup has run yet. Check that the backup service is running.",
        )
    if latest.status == BackupStatus.FAILED:
        return Check(
            "backup",
            label,
            CheckState.FAILING,
            f"The backup {_ago(latest.finished_at, now)} failed: {latest.detail or 'no detail'}",
        )
    summary = f"database {_mb(latest.database_bytes)}, files {_mb(latest.uploads_bytes)}"
    if now - latest.finished_at > timedelta(hours=settings.backup_max_age_hours):
        return Check(
            "backup",
            label,
            CheckState.FAILING,
            f"The last good backup was {_ago(latest.finished_at, now)} ({summary}). Check "
            "that the backup service is running.",
        )
    return Check(
        "backup", label, CheckState.OK, f"Last backup {_ago(latest.finished_at, now)} ({summary})."
    )


def restore_check(latest: BackupRun | None, now: datetime) -> Check:
    label = "Restore check"
    if latest is None:
        return Check(
            "restore_check",
            label,
            CheckState.WARNING,
            "No backup has been test-restored yet (the backup service does this weekly).",
        )
    if latest.status == BackupStatus.FAILED:
        return Check(
            "restore_check",
            label,
            CheckState.FAILING,
            f"The restore check {_ago(latest.finished_at, now)} failed: "
            f"{latest.detail or 'no detail'}",
        )
    if now - latest.finished_at > RESTORE_CHECK_MAX_AGE:
        return Check(
            "restore_check",
            label,
            CheckState.WARNING,
            f"The last restore check was {_ago(latest.finished_at, now)}.",
        )
    return Check(
        "restore_check",
        label,
        CheckState.OK,
        f"A backup was restored and checked {_ago(latest.finished_at, now)}: "
        f"{latest.detail or 'ok'}",
    )


def offsite_check(latest: BackupRun | None, settings: Settings, now: datetime) -> Check:
    label = "Off-site copy"
    if not settings.offsite_backups_enabled:
        return Check(
            "offsite",
            label,
            CheckState.WARNING,
            "Backups are kept on this server only. Set BACKUP_S3_BUCKET to copy them to "
            "cloud storage, or download them regularly.",
        )
    if latest is None:
        return Check("offsite", label, CheckState.OK, "Waiting for the first backup.")
    if latest.offsite_status == OffsiteStatus.UPLOADED:
        when = latest.offsite_at or latest.finished_at
        return Check(
            "offsite", label, CheckState.OK, f"The latest backup was copied {_ago(when, now)}."
        )
    if now - latest.finished_at <= OFFSITE_GRACE and latest.offsite_status in {
        OffsiteStatus.PENDING,
        OffsiteStatus.FAILED,
    }:
        return Check("offsite", label, CheckState.OK, "The latest backup is being copied.")
    reason = latest.offsite_error or "it has not been copied yet"
    if latest.offsite_status == OffsiteStatus.MISSING:
        reason = "its files were removed from the server before they could be copied"
    return Check(
        "offsite",
        label,
        CheckState.FAILING,
        f"The backup {_ago(latest.finished_at, now)} is not off the server: {reason}",
    )


def disk_check(path: str) -> Check:
    label = "Disk space"
    target = Path(path)
    while not target.exists() and target != target.parent:
        target = target.parent
    usage = shutil.disk_usage(target)
    free = usage.free / usage.total if usage.total else 1.0
    detail = f"{usage.free / 1e9:,.1f} GB free of {usage.total / 1e9:,.1f} GB ({free:.0%})."
    if free < DISK_FAILING_FREE:
        return Check("disk", label, CheckState.FAILING, detail + " Free some space soon.")
    if free < DISK_WARNING_FREE:
        return Check("disk", label, CheckState.WARNING, detail)
    return Check("disk", label, CheckState.OK, detail)


def privacy_check(open_count: int, overdue: int, next_due: datetime | None) -> Check:
    label = "Privacy requests"
    if open_count == 0 or next_due is None:
        return Check("privacy", label, CheckState.OK, "No privacy requests waiting.")
    if overdue:
        return Check(
            "privacy",
            label,
            CheckState.FAILING,
            f"{overdue} privacy request(s) are past their 30-day answer date. Answer them at "
            "/admin/privacy.",
        )
    return Check(
        "privacy",
        label,
        CheckState.WARNING,
        f"{open_count} privacy request(s) waiting; the next is due {next_due.date().isoformat()}.",
    )


async def privacy_summary(db: AsyncSession, now: datetime) -> tuple[int, int, datetime | None]:
    open_count, overdue, next_due = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(PrivacyRequest.due_at < now),
                func.min(PrivacyRequest.due_at),
            ).where(PrivacyRequest.status == PrivacyRequestStatus.OPEN)
        )
    ).one()
    return int(open_count), int(overdue), next_due


async def latest_run(
    db: AsyncSession, kind: BackupKind, *, ok_only: bool = False
) -> BackupRun | None:
    stmt = select(BackupRun).where(BackupRun.kind == kind)
    if ok_only:
        stmt = stmt.where(BackupRun.status == BackupStatus.OK)
    return (
        await db.execute(stmt.order_by(BackupRun.finished_at.desc()).limit(1))
    ).scalar_one_or_none()


async def heartbeat(redis: Redis) -> datetime | None:
    value = await redis.get(HEARTBEAT_KEY)
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


async def collect(db: AsyncSession, redis: Redis, settings: Settings, now: datetime) -> list[Check]:
    latest_backup = await latest_run(db, BackupKind.BACKUP)
    latest_good = (
        latest_backup
        if latest_backup is None or latest_backup.status == BackupStatus.OK
        else await latest_run(db, BackupKind.BACKUP, ok_only=True)
    )
    restore = await latest_run(db, BackupKind.RESTORE_CHECK)
    beat = await heartbeat(redis)
    waiting = int(await cast("Awaitable[int]", redis.llen(CELERY_QUEUE)))
    return [
        heartbeat_check(beat, settings, now),
        queue_check(waiting),
        backup_check(latest_backup, settings, now),
        restore_check(restore, now),
        offsite_check(latest_good, settings, now),
        disk_check(settings.storage_local_root),
        privacy_check(*await privacy_summary(db, now)),
    ]
