from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.notifications.models import (
    EmailStatus,
    NotificationCategory,
    NotificationChannel,
    NotificationKind,
)


class NotificationOut(BaseModel):
    id: uuid.UUID
    kind: NotificationKind
    title: str
    body: str | None
    link_path: str | None
    project_id: uuid.UUID | None
    email_status: EmailStatus
    read_at: datetime | None
    created_at: datetime


class NotificationListOut(BaseModel):
    unread: int
    items: list[NotificationOut]


class MarkedReadOut(BaseModel):
    marked: int


class PreferenceOut(BaseModel):
    category: NotificationCategory
    channel: NotificationChannel


class PreferencesOut(BaseModel):
    items: list[PreferenceOut]


class PreferencesIn(BaseModel):
    """Only the categories listed change."""

    items: list[PreferenceOut] = Field(min_length=1, max_length=len(NotificationCategory))


class UnsubscribeOut(BaseModel):
    """What an unsubscribe link is for, and the person's channel for it now."""

    category: NotificationCategory
    channel: NotificationChannel


class UnsubscribedOut(BaseModel):
    scope: Literal["category", "all"]
    items: list[PreferenceOut]
