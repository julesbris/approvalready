"""System reminders: reminders kept in step with a date the customer recorded.

A lease end, a rent review, a settlement or a certificate expiry each get reminders a set
number of days before. Every reminder's ``source_key`` names the thing, the date and the
offset (``tenancy:<id>:end:2027-03-31:60``), so saving the same date again changes nothing,
a changed date cancels the old reminders and schedules new ones, and a reminder already
sent is never sent again.

The offsets are our own nudges, not legal deadlines: a reminder says what is coming up and
points at the project's checklist and findings, which carry the sourced rules.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Reminder, ReminderChannel, ReminderStatus

BRISBANE = ZoneInfo("Australia/Brisbane")
# Reminders go out at this local time on the day they are due.
SEND_AT = time(9, 0)


def local_today() -> date:
    return datetime.now(BRISBANE).date()


@dataclass(frozen=True)
class Planned:
    key: str
    title: str
    fires_on: date
    body: str | None = None


def before(
    prefix: str,
    event_on: date | None,
    days: Iterable[int],
    title: str,
    body: str | None = None,
    *,
    today: date | None = None,
) -> list[Planned]:
    """Reminders ``days`` before ``event_on``. Offsets already in the past collapse into
    one reminder today (so a lease ending in 10 days still gets one), and nothing is
    planned once the date itself has passed."""
    if event_on is None:
        return []
    today = today or local_today()
    if event_on < today:
        return []
    planned: list[Planned] = []
    overdue: Planned | None = None
    for offset in sorted(set(days), reverse=True):
        fires_on = date.fromordinal(event_on.toordinal() - offset)
        item = Planned(f"{prefix}{event_on.isoformat()}:{offset}", title, fires_on, body)
        if fires_on >= today:
            planned.append(item)
        else:
            overdue = Planned(item.key, title, today, body)
    if overdue is not None:
        planned.insert(0, overdue)
    return planned


def _fires_at(on: date) -> datetime:
    return datetime.combine(on, SEND_AT, tzinfo=BRISBANE)


async def sync(
    db: AsyncSession,
    organisation_id: uuid.UUID,
    prefix: str,
    planned: list[Planned],
    *,
    recipient_user_id: uuid.UUID,
    project_id: uuid.UUID | None,
    link_path: str | None,
    actor_id: uuid.UUID | None,
) -> None:
    """Make the scheduled reminders under ``prefix`` exactly ``planned``."""
    existing = list(
        (
            await db.execute(
                select(Reminder).where(
                    Reminder.organisation_id == organisation_id,
                    Reminder.source_key.startswith(prefix, autoescape=True),
                )
            )
        ).scalars()
    )
    wanted = {p.key: p for p in planned}
    kept: set[str] = set()
    for r in existing:
        p = wanted.get(r.source_key or "")
        if r.status != ReminderStatus.SCHEDULED:
            if p is not None and r.status == ReminderStatus.SENT:
                kept.add(p.key)  # already told them about this date
            continue
        if p is None or (r.title, r.body, r.fires_at) != (p.title, p.body, _fires_at(p.fires_on)):
            r.status = ReminderStatus.CANCELLED
        else:
            kept.add(p.key)
    for p in planned:
        if p.key in kept:
            continue
        db.add(
            Reminder(
                organisation_id=organisation_id,
                project_id=project_id,
                recipient_user_id=recipient_user_id,
                title=p.title,
                body=p.body,
                link_path=link_path,
                fires_at=_fires_at(p.fires_on),
                channel=ReminderChannel.EMAIL,
                source_key=p.key,
                created_by=actor_id,
            )
        )
    await db.flush()


async def cancel(db: AsyncSession, organisation_id: uuid.UUID, prefix: str) -> None:
    for r in (
        await db.execute(
            select(Reminder).where(
                Reminder.organisation_id == organisation_id,
                Reminder.status == ReminderStatus.SCHEDULED,
                Reminder.source_key.startswith(prefix, autoescape=True),
            )
        )
    ).scalars():
        r.status = ReminderStatus.CANCELLED
    await db.flush()
