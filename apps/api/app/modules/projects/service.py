"""Projects, status workflow, tasks and reminders.

Status workflow. Customers move a project between the states in ``USER_TRANSITIONS``;
``ASSESSED`` and ``IN_REVIEW`` are entered by the assessment (``mark_assessed``) and review
(``mark_in_review``, ``end_review``) workflows only. Every change is written to the append-only
``project_status_event`` table and the audit log.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, not_found
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.entities.models import BusinessProfile, Property, Vessel
from app.modules.projects.models import (
    Project,
    ProjectStatus,
    ProjectStatusEvent,
    Reminder,
    ReminderStatus,
    Task,
    TaskSource,
    TaskStatus,
    Vertical,
)
from app.modules.tenancy import service as tenancy

S = ProjectStatus

USER_TRANSITIONS: dict[str, frozenset[str]] = {
    S.DRAFT: frozenset({S.IN_PROGRESS, S.ARCHIVED}),
    S.IN_PROGRESS: frozenset({S.COMPLETED, S.ARCHIVED}),
    S.ASSESSED: frozenset({S.IN_PROGRESS, S.COMPLETED, S.ARCHIVED}),
    S.IN_REVIEW: frozenset(),
    S.COMPLETED: frozenset({S.IN_PROGRESS, S.ARCHIVED}),
    S.ARCHIVED: frozenset({S.IN_PROGRESS}),
}

# Which customer entity a project of each vertical may be about.
SUBJECTS: dict[str, tuple[str, type[Any]] | None] = {
    Vertical.PLANNING: ("property_id", Property),
    Vertical.SELL: ("property_id", Property),
    Vertical.RENT: ("property_id", Property),
    Vertical.VESSEL: ("vessel_id", Vessel),
    Vertical.BUSINESS: ("business_profile_id", BusinessProfile),
    Vertical.GRANT: ("business_profile_id", BusinessProfile),
    Vertical.TRADE: ("business_profile_id", BusinessProfile),
}
SUBJECT_COLUMNS = ("property_id", "vessel_id", "business_profile_id")

REFERENCE_PREFIX = {
    Vertical.PLANNING: "PLN",
    Vertical.VESSEL: "VSL",
    Vertical.BUSINESS: "BUS",
    Vertical.GRANT: "GRT",
    Vertical.SELL: "SEL",
    Vertical.RENT: "RNT",
    Vertical.TRADE: "TRD",
}
# Crockford base32 without I, L, O, U: unambiguous when read out over the phone.
_REFERENCE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def utcnow() -> datetime:
    return datetime.now(UTC)


def allowed_changes(project: Project) -> list[str]:
    return sorted(USER_TRANSITIONS.get(project.status, frozenset()))


async def _new_reference(db: AsyncSession, vertical: str) -> str:
    for _ in range(10):
        code = (
            REFERENCE_PREFIX[Vertical(vertical)]
            + "-"
            + "".join(secrets.choice(_REFERENCE_ALPHABET) for _ in range(6))
        )
        taken = (
            await db.execute(select(Project.id).where(Project.reference_code == code))
        ).scalar_one_or_none()
        if taken is None:
            return code
    raise RuntimeError("could not allocate a project reference")  # pragma: no cover


async def _check_subjects(
    db: AsyncSession, organisation_id: uuid.UUID, vertical: str, links: dict[str, Any]
) -> None:
    allowed = SUBJECTS[vertical]
    for column in SUBJECT_COLUMNS:
        value = links.get(column)
        if value is None:
            continue
        if allowed is None or allowed[0] != column:
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "subject_not_allowed",
                "That kind of record can't be linked to this kind of project.",
            )
        model = allowed[1]
        found = (
            await db.execute(
                select(model.id).where(
                    model.id == value,
                    model.organisation_id == organisation_id,
                    model.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if found is None:
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "subject_not_found",
                "The linked record was not found.",
            )


async def _record_status(
    db: AsyncSession,
    project: Project,
    previous: str | None,
    *,
    actor_id: uuid.UUID | None,
    meta: RequestMeta | None,
) -> None:
    db.add(
        ProjectStatusEvent(
            organisation_id=project.organisation_id,
            project_id=project.id,
            from_status=previous,
            to_status=project.status,
            actor_id=actor_id,
        )
    )
    await db.flush()
    if previous is not None:
        await audit.record(
            db,
            "project.status_changed",
            actor_user_id=actor_id,
            organisation_id=project.organisation_id,
            target_type="project",
            target_id=project.id,
            meta=meta,
            details={"from": previous, "to": project.status},
        )


# --- Projects --------------------------------------------------------------------------


async def list_projects(
    db: AsyncSession,
    organisation_id: uuid.UUID,
    *,
    vertical: str | None = None,
    include_archived: bool = False,
) -> list[Project]:
    stmt = select(Project).where(
        Project.organisation_id == organisation_id, Project.deleted_at.is_(None)
    )
    if vertical is not None:
        stmt = stmt.where(Project.vertical == vertical)
    if not include_archived:
        stmt = stmt.where(Project.status != S.ARCHIVED)
    return list((await db.execute(stmt.order_by(Project.updated_at.desc()))).scalars())


async def get_project(
    db: AsyncSession, organisation_id: uuid.UUID, project_id: uuid.UUID
) -> Project:
    project = (
        await db.execute(
            select(Project).where(
                Project.id == project_id,
                Project.organisation_id == organisation_id,
                Project.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if project is None:
        raise not_found("Project")
    return project


async def create_project(
    db: AsyncSession,
    organisation_id: uuid.UUID,
    data: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> Project:
    await _check_subjects(db, organisation_id, data["vertical"], data)
    project = Project(
        organisation_id=organisation_id,
        reference_code=await _new_reference(db, data["vertical"]),
        status=S.DRAFT,
        created_by=actor_id,
        **data,
    )
    db.add(project)
    await db.flush()
    await _record_status(db, project, None, actor_id=actor_id, meta=meta)
    await audit.record(
        db,
        "project.created",
        actor_user_id=actor_id,
        organisation_id=organisation_id,
        target_type="project",
        target_id=project.id,
        meta=meta,
        details={"vertical": project.vertical, "reference_code": project.reference_code},
    )
    return project


async def update_project(
    db: AsyncSession,
    project: Project,
    changes: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> Project:
    if "title" in changes and changes["title"] is None:
        del changes["title"]
    await _check_subjects(db, project.organisation_id, project.vertical, changes)
    applied = [k for k, v in changes.items() if getattr(project, k) != v]
    for key in applied:
        setattr(project, key, changes[key])
    if applied:
        await db.flush()
        await audit.record(
            db,
            "project.updated",
            actor_user_id=actor_id,
            organisation_id=project.organisation_id,
            target_type="project",
            target_id=project.id,
            meta=meta,
            details={"fields": sorted(applied)},
        )
    return project


async def change_status(
    db: AsyncSession,
    project: Project,
    new_status: str,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> Project:
    if new_status == project.status:
        return project
    if new_status not in USER_TRANSITIONS.get(project.status, frozenset()):
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "invalid_status_change",
            f"A project that is {project.status.replace('_', ' ').lower()} can't be "
            f"moved to {new_status.replace('_', ' ').lower()}.",
        )
    previous = project.status
    project.status = new_status
    await db.flush()
    await _record_status(db, project, previous, actor_id=actor_id, meta=meta)
    return project


async def mark_started(
    db: AsyncSession, project: Project, *, actor_id: uuid.UUID, meta: RequestMeta | None
) -> None:
    """Starting a questionnaire moves a draft project into progress."""
    if project.status == S.DRAFT:
        await change_status(db, project, S.IN_PROGRESS, actor_id=actor_id, meta=meta)


async def mark_assessed(
    db: AsyncSession, project: Project, *, actor_id: uuid.UUID, meta: RequestMeta | None
) -> None:
    """A completed assessment moves the project to ``ASSESSED`` (a system transition), except
    while it is with a professional reviewer."""
    if project.status in (S.ASSESSED, S.IN_REVIEW, S.ARCHIVED):
        return
    previous = project.status
    project.status = S.ASSESSED
    await db.flush()
    await _record_status(db, project, previous, actor_id=actor_id, meta=meta)


async def mark_in_review(
    db: AsyncSession, project: Project, *, actor_id: uuid.UUID | None, meta: RequestMeta | None
) -> None:
    """A review request moves the project to ``IN_REVIEW`` (a system transition); customers
    can't move it elsewhere until the review ends."""
    if project.status == S.IN_REVIEW:
        return
    previous = project.status
    project.status = S.IN_REVIEW
    await db.flush()
    await _record_status(db, project, previous, actor_id=actor_id, meta=meta)


