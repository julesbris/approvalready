"""Scheduled delivery (Celery beat, ``app/worker.py``).

* ``deliver_due_reminders``: every few minutes, each reminder whose time has come becomes a
  notification for its recipient (and an email on the ``EMAIL`` channel). Recurring
  reminders move to their next time; the rest are marked sent.
* ``daily_alerts``: once a day, staff hear about source references due for review, and the
  owners of grant projects hear when a round of a program they matched opens or is about to
  close.

Jobs run as the application role. Finding work across organisations goes through
``SECURITY DEFINER`` functions that return ids only (``due_reminders``,
``grant_alert_projects``); everything else is read with that one organisation bound, so
row-level security applies exactly as it does to requests.
"""

from __future__ import annotations

import calendar
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.email import EmailProvider
from app.db.tenant import bind_tenant
from app.modules.grants.matching import round_state
from app.modules.grants.models import GrantProgram, GrantRound, ProgramStatus, RoundStatus
from app.modules.notifications import service
from app.modules.notifications.models import NotificationKind
from app.modules.notifications.reminders import BRISBANE, local_today
from app.modules.projects.models import (
    Project,
    Recurrence,
    Reminder,
    ReminderChannel,
    ReminderStatus,
    Task,
    TaskStatus,
)
from app.modules.regulatory.models import SourceReference, VerificationStatus
from app.modules.tenancy import service as tenancy
from app.modules.tenancy.models import Organisation, OrganisationKind, OrganisationMember
from app.modules.tenancy.rbac import Perm

Factory = async_sessionmaker[AsyncSession]
Job = Callable[[Factory, EmailProvider, Settings], Awaitable[int]]

# Staff hear about source references this many days before they fall due.
SOURCES_DUE_WITHIN_DAYS = 14
# A round counts as newly open for this many days after its opening date.
NEWLY_OPEN_DAYS = 7
# Grant matches worth an alert: not ineligible.
ALERT_MATCHES = ("STRONG_MATCH", "POSSIBLE_MATCH", "NEEDS_INFORMATION")


def utcnow() -> datetime:
    return datetime.now(UTC)


def _add_months(moment: datetime, months: int) -> datetime:
    month = moment.month - 1 + months
    year = moment.year + month // 12
    month = month % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def next_occurrence(fires_at: datetime, recurrence: str, now: datetime) -> datetime:
    """The first repeat after ``now``, stepping in local time (Brisbane has no daylight
    saving, so local and absolute steps agree; months keep the day where they can)."""
    local = fires_at.astimezone(BRISBANE)
    anchor_day = local.day
    step = 0
    candidate = local
    while candidate <= now:
        step += 1
        match Recurrence(recurrence):
            case Recurrence.WEEKLY:
                candidate = local + timedelta(weeks=step)
            case Recurrence.MONTHLY:
                candidate = _add_months(local.replace(day=1), step)
                candidate = candidate.replace(
                    day=min(anchor_day, calendar.monthrange(candidate.year, candidate.month)[1])
                )
            case Recurrence.YEARLY:
                candidate = _add_months(local.replace(day=1), 12 * step)
                candidate = candidate.replace(
                    day=min(anchor_day, calendar.monthrange(candidate.year, candidate.month)[1])
                )
    return candidate


async def _still_relevant(db: AsyncSession, r: Reminder) -> bool:
    if await tenancy.membership(db, r.recipient_user_id, r.organisation_id) is None:
        return False
    if r.project_id is not None:
        project = await db.get(Project, r.project_id)
        if project is None or project.deleted_at is not None:
            return False
    if r.task_id is not None:
        task = await db.get(Task, r.task_id)
        if task is None or task.deleted_at is not None or task.status != TaskStatus.OPEN:
            return False
    return True


