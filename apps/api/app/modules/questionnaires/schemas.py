from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.modules.questionnaires.engine import QuestionnaireSpec


class OptionOut(BaseModel):
    value: str
    label: str


class QuestionOut(BaseModel):
    key: str
    type: str
    label: str
    help_text: str | None
    required: bool
    options: list[OptionOut]
    validation: dict[str, Any]
    visible_when: dict[str, Any] | None = Field(
        description="Condition AST. The browser may evaluate it for instant branching; the "
        "API re-evaluates on every save and is authoritative."
    )


class SectionOut(BaseModel):
    title: str
    questions: list[QuestionOut]


class QuestionnaireOut(BaseModel):
    key: str
    vertical: str
    version: int
    title: str
    description: str | None
    sections: list[SectionOut]


class QuestionnaireSummary(BaseModel):
    key: str
    vertical: str
    version: int
    title: str
    description: str | None
    published_at: datetime | None


class SubmissionStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    questionnaire_key: str | None = Field(
        default=None, description="Defaults to the only questionnaire for the project's vertical."
    )


class AnswersUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answers: dict[str, Any] = Field(
        max_length=200, description="Question key to answer. null clears an answer."
    )


class Progress(BaseModel):
    answered: int
    visible: int
    required_remaining: int


class SubmissionOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    status: str
    submitted_at: datetime | None
    updated_at: datetime
    questionnaire: QuestionnaireOut
    answers: dict[str, Any]
    visible: list[str]
    missing_required: list[str]
    pruned: list[str] = Field(
        description="Answers removed by this save because their question is now hidden."
    )
    progress: Progress


class PrefillSuggestion(BaseModel):
    key: str
    label: str
    value: Any = Field(description="A valid answer for the question, ready to save.")
    source: str = Field(description="Where the value comes from.")
    source_url: str | None
    is_mock: bool = Field(description="Made-up data from the development mock provider.")


class PrefillOut(BaseModel):
    provider: str = Field(description="Property facts provider in use ('none' means no lookups).")
    suggestions: list[PrefillSuggestion]


def questionnaire_out(spec: QuestionnaireSpec) -> QuestionnaireOut:
    return QuestionnaireOut(
        key=spec.questionnaire_key,
        vertical=spec.vertical,
        version=spec.version,
        title=spec.title,
        description=spec.description,
        sections=[
            SectionOut(
                title=title,
                questions=[
                    QuestionOut(
                        key=q.key,
                        type=q.type,
                        label=q.label,
                        help_text=q.help_text,
                        required=q.required,
                        options=[OptionOut(value=o.value, label=o.label) for o in q.options],
                        validation=q.validation.model_dump(mode="json", exclude_none=True),
                        visible_when=(
                            q.visible_when.model_dump(mode="json", by_alias=True, exclude_none=True)
                            if q.visible_when is not None
                            else None
                        ),
                    )
                    for q in questions
                ],
            )
            for title, questions in spec.sections()
        ],
    )