async def end_review(
    db: AsyncSession, project: Project, *, actor_id: uuid.UUID, meta: RequestMeta | None
) -> None:
    """A finished or cancelled review hands the project back as ``ASSESSED``."""
    if project.status != S.IN_REVIEW:
        return
    project.status = S.ASSESSED
    await db.flush()
    await _record_status(db, project, S.IN_REVIEW, actor_id=actor_id, meta=meta)


async def delete_project(
    db: AsyncSession, project: Project, *, actor_id: uuid.UUID, meta: RequestMeta | None
) -> None:
    project.deleted_at = utcnow()
    await db.flush()
    await audit.record(
        db,
        "project.deleted",
        actor_user_id=actor_id,
        organisation_id=project.organisation_id,
        target_type="project",
        target_id=project.id,
        meta=meta,
    )


async def status_events(db: AsyncSession, project: Project) -> list[ProjectStatusEvent]:
    return list(
        (
            await db.execute(
                select(ProjectStatusEvent)
                .where(ProjectStatusEvent.project_id == project.id)
                .order_by(ProjectStatusEvent.occurred_at, ProjectStatusEvent.id)
            )
        ).scalars()
    )


async def open_task_count(db: AsyncSession, project: Project) -> int:
    return int(
        (
            await db.execute(
                select(func.count(Task.id)).where(
                    Task.project_id == project.id,
                    Task.status == TaskStatus.OPEN,
                    Task.deleted_at.is_(None),
                )
            )
        ).scalar_one()
    )


