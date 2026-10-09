"""Adding checklists to projects and ticking off their items.

Callers have checked permissions and bound the tenant; queries still filter by
``organisation_id``. A checklist appears once per project: adding one that is already there
returns it unchanged, so re-running an assessment never duplicates a list or resets what
the customer ticked.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, not_found
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.checklists import definition
from app.modules.checklists.models import (
    ChecklistItem,
    ChecklistOrigin,
    ItemStatus,
    ProjectChecklist,
)
from app.modules.projects.models import Project


@dataclass(frozen=True)
class ChecklistView:
    checklist: ProjectChecklist
    items: list[ChecklistItem]


async def _existing(db: AsyncSession, project: Project, key: str) -> ProjectChecklist | None:
    return (
        await db.execute(
            select(ProjectChecklist).where(
                ProjectChecklist.organisation_id == project.organisation_id,
                ProjectChecklist.project_id == project.id,
                ProjectChecklist.checklist_key == key,
            )
        )
    ).scalar_one_or_none()


async def add(
    db: AsyncSession,
    project: Project,
    key: str,
    *,
    origin: ChecklistOrigin,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
    finding_id: uuid.UUID | None = None,
) -> tuple[ProjectChecklist, bool]:
    """The project's checklist for ``key``, and whether it was created now."""
    found = definition.bundled().get(key)
    if found is None or found.vertical != project.vertical:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "unknown_checklist",
            "That checklist isn't available for this kind of project.",
        )
    existing = await _existing(db, project, key)
    if existing is not None:
        return existing, False
    checklist = ProjectChecklist(
        organisation_id=project.organisation_id,
        project_id=project.id,
        checklist_key=key,
        title=found.title,
        description=found.description,
        sources=[s.model_dump(mode="json") for s in found.sources],
        definition_hash=found.content_hash(),
        origin=origin,
        finding_id=finding_id if origin == ChecklistOrigin.RULE else None,
        created_by=actor_id,
    )
    db.add(checklist)
    await db.flush()
    for ordinal, item in enumerate(found.items, start=1):
        db.add(
            ChecklistItem(
                organisation_id=project.organisation_id,
                checklist_id=checklist.id,
                item_key=item.key,
                ordinal=ordinal,
                title=item.title,
                detail=item.detail,
                required=item.required,
            )
        )
    await db.flush()
    await audit.record(
        db,
        "checklist.added",
        actor_user_id=actor_id,
        organisation_id=project.organisation_id,
        target_type="project_checklist",
        target_id=checklist.id,
        meta=meta,
        details={"project_id": str(project.id), "key": key, "origin": str(origin)},
    )
    return checklist, True


async def add_from_findings(
    db: AsyncSession,
    project: Project,
    named: list[tuple[uuid.UUID, str]],
    *,
    actor_id: uuid.UUID,
) -> list[ProjectChecklist]:
    """Checklists named by findings, as ``(finding_id, key)``. Keys that are not (or no
    longer) a bundled checklist for this vertical are skipped: the rule editor refuses
    unknown keys, so this only happens if a file was removed after a rule was published."""
    created = []
    for finding_id, key in named:
        found = definition.bundled().get(key)
        if found is None or found.vertical != project.vertical:
            continue
        checklist, new = await add(
            db,
            project,
            key,
            origin=ChecklistOrigin.RULE,
            actor_id=actor_id,
            meta=None,
            finding_id=finding_id,
        )
        if new:
            created.append(checklist)
    return created


async def list_for_project(db: AsyncSession, project: Project) -> list[ChecklistView]:
    checklists = list(
        (
            await db.execute(
                select(ProjectChecklist)
                .where(
                    ProjectChecklist.organisation_id == project.organisation_id,
                    ProjectChecklist.project_id == project.id,
                )
                .order_by(ProjectChecklist.created_at, ProjectChecklist.id)
            )
        ).scalars()
    )
    if not checklists:
        return []
    items: dict[uuid.UUID, list[ChecklistItem]] = {c.id: [] for c in checklists}
    for item in (
        await db.execute(
            select(ChecklistItem)
            .where(
                ChecklistItem.organisation_id == project.organisation_id,
                ChecklistItem.checklist_id.in_(list(items)),
            )
            .order_by(ChecklistItem.ordinal)
        )
    ).scalars():
        items[item.checklist_id].append(item)
    return [ChecklistView(c, items[c.id]) for c in checklists]


async def get_checklist(
    db: AsyncSession, organisation_id: uuid.UUID, checklist_id: uuid.UUID
) -> ProjectChecklist:
    checklist = (
        await db.execute(
            select(ProjectChecklist).where(
                ProjectChecklist.id == checklist_id,
                ProjectChecklist.organisation_id == organisation_id,
            )
        )
    ).scalar_one_or_none()
    if checklist is None:
        raise not_found("Checklist")
    return checklist


async def get_item(
    db: AsyncSession, organisation_id: uuid.UUID, item_id: uuid.UUID
) -> ChecklistItem:
    item = (
        await db.execute(
            select(ChecklistItem).where(
                ChecklistItem.id == item_id, ChecklistItem.organisation_id == organisation_id
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise not_found("Checklist item")
    return item


async def update_item(
    db: AsyncSession,
    item: ChecklistItem,
    *,
    new_status: ItemStatus | None,
    note: str | None,
    note_given: bool,
    actor_id: uuid.UUID,
) -> ChecklistItem:
    if new_status is not None and new_status != item.status:
        if (
            new_status == ItemStatus.NOT_APPLICABLE
            and item.required
            and not (note if note_given else item.note)
        ):
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "note_required",
                "Say why this item doesn't apply to you.",
            )
        item.status = new_status
        if new_status == ItemStatus.OPEN:
            item.completed_at = None
            item.completed_by = None
        else:
            item.completed_at = datetime.now(UTC)
            item.completed_by = actor_id
    if note_given:
        item.note = note
    await db.flush()
    return item


async def remove(
    db: AsyncSession,
    checklist: ProjectChecklist,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> None:
    if checklist.origin != ChecklistOrigin.USER:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "from_assessment",
            "Your assessment added this checklist. Mark items that don't apply instead.",
        )
    await db.delete(checklist)
    await db.flush()
    await audit.record(
        db,
        "checklist.removed",
        actor_user_id=actor_id,
        organisation_id=checklist.organisation_id,
        target_type="project_checklist",
        target_id=checklist.id,
        meta=meta,
        details={"project_id": str(checklist.project_id), "key": checklist.checklist_key},
    )
