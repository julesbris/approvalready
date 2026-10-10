from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.ai.models import AITask, JobStatus, PromptStatus
from app.modules.ai.outputs import AssessmentExplanationV1, GrantDraftV1


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExplanationIn(_In):
    regenerate: bool = Field(
        default=False, description="Write a new draft even if one exists for the same findings."
    )


class GrantDraftIn(_In):
    program_id: uuid.UUID
    regenerate: bool = False


class AIStatusOut(BaseModel):
    enabled: bool
    provider: str
    model: str | None
    mock: bool = Field(description="Drafts are canned test text, not written by a model.")


class AIJobOut(BaseModel):
    id: uuid.UUID
    task: AITask
    status: JobStatus
    assessment_id: uuid.UUID
    subject_id: uuid.UUID | None = Field(description="Grant drafts: the program.")
    prompt_version: int
    output_schema: str
    explanation: AssessmentExplanationV1 | None = None
    grant_draft: GrantDraftV1 | None = None
    error: str | None
    validation_errors: list[str] = Field(
        default_factory=list, description="Why a REJECTED draft failed our checks."
    )
    created_at: datetime
    completed_at: datetime | None


class AIUsageRowOut(BaseModel):
    provider: str
    model: str
    task: str
    status: str
    calls: int
    request_tokens: int
    response_tokens: int
    cost_micros: int = Field(description="Millionths of a US dollar, from configured prices.")


class AIUsageOut(BaseModel):
    provider: str
    model: str | None
    enabled: bool
    since: datetime
    rows: list[AIUsageRowOut]


class PromptVersionOut(BaseModel):
    id: uuid.UUID
    task: AITask
    version: int
    status: PromptStatus
    output_schema_name: str
    output_schema_version: int
    system_prompt: str
    user_template: str
    published_at: datetime