# --- Tasks -----------------------------------------------------------------------------


async def _require_member(db: AsyncSession, organisation_id: uuid.UUID, user_id: uuid.UUID) -> None:
    if await tenancy.membership(db, user_id, organisation_id) is None:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "not_a_member",
            "Choose someone who is a member of this organisation.",
        )


async def list_tasks(db: AsyncSession, project: Project) -> list[Task]:
    return list(
        (
            await db.execute(
                select(Task)
                .where(Task.project_id == project.id, Task.deleted_at.is_(None))
                .order_by(Task.status != TaskStatus.OPEN, Task.due_on.nulls_last(), Task.id)
            )
        ).scalars()
    )


async def get_task(db: AsyncSession, project: Project, task_id: uuid.UUID) -> Task:
    task = (
        await db.execute(
            select(Task).where(
                Task.id == task_id, Task.project_id == project.id, Task.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if task is None:
        raise not_found("Task")
    return task


async def create_task(
    db: AsyncSession, project: Project, data: dict[str, Any], *, actor_id: uuid.UUID
) -> Task:
    if data.get("assignee_user_id") is not None:
        await _require_member(db, project.organisation_id, data["assignee_user_id"])
    task = Task(
        organisation_id=project.organisation_id,
        project_id=project.id,
        created_by=actor_id,
        **data,
    )
    db.add(task)
    await db.flush()
    return task


async def add_rule_tasks(
    db: AsyncSession,
    project: Project,
    suggestions: list[tuple[uuid.UUID, str, str | None]],
    *,
    actor_id: uuid.UUID,
) -> list[Task]:
    """Tasks suggested by assessment findings, as ``(finding_id, title, notes)``. A title
    that already has an open task on the project is skipped, so re-running an assessment
    doesn't pile up duplicates; tasks from earlier runs are left as the customer left them."""
    open_titles = set(
        (
            await db.execute(
                select(Task.title).where(
                    Task.project_id == project.id,
                    Task.status == TaskStatus.OPEN,
                    Task.deleted_at.is_(None),
                )
            )
        ).scalars()
    )
    created = []
    for finding_id, title, notes in suggestions:
        if title in open_titles:
            continue
        open_titles.add(title)
        task = Task(
            organisation_id=project.organisation_id,
            project_id=project.id,
            title=title,
            notes=notes,
            source=TaskSource.RULE,
            finding_id=finding_id,
            created_by=actor_id,
        )
        db.add(task)
        created.append(task)
    await db.flush()
    return created


async def update_task(db: AsyncSession, task: Task, changes: dict[str, Any]) -> Task:
    if "title" in changes and changes["title"] is None:
        del changes["title"]
    if changes.get("status") is None:
        changes.pop("status", None)
    if changes.get("assignee_user_id") is not None:
        await _require_member(db, task.organisation_id, changes["assignee_user_id"])
    if "status" in changes and changes["status"] != task.status:
        task.completed_at = utcnow() if changes["status"] == TaskStatus.DONE else None
    for key, value in changes.items():
        setattr(task, key, value)
    await db.flush()
    return task


async def delete_task(db: AsyncSession, task: Task) -> None:
    task.deleted_at = utcnow()
    await db.flush()


# --- Reminders -------------------------------------------------------------------------


async def list_reminders(db: AsyncSession, project: Project) -> list[Reminder]:
    return list(
        (
            await db.execute(
                select(Reminder)
                .where(Reminder.project_id == project.id)
                .order_by(Reminder.fires_at, Reminder.id)
            )
        ).scalars()
    )


async def create_reminder(
    db: AsyncSession, project: Project, data: dict[str, Any], *, actor_id: uuid.UUID
) -> Reminder:
    fires_at: datetime = data["fires_at"]
    if fires_at.tzinfo is None:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "timezone_required",
            "Include a time zone with the reminder time.",
        )
    if fires_at <= utcnow():
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "in_the_past",
            "Choose a time in the future.",
        )
    recipient = data.get("recipient_user_id") or actor_id
    if recipient != actor_id:
        await _require_member(db, project.organisation_id, recipient)
    if data.get("task_id") is not None:
        await get_task(db, project, data["task_id"])
    reminder = Reminder(
        organisation_id=project.organisation_id,
        project_id=project.id,
        created_by=actor_id,
        **{**data, "recipient_user_id": recipient},
    )
    db.add(reminder)
    await db.flush()
    return reminder


async def cancel_reminder(db: AsyncSession, project: Project, reminder_id: uuid.UUID) -> None:
    reminder = (
        await db.execute(
            select(Reminder).where(Reminder.id == reminder_id, Reminder.project_id == project.id)
        )
    ).scalar_one_or_none()
    if reminder is None:
        raise not_found("Reminder")
    if reminder.status == ReminderStatus.SCHEDULED:
        reminder.status = ReminderStatus.CANCELLED
        await db.flush()
