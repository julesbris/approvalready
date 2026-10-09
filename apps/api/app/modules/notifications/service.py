"""Creating, listing and reading notifications.

Callers bind the tenant first (requests through ``require_org_permission``, jobs through
``bind_tenant``); queries still filter by organisation and recipient.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.email import EmailProvider
from app.core.errors import not_found
from app.modules.identity.models import AppUser
from app.modules.notifications import emails
from app.modules.notifications.models import EmailStatus, Notification, NotificationKind

logger = logging.getLogger(__name__)

PAGE_SIZE = 50


def utcnow() -> datetime:
    return datetime.now(UTC)


async def create(
    db: AsyncSession,
    *,
    organisation_id: uuid.UUID,
    recipient_user_id: uuid.UUID,
    kind: NotificationKind,
    title: str,
    body: str | None = None,
    link_path: str | None = None,
    project_id: uuid.UUID | None = None,
    reminder_id: uuid.UUID | None = None,
    dedupe_key: str | None = None,
    email: bool = True,
) -> uuid.UUID | None:
    """The new notification's id, or ``None`` when one with this ``dedupe_key`` exists."""
    values = {
        "organisation_id": organisation_id,
        "recipient_user_id": recipient_user_id,
        "kind": kind,
        "title": title[:200],
        "body": body[:1000] if body else None,
        "link_path": link_path,
        "project_id": project_id,
        "reminder_id": reminder_id,
        "dedupe_key": dedupe_key,
        "email_status": EmailStatus.PENDING if email else EmailStatus.NOT_REQUESTED,
    }
    stmt = insert(Notification).values(id=uuid.uuid4(), **values)
    if dedupe_key is not None:
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["organisation_id", "recipient_user_id", "dedupe_key"],
            index_where=Notification.dedupe_key.is_not(None),
        )
    return (await db.execute(stmt.returning(Notification.id))).scalar_one_or_none()


async def send_emails(
    db: AsyncSession,
    provider: EmailProvider,
    settings: Settings,
    organisation_id: uuid.UUID,
    ids: list[uuid.UUID],
) -> int:
    """Email the pending notifications in ``ids`` (call after they are committed). A failure
    is recorded on the notification and never retried by email; the in-app copy stays."""
    sent = 0
    for nid in ids:
        n = (
            await db.execute(
                select(Notification).where(
                    Notification.id == nid,
                    Notification.organisation_id == organisation_id,
                    Notification.email_status == EmailStatus.PENDING,
                )
            )
        ).scalar_one_or_none()
        if n is None:
            continue
        user = await db.get(AppUser, n.recipient_user_id)
        if user is None or user.email_verified_at is None:
            n.email_status = EmailStatus.FAILED
            await db.commit()
            continue
        message = emails.notification(
            settings, user.email, user.display_name, n.title, n.body, n.link_path
        )
        try:
            await provider.send(message)
        except Exception:
            logger.exception("notification email failed", extra={"kind": n.kind})
            n.email_status = EmailStatus.FAILED
        else:
            n.email_status = EmailStatus.SENT
            n.emailed_at = utcnow()
            sent += 1
        await db.commit()
    return sent


async def list_for(
    db: AsyncSession,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    unread_only: bool = False,
    limit: int = PAGE_SIZE,
) -> list[Notification]:
    query = select(Notification).where(
        Notification.organisation_id == organisation_id,
        Notification.recipient_user_id == user_id,
    )
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    query = query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)
    return list((await db.execute(query)).scalars())


async def unread_count(db: AsyncSession, organisation_id: uuid.UUID, user_id: uuid.UUID) -> int:
    return int(
        (
            await db.execute(
                select(func.count()).where(
                    Notification.organisation_id == organisation_id,
                    Notification.recipient_user_id == user_id,
                    Notification.read_at.is_(None),
                )
            )
        ).scalar_one()
    )


async def mark_read(
    db: AsyncSession, organisation_id: uuid.UUID, user_id: uuid.UUID, notification_id: uuid.UUID
) -> Notification:
    n = (
        await db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.organisation_id == organisation_id,
                Notification.recipient_user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if n is None:
        raise not_found("Notification")
    if n.read_at is None:
        n.read_at = utcnow()
        await db.flush()
    return n


async def mark_all_read(db: AsyncSession, organisation_id: uuid.UUID, user_id: uuid.UUID) -> int:
    result = await db.execute(
        update(Notification)
        .where(
            Notification.organisation_id == organisation_id,
            Notification.recipient_user_id == user_id,
            Notification.read_at.is_(None),
        )
        .values(read_at=utcnow())
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
