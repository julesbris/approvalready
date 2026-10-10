"""Celery application for background work and the beat scheduler.

Run the worker:    celery -A app.worker worker --loglevel=INFO
Run the scheduler: celery -A app.worker beat --loglevel=INFO   (exactly one instance)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from celery import Celery
from celery.schedules import crontab
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.email import create_email_provider
from app.modules.documents import jobs
from app.modules.notifications import delivery

settings = get_settings()

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
    },
)


@celery_app.task(name="system.ping")
def ping() -> str:
    return "pong"


@celery_app.task(name="system.heartbeat")
def heartbeat() -> str:
    return datetime.now(UTC).isoformat()


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


@celery_app.task(name="documents.requeue_stalled")
def requeue_stalled() -> int:
    """Re-queue scans and reports still pending well after their retries would have run
    (for example when the queue was down at upload time). Jobs ignore finished work."""
    stalled = asyncio.run(jobs.stalled_jobs(settings, older_than_minutes=120))
    for kind, target_id, organisation_id in stalled:
        name = jobs.SCAN_TASK if kind == "scan" else jobs.GENERATE_TASK
        celery_app.send_task(name, args=[organisation_id, target_id])
    return len(stalled)


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
