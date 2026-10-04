"""Celery application for background work and the beat scheduler.

Run the worker:    celery -A app.worker worker --loglevel=INFO
Run the scheduler: celery -A app.worker beat --loglevel=INFO   (exactly one instance)
"""

from __future__ import annotations

from datetime import UTC, datetime

from celery import Celery

from app.core.config import get_settings

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
    # Periodic jobs (reminders, subscription grace expiry, lead expiry, source review
    # due dates) are registered here as their milestones land.
    beat_schedule={
        "system-heartbeat": {"task": "system.heartbeat", "schedule": 300.0},
    },
)


@celery_app.task(name="system.ping")
def ping() -> str:
    return "pong"


@celery_app.task(name="system.heartbeat")
def heartbeat() -> str:
    return datetime.now(UTC).isoformat()
