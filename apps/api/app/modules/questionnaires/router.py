"""``/v1/questionnaires``: published questionnaire definitions (reference data)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import AuthDep, DbDep
from app.core.errors import not_found
from app.modules.projects.models import Vertical
from app.modules.questionnaires import service
from app.modules.questionnaires.schemas import (
    QuestionnaireOut,
    QuestionnaireSummary,
    questionnaire_out,
)

router = APIRouter(prefix="/v1/questionnaires", tags=["questionnaires"])


@router.get("", response_model=list[QuestionnaireSummary])
async def list_questionnaires(
    _: AuthDep, db: DbDep, vertical: Vertical | None = None
) -> list[QuestionnaireSummary]:
    return [
        QuestionnaireSummary(
            key=q.key,
            vertical=q.vertical,
            version=v.version,
            title=v.title,
            description=v.description,
            published_at=v.published_at,
        )
        for q, v in await service.published_versions(db, vertical)
    ]


@router.get("/{key}", response_model=QuestionnaireOut)
async def get_questionnaire(key: str, _: AuthDep, db: DbDep) -> QuestionnaireOut:
    version = await service.published_version(db, key)
    if version is None:
        raise not_found("Questionnaire")
    return questionnaire_out(await service.compiled(db, version.id))
