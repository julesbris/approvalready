"""Celery application for background work and the beat scheduler.

Run the worker:    celery -A app.worker worker --loglevel=INFO
Run the scheduler: celery -A app.worker beat --loglevel=INFO   (exactly one instance)
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import redis
from celery import Celery
from celery.schedules import crontab
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.email import create_email_provider
from app.core.errors_tracking import init_error_tracking
from app.modules.documents import jobs
from app.modules.notifications import delivery

settings = get_settings()
init_error_tracking(settings, "worker")

celery_app = Celery(
    "approvalready",
    broker=settings.broker_url,
    backend=settings.result_backend,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],  # never pickle: payloads may originate from user input
    timezone="Australia/Brisbane",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    result_expires=3600,
    broker_connection_retry_on_startup=True,
    task_default_queue="default",
    # Periodic jobs (subscription grace expiry, lead expiry) are registered here as their
    # milestones land. Crontab times are Brisbane time (``timezone`` above).
    beat_schedule={
        "system-heartbeat": {"task": "system.heartbeat", "schedule": 300.0},
        "documents-requeue-stalled": {"task": "documents.requeue_stalled", "schedule": 600.0},
        "notifications-deliver-reminders": {
            "task": "notifications.deliver_reminders",
            "schedule": 300.0,
        },
        "notifications-daily-alerts": {
            "task": "notifications.daily_alerts",
            "schedule": crontab(hour=7, minute=30),
        },
        "leads-sweep": {"task": "leads.sweep", "schedule": 900.0},
        "ops-watchdog": {"task": "ops.watchdog", "schedule": 600.0},
        "ops-ship-backups": {"task": "ops.ship_backups", "schedule": 1800.0},
        "sources-weekly-check": {
            "task": "sources.weekly_check",
            "schedule": crontab(day_of_week="mon", hour=6, minute=0),
        },
    },
)


@celery_app.task(name="system.ping")
def ping() -> str:
    return "pong"


@celery_app.task(name="system.heartbeat")
def heartbeat() -> str:
    """Proves the scheduler and a worker are both running (``/health/jobs``, ``/admin/ops``)."""
    from app.modules.ops.checks import HEARTBEAT_KEY

    now = datetime.now(UTC).isoformat()
    client = redis.Redis.from_url(settings.redis_url, socket_timeout=5)
    try:
        client.set(HEARTBEAT_KEY, now, ex=7 * 24 * 3600)
    finally:
        client.close()
    return now


# --- Documents (Milestone 6) -----------------------------------------------------------

# Retries back off from 30 s to 10 min, about 90 minutes in all: long enough to ride out a
# ClamAV restart or signature download. After that a scan is marked ERROR.
DOCUMENT_JOB_RETRIES = 12


def _countdown(retries: int) -> int:
    return int(min(30 * 2**retries, 600))


def _run(task: Any, job: jobs.JobFn, organisation_id: str, target_id: str) -> str | None:
    final = task.request.retries >= DOCUMENT_JOB_RETRIES
    try:
        return asyncio.run(
            jobs.run_with_own_resources(
                settings, job, organisation_id, target_id, final_attempt=final
            )
        )
    except jobs.RetryLater as exc:
        raise task.retry(exc=exc, countdown=_countdown(task.request.retries)) from exc


@celery_app.task(name=jobs.SCAN_TASK, bind=True, max_retries=DOCUMENT_JOB_RETRIES)
def scan_document(self: Any, organisation_id: str, document_id: str) -> str | None:
    return _run(self, jobs.scan_job, organisation_id, document_id)


@celery_app.task(name=jobs.GENERATE_TASK, bind=True, max_retries=DOCUMENT_JOB_RETRIES)
def generate_document(self: Any, organisation_id: str, generated_id: str) -> str | None:
    return _run(self, jobs.generate_job, organisation_id, generated_id)


# --- AI drafting (Milestone 12) ---------------------------------------------------------

# Provider overloads and rate limits clear within minutes; after about half an hour the job
# fails and the customer can ask again.
AI_JOB_RETRIES = 5


@celery_app.task(name=jobs.AI_TASK, bind=True, max_retries=AI_JOB_RETRIES)
def run_ai_job(self: Any, organisation_id: str, job_id: str) -> str | None:
    final = self.request.retries >= AI_JOB_RETRIES
    try:
        return asyncio.run(
            jobs.run_with_own_resources(
                settings, jobs.ai_job, organisation_id, job_id, final_attempt=final
            )
        )
    except jobs.RetryLater as exc:
        raise self.retry(exc=exc, countdown=_countdown(self.request.retries)) from exc


# --- Payments (Milestone 13) ------------------------------------------------------------

# Applying a webhook only fails when the database is unavailable or on a bug; after about an
# hour of retries the event stays FAILED and staff can retry it at /admin/billing.
BILLING_EVENT_RETRIES = 8


@celery_app.task(name=jobs.BILLING_EVENT_TASK, bind=True, max_retries=BILLING_EVENT_RETRIES)
def process_billing_event(self: Any, event_id: str) -> str | None:
    try:
        return asyncio.run(jobs.run_billing_event(settings, event_id))
    except jobs.RetryLater as exc:
        raise self.retry(exc=exc, countdown=_countdown(self.request.retries)) from exc


@celery_app.task(name="documents.requeue_stalled")
def requeue_stalled() -> int:
    """Re-queue scans, reports, AI drafts and Stripe events still pending well after their
    retries would have run (for example when the queue was down at upload time). Jobs
    ignore finished work."""
    stalled = asyncio.run(jobs.stalled_jobs(settings, older_than_minutes=120))
    names = {"scan": jobs.SCAN_TASK, "generate": jobs.GENERATE_TASK, "ai": jobs.AI_TASK}
    for kind, target_id, organisation_id in stalled:
        name = names[kind]
        celery_app.send_task(name, args=[organisation_id, target_id])
    # Stripe events still waiting (the queue was down) or failed with tries left.
    events = asyncio.run(jobs.stalled_billing_events(settings, older_than_minutes=10))
    for event_id in events:
        celery_app.send_task(jobs.BILLING_EVENT_TASK, args=[event_id])
    return len(stalled) + len(events)


# --- Notifications (Milestone 11) ------------------------------------------------------


async def _with_own_engine(job: delivery.Job) -> int:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        factory = async_sessionmaker[AsyncSession](engine, expire_on_commit=False)
        return await job(factory, create_email_provider(settings), settings)
    finally:
        await engine.dispose()


@celery_app.task(name="notifications.deliver_reminders")
def deliver_reminders() -> int:
    """Turn due reminders into notifications and emails (every 5 minutes)."""
    return asyncio.run(_with_own_engine(delivery.deliver_due_reminders))


@celery_app.task(name="notifications.daily_alerts")
def daily_alerts() -> int:
    """Sources due for review (staff) and grant rounds opening or closing (customers)."""
    return asyncio.run(_with_own_engine(delivery.daily_alerts))


# --- Leads (Milestone 15) ---------------------------------------------------------------


@celery_app.task(name="leads.match")
def match_lead(lead_id: str) -> int:
    """Match a new lead to partners and offer the first wave."""
    from app.modules.leads import jobs as leads

    async def job(factory: Any, email: Any, s: Any) -> int:
        return await leads.match_lead(factory, email, s, uuid.UUID(lead_id))

    return asyncio.run(_with_own_engine(job))


@celery_app.task(name="leads.sweep")
def sweep_leads() -> int:
    """Expire, re-match and release open leads (every 15 minutes)."""
    from app.modules.leads import jobs as leads

    return asyncio.run(_with_own_engine(leads.sweep))


# --- Operations (Milestone 17) ----------------------------------------------------------


@celery_app.task(name="ops.watchdog")
def ops_watchdog() -> int:
    """Run the operational checks and alert platform admins (every 10 minutes)."""
    from app.modules.ops import service as ops

    async def job(factory: Any, email: Any, s: Any) -> int:
        client = Redis.from_url(s.redis_url, decode_responses=True, socket_timeout=5)
        try:
            checks = await ops.watchdog(factory, email, s, client, datetime.now(UTC))
        finally:
            await client.aclose()
        return sum(1 for c in checks if c.state != "OK")

    return asyncio.run(_with_own_engine(job))


@celery_app.task(name="ops.ship_backups")
def ship_backups() -> int:
    """Copy new backups off the server when BACKUP_S3_BUCKET is set (every 30 minutes)."""
    from app.modules.ops import offsite

    async def job(factory: Any, email: Any, s: Any) -> int:
        result = await offsite.ship(factory, s)
        return result.uploaded

    return asyncio.run(_with_own_engine(job))


# --- Source checks (Milestone 24) -------------------------------------------------------


@celery_app.task(name="sources.weekly_check")
def sources_weekly_check() -> int:
    """Read every source document from its official address (Mondays, 6 am Brisbane)."""
    from app.modules.regulatory import checks
    from app.modules.regulatory.fetch import SourceFetcher

    async def job(factory: Any, email: Any, s: Any) -> int:
        result = await checks.run_weekly(factory, email, s, SourceFetcher(s))
        return result.checked

    return asyncio.run(_with_own_engine(job))