async def deliver_due_reminders(
    factory: Factory, provider: EmailProvider, settings: Settings, *, limit: int = 200
) -> int:
    """Deliver reminders that are due. Safe to run concurrently: each reminder is locked
    (``SKIP LOCKED``) and a notification is created at most once per firing."""
    async with factory() as db:
        due = (
            await db.execute(
                text("SELECT id, organisation_id FROM due_reminders(:n)"), {"n": limit}
            )
        ).all()
        await db.commit()
    delivered = 0
    for reminder_id, organisation_id in due:
        async with factory() as db:
            await bind_tenant(db, organisation_id)
            r = (
                await db.execute(
                    select(Reminder)
                    .where(
                        Reminder.id == reminder_id,
                        Reminder.organisation_id == organisation_id,
                        Reminder.status == ReminderStatus.SCHEDULED,
                        Reminder.fires_at <= func.now(),
                    )
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if r is None:
                continue
            if not await _still_relevant(db, r):
                r.status = ReminderStatus.CANCELLED
                await db.commit()
                continue
            email = r.channel == ReminderChannel.EMAIL
            nid = await service.create(
                db,
                organisation_id=organisation_id,
                recipient_user_id=r.recipient_user_id,
                kind=NotificationKind.REMINDER,
                title=r.title,
                body=r.body,
                link_path=r.link_path or (f"/projects/{r.project_id}" if r.project_id else None),
                project_id=r.project_id,
                reminder_id=r.id,
                dedupe_key=f"reminder:{r.id}:{r.fires_at.isoformat()}",
                email=email,
            )
            now = utcnow()
            r.sent_at = now
            if r.recurrence:
                r.fires_at = next_occurrence(r.fires_at, r.recurrence, now)
            else:
                r.status = ReminderStatus.SENT
            await db.commit()
            delivered += 1
            if nid is not None and email:
                await service.send_emails(db, provider, settings, organisation_id, [nid])
    return delivered


# --- Daily alerts ----------------------------------------------------------------------


async def _sources_due(
    factory: Factory, provider: EmailProvider, settings: Settings, today: date
) -> int:
    async with factory() as db:
        due = int(
            (
                await db.execute(
                    select(func.count()).where(
                        SourceReference.next_review_due.is_not(None),
                        SourceReference.next_review_due
                        <= today + timedelta(days=SOURCES_DUE_WITHIN_DAYS),
                        SourceReference.verification_status == VerificationStatus.VERIFIED,
                    )
                )
            ).scalar_one()
        )
        orgs = list(
            (
                await db.execute(
                    select(Organisation.id).where(
                        Organisation.kind == OrganisationKind.PLATFORM_ADMIN,
                        Organisation.deleted_at.is_(None),
                    )
                )
            ).scalars()
        )
        await db.commit()
    if due == 0:
        return 0
    year, week, _ = today.isocalendar()
    title = (
        "1 verified source reference is due for review"
        if due == 1
        else f"{due} verified source references are due for review"
    )
    created = 0
    for org_id in orgs:
        async with factory() as db:
            await bind_tenant(db, org_id)
            members = (
                await db.execute(
                    select(OrganisationMember.user_id).where(
                        OrganisationMember.organisation_id == org_id
                    )
                )
            ).scalars()
            ids: list[uuid.UUID] = []
            for user_id in members:
                m = await tenancy.membership(db, user_id, org_id)
                if m is None or Perm.SOURCE_VERIFY not in m.permissions:
                    continue
                nid = await service.create(
                    db,
                    organisation_id=org_id,
                    recipient_user_id=user_id,
                    kind=NotificationKind.SOURCES_DUE,
                    title=title,
                    body=f"Due or overdue within the next {SOURCES_DUE_WITHIN_DAYS} days. "
                    "Findings that rely on an overdue source drop to review required.",
                    link_path="/admin/sources",
                    dedupe_key=f"sources_due:{year}-W{week:02d}",
                )
                if nid is not None:
                    ids.append(nid)
            await db.commit()
            created += len(ids)
            await service.send_emails(db, provider, settings, org_id, ids)
    return created


def _round_alerts(
    rounds: list[tuple[GrantRound, GrantProgram]], today: date
) -> list[tuple[GrantRound, GrantProgram, str, str]]:
    """(round, program, alert kind, title) for rounds opening or about to close."""
    alerts = []
    for r, program in rounds:
        state = round_state(r, today)
        if state.state != RoundStatus.OPEN:
            continue
        if state.closing_soon and r.closes_on is not None:
            when = r.closes_on.strftime("%-d %B %Y")
            alerts.append((r, program, "closing", f"{program.title}: {r.title} closes {when}"))
        elif r.opens_on is not None and timedelta(0) <= today - r.opens_on <= timedelta(
            days=NEWLY_OPEN_DAYS
        ):
            alerts.append((r, program, "open", f"{program.title}: {r.title} is open"))
    return alerts


async def _grant_rounds(
    factory: Factory, provider: EmailProvider, settings: Settings, today: date
) -> int:
    async with factory() as db:
        rounds = list(
            (
                await db.execute(
                    select(GrantRound, GrantProgram)
                    .join(GrantProgram, GrantProgram.id == GrantRound.program_id)
                    .where(GrantProgram.status == ProgramStatus.ACTIVE)
                )
            ).tuples()
        )
        alerts = _round_alerts(rounds, today)
        targets: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID | None]] = []
        if alerts:
            targets = [
                (row[0], row[1], row[2], row[3])
                for row in await db.execute(
                    text(
                        "SELECT organisation_id, project_id, program_id, created_by "
                        "FROM grant_alert_projects(:programs, :statuses)"
                    ),
                    {
                        "programs": list({p.id for _, p, _, _ in alerts}),
                        "statuses": list(ALERT_MATCHES),
                    },
                )
            ]
        await db.commit()
    created = 0
    for org_id, project_id, program_id, owner in targets:
        if owner is None:
            continue
        async with factory() as db:
            await bind_tenant(db, org_id)
            if await tenancy.membership(db, owner, org_id) is None:
                continue
            ids = []
            for r, program, kind, title in alerts:
                if program.id != program_id:
                    continue
                nid = await service.create(
                    db,
                    organisation_id=org_id,
                    recipient_user_id=owner,
                    kind=NotificationKind.GRANT_ROUND,
                    title=title,
                    body="Your grant project matched this program. Check the round's source "
                    "before you rely on its dates.",
                    link_path=f"/projects/{project_id}",
                    project_id=project_id,
                    dedupe_key=f"grant_round:{r.id}:{kind}:{project_id}",
                )
                if nid is not None:
                    ids.append(nid)
            await db.commit()
            created += len(ids)
            await service.send_emails(db, provider, settings, org_id, ids)
    return created


async def daily_alerts(
    factory: Factory, provider: EmailProvider, settings: Settings, *, today: date | None = None
) -> int:
    today = today or local_today()
    return await _sources_due(factory, provider, settings, today) + await _grant_rounds(
        factory, provider, settings, today
    )
