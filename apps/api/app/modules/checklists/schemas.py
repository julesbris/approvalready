from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.checklists.models import ChecklistOrigin, ItemStatus
from app.modules.projects.models import Vertical


class ChecklistSourceOut(BaseModel):
    title: str
    organisation: str
    url: str


class ChecklistItemDefOut(BaseModel):
    key: str
    title: str
    detail: str | None
    required: bool


class ChecklistDefinitionOut(BaseModel):
    key: str
    vertical: Vertical
    title: str
    description: str
    sources: list[ChecklistSourceOut]
    items: list[ChecklistItemDefOut]


class ChecklistItemOut(BaseModel):
    id: uuid.UUID
    checklist_id: uuid.UUID
    key: str
    title: str
    detail: str | None
    required: bool
    status: ItemStatus
    note: str | None
    completed_at: datetime | None
    completed_by: uuid.UUID | None


class ChecklistOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    key: str
    title: str
    description: str
    sources: list[ChecklistSourceOut]
    origin: ChecklistOrigin = Field(
        description="RULE: added by an assessment finding (cannot be removed). USER: added by "
        "the customer."
    )
    finding_id: uuid.UUID | None
    items: list[ChecklistItemOut]
    done: int = Field(description="Items done or marked not applicable.")
    total: int
    created_at: datetime


class ChecklistAddIn(BaseModel):
    key: str = Field(max_length=80)


class ChecklistItemUpdateIn(BaseModel):
    status: ItemStatus | None = None
    note: str | None = Field(default=None, max_length=1000)
