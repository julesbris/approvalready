from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.modules.assessments.schemas import AssessmentSummary
from app.modules.projects.models import (
    ProjectStatus,
    Recurrence,
    ReminderChannel,
    TaskStatus,
    Vertical,
)

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectCreate(_In):
    vertical: Vertical
    title: Title
    description: Notes | None = None
    property_id: uuid.UUID | None = None
    vessel_id: uuid.UUID | None = None
    business_profile_id: uuid.UUID | None = None


class ProjectUpdate(_In):
    title: Title | None = None
    description: Notes | None = None
    property_id: uuid.UUID | None = None
    vessel_id: uuid.UUID | None = None
    business_profile_id: uuid.UUID | None = None


class ProjectStatusChange(_In):
    status: Literal["IN_PROGRESS", "COMPLETED", "ARCHIVED"]


class SubmissionSummary(BaseModel):
    id: uuid.UUID
    questionnaire_key: str
    questionnaire_title: str
    version: int
    status: str
    submitted_at: datetime | None
    updated_at: datetime


class ProjectOut(BaseModel):
    id: uuid.UUID
    organisation_id: uuid.UUID
    reference_code: str
    vertical: Vertical
    title: str
    description: str | None
    status: ProjectStatus
    allowed_status_changes: list[str]
    property_id: uuid.UUID | None
    vessel_id: uuid.UUID | None
    business_profile_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ProjectDetailOut(ProjectOut):
    submissions: list[SubmissionSummary]
    open_tasks: int
    latest_assessment: AssessmentSummary | None


class StatusEventOut(BaseModel):
    from_status: str | None
    to_status: str
    actor_id: uuid.UUID | None
    occurred_at: datetime


class TaskCreate(_In):
    title: Title
    notes: Notes | None = None
    due_on: date | None = None
    assignee_user_id: uuid.UUID | None = None


class TaskUpdate(_In):
    title: Title | None = None
    notes: Notes | None = None
    due_on: date | None = None
    assignee_user_id: uuid.UUID | None = None
    status: TaskStatus | None = None


class TaskOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    notes: str | None
    status: TaskStatus
    source: str
    due_on: date | None
    assignee_user_id: uuid.UUID | None
    completed_at: datetime | None
    created_at: datetime


class ReminderCreate(_In):
    title: Title
    fires_at: datetime
    channel: ReminderChannel = ReminderChannel.EMAIL
    recurrence: Recurrence | None = None
    task_id: uuid.UUID | None = None
    recipient_user_id: uuid.UUID | None = Field(
        default=None, description="Defaults to the person creating the reminder."
    )


class ReminderOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    task_id: uuid.UUID | None
    recipient_user_id: uuid.UUID
    title: str
    fires_at: datetime
    channel: str
    status: str
    recurrence: str | None
    created_at: datetime
