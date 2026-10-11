from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.modules.progress.service import ProgressStep


class LeftItemOut(BaseModel):
    step: ProgressStep
    title: str
    count: int
    link_path: str
    details: list[str]


class WhatsLeftOut(BaseModel):
    done: bool
    items: list[LeftItemOut]


class QuietProjectOut(BaseModel):
    """A project that went quiet partway through (staff view): stage and counts only."""

    organisation_id: uuid.UUID
    organisation_name: str
    project_id: uuid.UUID
    reference_code: str
    vertical: str
    status: str
    owner_user_id: uuid.UUID | None
    owner_email: str | None
    owner_name: str | None
    last_activity_at: datetime
    stage: str
    open_tasks: int
    documents_missing: int
    checklist_open: int
    nudges_sent: int
    last_nudged_at: datetime | None
