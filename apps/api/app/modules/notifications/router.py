"""``/v1/organisations/{organisation_id}/notifications``: the signed-in member's own
notifications in that organisation."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbDep, OrgContext, require_org_permission
from app.modules.notifications import service
from app.modules.notifications.models import Notification
from app.modules.notifications.schemas import MarkedReadOut, NotificationListOut, NotificationOut
from app.modules.tenancy.rbac import Perm

router = APIRouter(prefix="/v1/organisations/{organisation_id}", tags=["notifications"])

Member = Annotated[OrgContext, Depends(require_org_permission(Perm.ORG_READ))]


def notification_out(n: Notification) -> NotificationOut:
    return NotificationOut.model_validate(n, from_attributes=True)


@router.get("/notifications", response_model=NotificationListOut)
async def list_notifications(
    ctx: Member,
    db: DbDep,
    unread_only: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=service.PAGE_SIZE)] = service.PAGE_SIZE,
) -> NotificationListOut:
    """Newest first, with the number still unread."""
    org, user = ctx.organisation.id, ctx.auth.user.id
    items = await service.list_for(db, org, user, unread_only=unread_only, limit=limit)
    return NotificationListOut(
        unread=await service.unread_count(db, org, user),
        items=[notification_out(n) for n in items],
    )


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
async def mark_read(notification_id: uuid.UUID, ctx: Member, db: DbDep) -> NotificationOut:
    n = await service.mark_read(db, ctx.organisation.id, ctx.auth.user.id, notification_id)
    await db.commit()
    return notification_out(n)


@router.post("/notifications/read-all", response_model=MarkedReadOut)
async def mark_all_read(ctx: Member, db: DbDep) -> MarkedReadOut:
    marked = await service.mark_all_read(db, ctx.organisation.id, ctx.auth.user.id)
    await db.commit()
    return MarkedReadOut(marked=marked)
