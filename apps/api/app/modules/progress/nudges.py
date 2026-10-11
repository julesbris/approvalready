"""Keep-going nudges: when someone stops partway through a project, remind them what is left.

Once a day (``progress.nudge``, Celery beat) every open project whose last activity was a
day, three days and a week ago gets a nudge naming exactly what is still missing (the same
items as the project page's "What's left"), linking straight to the first of them. Then the
nudges stop. They start again only after the person picks the project up and goes quiet
again, and they never go out once nothing is left, the project is completed or archived, or
the person turns "Reminders to finish your projects" off or unsubscribes.

* "Activity" is any change to the project, its answers, assessments, tasks, checklists,
  uploads or evidence (``quiet_projects``, migration 0030). Reading a page or a nudge is not.
* Each nudge's ``dedupe_key`` names the project, when it went quiet and the step, so a job
  that runs twice, or late, never repeats one. A late job sends the latest step due.
* A person gets at most one nudge email a day, about their most recently active project;
  the others wait for a later day.
* Projects in professional review are left alone: the next move is the reviewer's.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.email import EmailProvider
from app.db.tenant import bind_tenant
from app.modules.notifications import service as notifications
from app.modules.notifications.models import NotificationKind
from app.modules.progress.service import WhatsLeft, whats_left
from app.modules.projects.models import Project
from app.modules.tenancy import service as tenancy

Factory = async_sessionmaker[AsyncSession]

# Days of quiet after which each nudge goes out. The last one says it is the last.
STEPS_DAYS = (1, 3, 7)
# A project quiet this long is left alone (also covers the first run after deploying).
STOP_AFTER_DAYS = 14
BATCH = 1000

# Notification bodies are capped at 1000 characters (``notification.body``).
BODY_LIMIT = 1000


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class QuietProject:
    organisation_id: uuid.UUID
    project_id: uuid.UUID
    reference_code: str
    vertical: str
    status: str
    owner_user_id: uuid.UUID | None
    last_activity_at: datetime
    stage: str
    open_tasks: int
    documents_missing: int
    checklist_open: int
    nudges_sent: int
    last_nudged_at: datetime | None


async def quiet_projects(
    db: AsyncSession,
    *,
    active_before: datetime,
    active_after: datetime | None = None,
    limit: int = BATCH,
) -> list[QuietProject]:
    """Open projects, in every organisation, last active in the window and with something
    left to do; most recently active first. Ids, stages and counts only."""
    rows = await db.execute(
        text("SELECT * FROM quiet_projects(:before, :after, :n)"),
        {
            "before": active_before,
            "after": active_after or datetime(1970, 1, 1, tzinfo=UTC),
            "n": limit,
        },
    )
    return [QuietProject(*row) for row in rows.all()]


def due_step(quiet_for: timedelta) -> int | None:
    """The nudge due after this much quiet (days), or ``None`` (too soon, or too late)."""
    if quiet_for >= timedelta(days=STOP_AFTER_DAYS):
        return None
    due = [d for d in STEPS_DAYS if quiet_for >= timedelta(days=d)]
    return due[-1] if due else None


def message(project_title: str, left: WhatsLeft, step: int) -> tuple[str, str]:
    """(title, body) of the nudge for ``step`` days of quiet."""
    name = project_title if len(project_title) <= 80 else f"{project_title[:79]}…"
    steps = len(left.items)
    if step == STEPS_DAYS[0]:
        title = f"Pick up where you left off: {name}"
    elif step == STEPS_DAYS[-1]:
        title = f"Still working on {name}? Here's what's left"
    else:
        title = f"{steps} {'step' if steps == 1 else 'steps'} left on {name}"
    closing = "Your answers are saved, so you can carry on from where you stopped."
    if step == STEPS_DAYS[-1]:
        closing += (
            " This is our last reminder about this project. It stays saved for whenever "
            "you're ready."
        )
    lines = ["What's still needed:"]
    for item in left.items:
        line = f"- {item.title}"
        if item.details:
            more = item.count - len(item.details)
            line += ": " + "; ".join(item.details) + (f" and {more} more" if more > 0 else "")
        lines.append(line)
    body = "\n".join(lines)
    room = BODY_LIMIT - len(closing) - 2
    if len(body) > room:
        body = body[: room - 1].rstrip() + "…"
    return title, f"{body}\n\n{closing}"


async def _nudge(
    factory: Factory,
    provider: EmailProvider,
    settings: Settings,
    q: QuietProject,
    owner: uuid.UUID,
    step: int,
) -> bool:
    async with factory() as db:
        await bind_tenant(db, q.organisation_id)
        if await tenancy.membership(db, owner, q.organisation_id) is None:
            return False
        project = await db.get(Project, q.project_id)
        if project is None:
            return False
        left = await whats_left(db, project)
        if left.done:
            return False
        title, body = message(project.title, left, step)
        quiet_since = int(q.last_activity_at.timestamp())
        nid = await notifications.create(
            db,
            organisation_id=q.organisation_id,
            recipient_user_id=owner,
            kind=NotificationKind.KEEP_GOING,
            title=title,
            body=body,
            link_path=left.items[0].link_path,
            project_id=project.id,
            dedupe_key=f"keep_going:{project.id}:{quiet_since}:{step}",
        )
        await db.commit()
        if nid is None:
            return False
        await notifications.send_emails(db, provider, settings, q.organisation_id, [nid])
        return True


async def send_nudges(
    factory: Factory,
    provider: EmailProvider,
    settings: Settings,
    *,
    now: datetime | None = None,
    limit: int = BATCH,
) -> int:
    """Nudge the owners of projects that went quiet. Returns how many were nudged."""
    now = now or utcnow()
    async with factory() as db:
        quiet = await quiet_projects(
            db,
            active_before=now - timedelta(days=STEPS_DAYS[0]),
            active_after=now - timedelta(days=STOP_AFTER_DAYS),
            limit=limit,
        )
        await db.commit()
    told: set[uuid.UUID] = set()
    for q in quiet:
        owner = q.owner_user_id
        if owner is None or owner in told:
            continue
        step = due_step(now - q.last_activity_at)
        if step is None:
            continue
        if await _nudge(factory, provider, settings, q, owner, step):
            told.add(owner)
    return len(told)
