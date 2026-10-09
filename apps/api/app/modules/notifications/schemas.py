from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.modules.notifications.models import EmailStatus, NotificationKind


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
