"""Progress routes.

* ``GET /v1/organisations/{organisation_id}/projects/{project_id}/whats-left``: the
  project's remaining steps, each linking to where it gets done.
* ``GET /v1/admin/progress/quiet``: staff see who stopped where (``platform.users.read``):
  projects quiet for at least ``days`` days with something left, newest first.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import DbDep, OrgContext, require_org_permission, require_platform_permission
from app.modules.identity.models import AppUser
from app.modules.progress import nudges
from app.modules.progress.schemas import LeftItemOut, QuietProjectOut, WhatsLeftOut
from app.modules.progress.service import whats_left
from app.modules.projects import service as projects
from app.modules.tenancy.models import Organisation
from app.modules.tenancy.rbac import Perm

router = APIRouter(prefix="/v1/organisations/{organisation_id}", tags=["projects"])
admin_router = APIRouter(prefix="/v1/admin/progress", tags=["admin: progress"])

Read = Annotated[OrgContext, Depends(require_org_permission(Perm.PROJECT_READ))]
Staff = Annotated[OrgContext, Depends(require_platform_permission(Perm.PLATFORM_USERS_READ))]

QUIET_LIMIT = 500


@router.get("/projects/{project_id}/whats-left", response_model=WhatsLeftOut)
async def get_whats_left(project_id: uuid.UUID, ctx: Read, db: DbDep) -> WhatsLeftOut:
    project = await projects.get_project(db, ctx.organisation.id, project_id)
    left = await whats_left(db, project)
    return WhatsLeftOut(
        done=left.done,
        items=[LeftItemOut(**item.__dict__) for item in left.items],
    )


@admin_router.get("/quiet", response_model=list[QuietProjectOut])
async def quiet_projects(
    _: Staff, db: DbDep, days: Annotated[int, Query(ge=1, le=365)] = 1
) -> list[QuietProjectOut]:
    rows = await nudges.quiet_projects(
        db, active_before=datetime.now(UTC) - timedelta(days=days), limit=QUIET_LIMIT
    )
    org_ids = {r.organisation_id for r in rows}
    user_ids = {r.owner_user_id for r in rows if r.owner_user_id is not None}
    orgs = {
        o.id: o.name
        for o in (
            await db.execute(select(Organisation).where(Organisation.id.in_(org_ids)))
        ).scalars()
    }
    users = {
        u.id: u
        for u in (await db.execute(select(AppUser).where(AppUser.id.in_(user_ids)))).scalars()
    }
    out = []
    for r in rows:
        owner = users.get(r.owner_user_id) if r.owner_user_id else None
        out.append(
            QuietProjectOut(
                **r.__dict__,
                organisation_name=orgs.get(r.organisation_id, ""),
                owner_email=owner.email if owner else None,
                owner_name=owner.display_name if owner else None,
            )
        )
    return out
