"""Checklists: ``/v1/checklists`` (the reviewed definitions) and
``/v1/organisations/{organisation_id}/projects/{id}/checklists``, ``/checklists/{id}``,
``/checklist-items/{id}``."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import AuthDep, DbDep, MetaDep, OrgContext, require_org_permission
from app.modules.checklists import definition, service
from app.modules.checklists.models import ChecklistItem, ChecklistOrigin, ItemStatus
from app.modules.checklists.schemas import (
    ChecklistAddIn,
    ChecklistDefinitionOut,
    ChecklistItemOut,
    ChecklistItemUpdateIn,
    ChecklistOut,
)
from app.modules.projects import service as projects
from app.modules.projects.models import Vertical
from app.modules.tenancy.rbac import Perm

definitions_router = APIRouter(prefix="/v1/checklists", tags=["checklists"])
router = APIRouter(prefix="/v1/organisations/{organisation_id}", tags=["checklists"])

Read = Annotated[OrgContext, Depends(require_org_permission(Perm.PROJECT_READ))]
Write = Annotated[OrgContext, Depends(require_org_permission(Perm.PROJECT_WRITE))]


def item_out(i: ChecklistItem) -> ChecklistItemOut:
    return ChecklistItemOut(
        id=i.id,
        checklist_id=i.checklist_id,
        key=i.item_key,
        title=i.title,
        detail=i.detail,
        required=i.required,
        status=ItemStatus(i.status),
        note=i.note,
        completed_at=i.completed_at,
        completed_by=i.completed_by,
    )


def checklist_out(view: service.ChecklistView) -> ChecklistOut:
    c = view.checklist
    return ChecklistOut(
        id=c.id,
        project_id=c.project_id,
        key=c.checklist_key,
        title=c.title,
        description=c.description,
        sources=c.sources,
        origin=ChecklistOrigin(c.origin),
        finding_id=c.finding_id,
        items=[item_out(i) for i in view.items],
        done=sum(1 for i in view.items if i.status != ItemStatus.OPEN),
        total=len(view.items),
        created_at=c.created_at,
    )


@definitions_router.get("", response_model=list[ChecklistDefinitionOut])
async def list_definitions(
    _: AuthDep, vertical: Vertical | None = None
) -> list[ChecklistDefinitionOut]:
    """Checklists a project can add, from the reviewed files (optionally for one vertical)."""
    found = definition.bundled().values()
    return [
        ChecklistDefinitionOut.model_validate(d.model_dump(mode="json"))
        for d in found
        if vertical is None or d.vertical == vertical
    ]


@router.get("/projects/{project_id}/checklists", response_model=list[ChecklistOut])
async def list_checklists(project_id: uuid.UUID, ctx: Read, db: DbDep) -> list[ChecklistOut]:
    project = await projects.get_project(db, ctx.organisation.id, project_id)
    return [checklist_out(v) for v in await service.list_for_project(db, project)]


@router.post(
    "/projects/{project_id}/checklists",
    status_code=status.HTTP_201_CREATED,
    response_model=ChecklistOut,
)
async def add_checklist(
    project_id: uuid.UUID, body: ChecklistAddIn, ctx: Write, db: DbDep, meta: MetaDep
) -> ChecklistOut:
    """Add a checklist to the project. Adding one that is already there returns it."""
    project = await projects.get_project(db, ctx.organisation.id, project_id)
    checklist, _ = await service.add(
        db,
        project,
        body.key,
        origin=ChecklistOrigin.USER,
        actor_id=ctx.auth.user.id,
        meta=meta,
    )
    await db.commit()
    views = await service.list_for_project(db, project)
    return checklist_out(next(v for v in views if v.checklist.id == checklist.id))


@router.delete("/checklists/{checklist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_checklist(checklist_id: uuid.UUID, ctx: Write, db: DbDep, meta: MetaDep) -> None:
    checklist = await service.get_checklist(db, ctx.organisation.id, checklist_id)
    await projects.get_project(db, ctx.organisation.id, checklist.project_id)
    await service.remove(db, checklist, actor_id=ctx.auth.user.id, meta=meta)
    await db.commit()


@router.patch("/checklist-items/{item_id}", response_model=ChecklistItemOut)
async def update_item(
    item_id: uuid.UUID, body: ChecklistItemUpdateIn, ctx: Write, db: DbDep
) -> ChecklistItemOut:
    """Tick an item off, reopen it or mark it not applicable (a required item needs a note
    saying why)."""
    item = await service.get_item(db, ctx.organisation.id, item_id)
    checklist = await service.get_checklist(db, ctx.organisation.id, item.checklist_id)
    await projects.get_project(db, ctx.organisation.id, checklist.project_id)
    await service.update_item(
        db,
        item,
        new_status=body.status,
        note=(body.note or "").strip() or None,
        note_given="note" in body.model_fields_set,
        actor_id=ctx.auth.user.id,
    )
    await db.commit()
    return item_out(item)
