"""``/v1/organisations/{organisation_id}/notifications``: the signed-in member's own
notifications in that organisation. ``/v1/auth/notification-preferences`` and
``/v1/auth/unsubscribe``: what a person hears about (Milestone 21)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.api.deps import AuthDep, DbDep, OrgContext, SettingsDep, require_org_permission
from app.core.config import Settings
from app.core.errors import ApiError
from app.modules.identity.models import AppUser
from app.modules.notifications import preferences, service
from app.modules.notifications.models import Notification, NotificationCategory
from app.modules.notifications.schemas import (
    MarkedReadOut,
    NotificationListOut,
    NotificationOut,
    PreferenceOut,
    PreferencesIn,
    PreferencesOut,
    UnsubscribedOut,
    UnsubscribeOut,
)
from app.modules.tenancy.rbac import Perm

router = APIRouter(prefix="/v1/organisations/{organisation_id}", tags=["notifications"])
preferences_router = APIRouter(prefix="/v1/auth", tags=["notifications"])

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


# --- Preferences and unsubscribe (Milestone 21) ------------------------------------------


async def _preferences_out(db: DbDep, user_id: uuid.UUID) -> PreferencesOut:
    chosen = await preferences.choices(db, user_id)
    return PreferencesOut(items=[PreferenceOut(category=c, channel=ch) for c, ch in chosen.items()])


@preferences_router.get("/notification-preferences", response_model=PreferencesOut)
async def get_preferences(auth: AuthDep, db: DbDep) -> PreferencesOut:
    """Every category with the signed-in person's choice (``ALL`` until they choose)."""
    return await _preferences_out(db, auth.user.id)


@preferences_router.put("/notification-preferences", response_model=PreferencesOut)
async def put_preferences(body: PreferencesIn, auth: AuthDep, db: DbDep) -> PreferencesOut:
    for item in body.items:
        await preferences.choose(db, auth.user.id, item.category, item.channel)
    await db.commit()
    return await _preferences_out(db, auth.user.id)


async def _token_user(
    db: DbDep, settings: Settings, token: str
) -> tuple[AppUser, NotificationCategory]:
    read = preferences.read_unsubscribe_token(settings.secret_key.get_secret_value(), token)
    user = await db.get(AppUser, read[0]) if read else None
    if read is None or user is None or user.deleted_at is not None:
        raise ApiError(
            400,
            "invalid_link",
            "This unsubscribe link doesn't work. Sign in to choose which emails you get.",
        )
    return user, read[1]


Token = Annotated[str, Query(min_length=1, max_length=200)]


@preferences_router.get("/unsubscribe", response_model=UnsubscribeOut)
async def unsubscribe_info(token: Token, db: DbDep, settings: SettingsDep) -> UnsubscribeOut:
    """What an emailed unsubscribe link is for. Changes nothing (link scanners open it)."""
    user, category = await _token_user(db, settings, token)
    return UnsubscribeOut(
        category=category, channel=await preferences.channel_for_category(db, user.id, category)
    )


@preferences_router.post("/unsubscribe", response_model=UnsubscribedOut)
async def unsubscribe(
    token: Token,
    db: DbDep,
    settings: SettingsDep,
    scope: Annotated[Literal["category", "all"], Query()] = "category",
) -> UnsubscribedOut:
    """Stop emails for the link's category, or every optional email with ``scope=all``.
    Needs no sign-in: the link is the proof. Also the target of one-click unsubscribe
    (RFC 8058), whose form body is ignored."""
    user, category = await _token_user(db, settings, token)
    categories = list(NotificationCategory) if scope == "all" else [category]
    await preferences.stop_emails(db, user.id, categories)
    await db.commit()
    return UnsubscribedOut(scope=scope, items=(await _preferences_out(db, user.id)).items)
