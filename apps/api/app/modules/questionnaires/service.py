"""Questionnaire definitions (sync, compile) and submissions (start, answer, submit).

Definitions ship as JSON files in ``definitions/`` and are reviewed like code.
``sync_definitions`` (run by ``python -m app.cli questionnaires sync`` on deploy) stores a
new immutable version whenever a file's content changes and publishes it; earlier versions
are retired but keep serving the submissions pinned to them.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, not_found
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.projects.models import Project
from app.modules.questionnaires.definition import QuestionnaireDef
from app.modules.questionnaires.engine import (
    AnswerInvalid,
    AnswerState,
    QuestionnaireSpec,
    compile_question,
    evaluate_answers,
    normalise_answer,
)
from app.modules.questionnaires.models import (
    Question,
    Questionnaire,
    QuestionnaireSubmission,
    QuestionnaireVersion,
    QuestionOption,
    QuestionResponse,
    QuestionVersion,
    SubmissionStatus,
    VersionStatus,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


# --- Definitions -----------------------------------------------------------------------


@dataclass(frozen=True)
class SyncResult:
    key: str
    version: int
    changed: bool


async def _create_version(
    db: AsyncSession, questionnaire: Questionnaire, definition: QuestionnaireDef, number: int
) -> QuestionnaireVersion:
    version = QuestionnaireVersion(
        questionnaire_id=questionnaire.id,
        version=number,
        status=VersionStatus.DRAFT,
        title=definition.title,
        description=definition.description,
        content_hash=definition.content_hash(),
    )
    db.add(version)
    await db.flush()
    keys = [q.key for q in definition.questions()]
    existing = {
        q.key: q
        for q in (await db.execute(select(Question).where(Question.key.in_(keys)))).scalars()
    }
    ordinal = 0
    for section in definition.sections:
        for qdef in section.questions:
            question = existing.get(qdef.key)
            if question is None:
                question = Question(key=qdef.key)
                db.add(question)
                await db.flush()
            ordinal += 1
            qv = QuestionVersion(
                questionnaire_version_id=version.id,
                question_id=question.id,
                ordinal=ordinal,
                section=section.title,
                type=qdef.type,
                label=qdef.label,
                help_text=qdef.help_text,
                required=qdef.required,
                validation=qdef.validation.model_dump(mode="json", exclude_none=True),
                visible_when=qdef.visible_when,
            )
            db.add(qv)
            await db.flush()
            for i, option in enumerate(qdef.options, start=1):
                db.add(
                    QuestionOption(
                        question_version_id=qv.id, value=option.value, label=option.label, ordinal=i
                    )
                )
    await db.flush()
    return version


async def sync_definition(db: AsyncSession, definition: QuestionnaireDef) -> SyncResult:
    """Store and publish ``definition`` if it differs from the current version."""
    questionnaire = (
        await db.execute(select(Questionnaire).where(Questionnaire.key == definition.key))
    ).scalar_one_or_none()
    if questionnaire is None:
        questionnaire = Questionnaire(
            key=definition.key, vertical=definition.vertical, title=definition.title
        )
        db.add(questionnaire)
        await db.flush()
    elif questionnaire.vertical != definition.vertical:
        raise ValueError(f"{definition.key}: a questionnaire cannot change vertical")
    questionnaire.title = definition.title

    content_hash = definition.content_hash()
    current = (
        await db.execute(
            select(QuestionnaireVersion).where(
                QuestionnaireVersion.questionnaire_id == questionnaire.id,
                QuestionnaireVersion.status == VersionStatus.PUBLISHED,
            )
        )
    ).scalar_one_or_none()
    if current is not None and current.content_hash == content_hash:
        return SyncResult(definition.key, current.version, changed=False)

    latest = (
        await db.execute(
            select(func.max(QuestionnaireVersion.version)).where(
                QuestionnaireVersion.questionnaire_id == questionnaire.id
            )
        )
    ).scalar_one()
    version = await _create_version(db, questionnaire, definition, (latest or 0) + 1)
    if current is not None:
        current.status = VersionStatus.RETIRED
        await db.flush()
    version.status = VersionStatus.PUBLISHED
    version.published_at = utcnow()
    await db.flush()
    return SyncResult(definition.key, version.version, changed=True)


async def sync_definitions(
    db: AsyncSession, definitions: Sequence[QuestionnaireDef]
) -> list[SyncResult]:
    return [await sync_definition(db, d) for d in definitions]


_SPEC_CACHE: dict[uuid.UUID, QuestionnaireSpec] = {}


async def compiled(db: AsyncSession, version_id: uuid.UUID) -> QuestionnaireSpec:
    """The compiled questionnaire for a version. Non-draft versions are immutable, so they
    are cached for the life of the process."""
    cached = _SPEC_CACHE.get(version_id)
    if cached is not None:
        return cached
    row = (
        await db.execute(
            select(QuestionnaireVersion, Questionnaire)
            .join(Questionnaire, Questionnaire.id == QuestionnaireVersion.questionnaire_id)
            .where(QuestionnaireVersion.id == version_id)
        )
    ).one()
    version, questionnaire = row
    rows = (
        await db.execute(
            select(QuestionVersion, Question.key)
            .join(Question, Question.id == QuestionVersion.question_id)
            .where(QuestionVersion.questionnaire_version_id == version_id)
            .order_by(QuestionVersion.ordinal)
        )
    ).all()
    options: dict[uuid.UUID, list[tuple[str, str]]] = {}
    for option in (
        await db.execute(
            select(QuestionOption)
            .where(QuestionOption.question_version_id.in_([qv.id for qv, _ in rows]))
            .order_by(QuestionOption.question_version_id, QuestionOption.ordinal)
        )
    ).scalars():
        options.setdefault(option.question_version_id, []).append((option.value, option.label))
    spec = QuestionnaireSpec(
        version_id=version.id,
        questionnaire_key=questionnaire.key,
        vertical=questionnaire.vertical,
        version=version.version,
        title=version.title,
        description=version.description,
        questions=tuple(
            compile_question(
                id=qv.id,
                key=key,
                type=qv.type,
                section=qv.section,
                label=qv.label,
                help_text=qv.help_text,
                required=qv.required,
                options=options.get(qv.id, []),
                validation=qv.validation,
                visible_when=qv.visible_when,
            )
            for qv, key in rows
        ),
    )
    if version.status != VersionStatus.DRAFT:
        _SPEC_CACHE[version_id] = spec
    return spec


async def published_versions(
    db: AsyncSession, vertical: str | None = None
) -> list[tuple[Questionnaire, QuestionnaireVersion]]:
    stmt = (
        select(Questionnaire, QuestionnaireVersion)
        .join(QuestionnaireVersion, QuestionnaireVersion.questionnaire_id == Questionnaire.id)
        .where(QuestionnaireVersion.status == VersionStatus.PUBLISHED)
        .order_by(Questionnaire.key)
    )
    if vertical is not None:
        stmt = stmt.where(Questionnaire.vertical == vertical)
    return [(q, v) for q, v in (await db.execute(stmt)).all()]


async def published_version(db: AsyncSession, key: str) -> QuestionnaireVersion | None:
    return (
        await db.execute(
            select(QuestionnaireVersion)
            .join(Questionnaire, Questionnaire.id == QuestionnaireVersion.questionnaire_id)
            .where(Questionnaire.key == key, QuestionnaireVersion.status == VersionStatus.PUBLISHED)
        )
    ).scalar_one_or_none()


# --- Submissions -----------------------------------------------------------------------


@dataclass(frozen=True)
class SubmissionView:
    submission: QuestionnaireSubmission
    spec: QuestionnaireSpec
    answers: dict[str, Any]
    state: AnswerState
    pruned: tuple[str, ...] = ()


async def _answers(
    db: AsyncSession, submission: QuestionnaireSubmission, spec: QuestionnaireSpec
) -> dict[str, QuestionResponse]:
    by_id = {q.id: q.key for q in spec.questions}
    rows = (
        await db.execute(
            select(QuestionResponse).where(QuestionResponse.submission_id == submission.id)
        )
    ).scalars()
    return {by_id[r.question_version_id]: r for r in rows if r.question_version_id in by_id}


async def view(db: AsyncSession, submission: QuestionnaireSubmission) -> SubmissionView:
    spec = await compiled(db, submission.questionnaire_version_id)
    answers = {k: r.value for k, r in (await _answers(db, submission, spec)).items()}
    return SubmissionView(submission, spec, answers, evaluate_answers(spec, answers))


async def list_submissions(db: AsyncSession, project: Project) -> list[QuestionnaireSubmission]:
    return list(
        (
            await db.execute(
                select(QuestionnaireSubmission)
                .where(QuestionnaireSubmission.project_id == project.id)
                .order_by(QuestionnaireSubmission.created_at.desc())
            )
        ).scalars()
    )


async def get_submission(
    db: AsyncSession, organisation_id: uuid.UUID, submission_id: uuid.UUID
) -> QuestionnaireSubmission:
    submission = (
        await db.execute(
            select(QuestionnaireSubmission)
            .join(Project, Project.id == QuestionnaireSubmission.project_id)
            .where(
                QuestionnaireSubmission.id == submission_id,
                QuestionnaireSubmission.organisation_id == organisation_id,
                Project.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if submission is None:
        raise not_found("Questionnaire")
    return submission


async def start_submission(
    db: AsyncSession,
    project: Project,
    *,
    questionnaire_key: str | None,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> QuestionnaireSubmission:
    """Start (or return the open) submission of the current published version."""
    if questionnaire_key is None:
        candidates = await published_versions(db, project.vertical)
        if len(candidates) != 1:
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "questionnaire_required",
                "Choose which questionnaire to start.",
            )
        questionnaire, version = candidates[0]
    else:
        row = (
            await db.execute(
                select(Questionnaire, QuestionnaireVersion)
                .join(
                    QuestionnaireVersion,
                    QuestionnaireVersion.questionnaire_id == Questionnaire.id,
                )
                .where(
                    Questionnaire.key == questionnaire_key,
                    QuestionnaireVersion.status == VersionStatus.PUBLISHED,
                )
            )
        ).one_or_none()
        if row is None:
            raise not_found("Questionnaire")
        questionnaire, version = row
        if questionnaire.vertical != project.vertical:
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "wrong_vertical",
                "That questionnaire is for a different kind of project.",
            )
    existing = (
        await db.execute(
            select(QuestionnaireSubmission)
            .join(
                QuestionnaireVersion,
                QuestionnaireVersion.id == QuestionnaireSubmission.questionnaire_version_id,
            )
            .where(
                QuestionnaireSubmission.project_id == project.id,
                QuestionnaireVersion.questionnaire_id == questionnaire.id,
                QuestionnaireSubmission.status == SubmissionStatus.IN_PROGRESS,
            )
            .order_by(QuestionnaireSubmission.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    submission = QuestionnaireSubmission(
        organisation_id=project.organisation_id,
        project_id=project.id,
        questionnaire_version_id=version.id,
        created_by=actor_id,
    )
    db.add(submission)
    await db.flush()
    await audit.record(
        db,
        "questionnaire.started",
        actor_user_id=actor_id,
        organisation_id=project.organisation_id,
        target_type="questionnaire_submission",
        target_id=submission.id,
        meta=meta,
        details={
            "project_id": str(project.id),
            "questionnaire": questionnaire.key,
            "version": version.version,
        },
    )
    return submission


def _require_open(submission: QuestionnaireSubmission) -> None:
    if submission.status != SubmissionStatus.IN_PROGRESS:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "submission_closed",
            "These answers have been submitted. Reopen them to make changes.",
        )


async def save_answers(
    db: AsyncSession,
    submission: QuestionnaireSubmission,
    changes: Mapping[str, Any],
    *,
    actor_id: uuid.UUID,
) -> SubmissionView:
    """Validate and store a partial set of answers (``None`` clears an answer).

    All-or-nothing: if any answer is invalid nothing is saved and every problem is reported.
    Answers to questions that end up hidden are removed.
    """
    _require_open(submission)
    spec = await compiled(db, submission.questionnaire_version_id)
    rows = await _answers(db, submission, spec)
    answers: dict[str, Any] = {k: r.value for k, r in rows.items()}
    errors: dict[str, str] = {}
    for key, raw in changes.items():
        question = spec.by_key.get(key)
        if question is None:
            errors[key] = "This question is not part of the questionnaire."
            continue
        try:
            value = normalise_answer(question, raw)
        except AnswerInvalid as exc:
            errors[key] = str(exc)
            continue
        if value is None:
            answers.pop(key, None)
        else:
            answers[key] = value
    if errors:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_answers",
            "Some answers need attention.",
            fields=errors,
        )

    state = evaluate_answers(spec, answers)
    for key in state.hidden_answered:
        answers.pop(key)
    for key, row in rows.items():
        if key not in answers:
            await db.delete(row)
        elif row.value != answers[key]:
            row.value = answers[key]
            row.answered_by = actor_id
    for key, value in answers.items():
        if key not in rows:
            db.add(
                QuestionResponse(
                    organisation_id=submission.organisation_id,
                    submission_id=submission.id,
                    question_version_id=spec.by_key[key].id,
                    value=value,
                    answered_by=actor_id,
                )
            )
    submission.updated_at = utcnow()
    await db.flush()
    return SubmissionView(submission, spec, answers, state, pruned=state.hidden_answered)


async def submit(
    db: AsyncSession,
    submission: QuestionnaireSubmission,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> SubmissionView:
    _require_open(submission)
    current = await view(db, submission)
    if current.state.missing_required:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "answers_incomplete",
            "Answer the remaining required questions before submitting.",
            fields={k: "This question needs an answer." for k in current.state.missing_required},
        )
    submission.status = SubmissionStatus.SUBMITTED
    submission.submitted_at = utcnow()
    submission.submitted_by = actor_id
    await db.flush()
    await audit.record(
        db,
        "questionnaire.submitted",
        actor_user_id=actor_id,
        organisation_id=submission.organisation_id,
        target_type="questionnaire_submission",
        target_id=submission.id,
        meta=meta,
        details={"answered": len(current.state.answered)},
    )
    return current


async def reopen(
    db: AsyncSession,
    submission: QuestionnaireSubmission,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> SubmissionView:
    if submission.status != SubmissionStatus.SUBMITTED:
        raise ApiError(status.HTTP_409_CONFLICT, "not_submitted", "These answers are still open.")
    submission.status = SubmissionStatus.IN_PROGRESS
    submission.submitted_at = None
    submission.submitted_by = None
    await db.flush()
    await audit.record(
        db,
        "questionnaire.reopened",
        actor_user_id=actor_id,
        organisation_id=submission.organisation_id,
        target_type="questionnaire_submission",
        target_id=submission.id,
        meta=meta,
    )
    return await view(db, submission)
