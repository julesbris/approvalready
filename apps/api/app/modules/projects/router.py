"""``/v1/organisations/{organisation_id}/projects``: projects, status, tasks, reminders and
questionnaire submissions."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import select

from app.api.deps import DbDep, MetaDep, OrgContext, SettingsDep, require_org_permission
from app.modules.assessments import service as assessments
from app.modules.assessments.router import summary_out
from app.modules.projects import service
from app.modules.projects.models import Project, Reminder, Task, Vertical
from app.modules.projects.schemas import (
    ProjectCreate,
    ProjectDetailOut,
    ProjectOut,
    ProjectStatusChange,
    ProjectUpdate,
    ReminderCreate,
    ReminderOut,
    StatusEventOut,
    SubmissionSummary,
    TaskCreate,
    TaskOut,
    TaskUpdate,
)
from app.modules.property_facts import service as property_facts
from app.modules.property_facts.provider import get_provider
from app.modules.questionnaires import service as questionnaires
from app.modules.questionnaires.models import (
    Questionnaire,
    QuestionnaireSubmission,
    QuestionnaireVersion,
)
from app.modules.questionnaires.schemas import (
    AnswersUpdate,
    PrefillOut,
    PrefillSuggestion,
    Progress,
    SubmissionOut,
    SubmissionStart,
    questionnaire_out,
)
from app.modules.tenancy.rbac import Perm

router = APIRouter(prefix="/v1/organisations/{organisation_id}", tags=["projects"])

Read = Annotated[OrgContext, Depends(require_org_permission(Perm.PROJECT_READ))]
Write = Annotated[OrgContext, Depends(require_org_permission(Perm.PROJECT_WRITE))]


def _project_out(p: Project) -> ProjectOut:
    return ProjectOut(
        id=p.id,
        organisation_id=p.organisation_id,
        reference_code=p.reference_code,
        vertical=Vertical(p.vertical),
        title=p.title,
        description=p.description,
        status=p.status,
        allowed_status_changes=service.allowed_changes(p),
        property_id=p.property_id,
        vessel_id=p.vessel_id,
        business_profile_id=p.business_profile_id,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


async def _detail(db: DbDep, p: Project) -> ProjectDetailOut:
    rows = (
        await db.execute(
            select(QuestionnaireSubmission, QuestionnaireVersion, Questionnaire)
            .join(
                QuestionnaireVersion,
                QuestionnaireVersion.id == QuestionnaireSubmission.questionnaire_version_id,
            )
            .join(Questionnaire, Questionnaire.id == QuestionnaireVersion.questionnaire_id)
            .where(QuestionnaireSubmission.project_id == p.id)
            .order_by(QuestionnaireSubmission.created_at.desc())
        )
    ).all()
    assessed = await assessments.list_for_project(db, p)
    return ProjectDetailOut(
        **_project_out(p).model_dump(),
        submissions=[
            SubmissionSummary(
                id=s.id,
                questionnaire_key=q.key,
                questionnaire_title=v.title,
                version=v.version,
                status=s.status,
                submitted_at=s.submitted_at,
                updated_at=s.updated_at,
            )
            for s, v, q in rows
        ],
        open_tasks=await service.open_task_count(db, p),
        latest_assessment=summary_out(*assessed[0]) if assessed else None,
    )


def _task_out(t: Task) -> TaskOut:
    return TaskOut.model_validate(t, from_attributes=True)


def _reminder_out(r: Reminder) -> ReminderOut:
    return ReminderOut.model_validate(r, from_attributes=True)


def _submission_out(v: questionnaires.SubmissionView) -> SubmissionOut:
    s = v.submission
    required_remaining = len(v.state.missing_required)
    return SubmissionOut(
        id=s.id,
        project_id=s.project_id,
        status=s.status,
        submitted_at=s.submitted_at,
        updated_at=s.updated_at,
        questionnaire=questionnaire_out(v.spec),
        answers={k: v.answers[k] for k in v.state.answered},
        visible=list(v.state.visible),
        missing_required=list(v.state.missing_required),
        pruned=list(v.pruned),
        progress=Progress(
            answered=len(v.state.answered),
            visible=len(v.state.visible),
            required_remaining=required_remaining,
        ),
    )


# --- Projects --------------------------------------------------------------------------


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(
    ctx: Read,
    db: DbDep,
    vertical: Vertical | None = None,
    include_archived: Annotated[bool, Query()] = False,
) -> list[ProjectOut]:
    projects = await service.list_projects(
        db, ctx.organisation.id, vertical=vertical, include_archived=include_archived
    )
    return [_project_out(p) for p in projects]


@router.post("/projects", status_code=status.HTTP_201_CREATED, response_model=ProjectDetailOut)
async def create_project(
    body: ProjectCreate, ctx: Write, db: DbDep, meta: MetaDep
) -> ProjectDetailOut:
    project = await service.create_project(
        db, ctx.organisation.id, body.model_dump(), actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    return await _detail(db, project)


@router.get("/projects/{project_id}", response_model=ProjectDetailOut)
async def get_project(project_id: uuid.UUID, ctx: Read, db: DbDep) -> ProjectDetailOut:
    return await _detail(db, await service.get_project(db, ctx.organisation.id, project_id))


@router.patch("/projects/{project_id}", response_model=ProjectDetailOut)
async def update_project(
    project_id: uuid.UUID, body: ProjectUpdate, ctx: Write, db: DbDep, meta: MetaDep
) -> ProjectDetailOut:
    project = await service.get_project(db, ctx.organisation.id, project_id)
    await service.update_project(
        db, project, body.model_dump(exclude_unset=True), actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    return await _detail(db, project)


@router.post("/projects/{project_id}/status", response_model=ProjectDetailOut)
async def change_project_status(
    project_id: uuid.UUID, body: ProjectStatusChange, ctx: Write, db: DbDep, meta: MetaDep
) -> ProjectDetailOut:
    project = await service.get_project(db, ctx.organisation.id, project_id)
    await service.change_status(db, project, body.status, actor_id=ctx.auth.user.id, meta=meta)
    await db.commit()
    return await _detail(db, project)


@router.get("/projects/{project_id}/status-events", response_model=list[StatusEventOut])
async def list_status_events(project_id: uuid.UUID, ctx: Read, db: DbDep) -> list[StatusEventOut]:
    project = await service.get_project(db, ctx.organisation.id, project_id)
    return [
        StatusEventOut.model_validate(e, from_attributes=True)
        for e in await service.status_events(db, project)
    ]


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: uuid.UUID, ctx: Write, db: DbDep, meta: MetaDep) -> None:
    project = await service.get_project(db, ctx.organisation.id, project_id)
    await service.delete_project(db, project, actor_id=ctx.auth.user.id, meta=meta)
    await db.commit()


# --- Tasks -----------------------------------------------------------------------------


@router.get("/projects/{project_id}/tasks", response_model=list[TaskOut])
async def list_tasks(project_id: uuid.UUID, ctx: Read, db: DbDep) -> list[TaskOut]:
    project = await service.get_project(db, ctx.organisation.id, project_id)
    return [_task_out(t) for t in await service.list_tasks(db, project)]


@router.post(
    "/projects/{project_id}/tasks", status_code=status.HTTP_201_CREATED, response_model=TaskOut
)
async def create_task(project_id: uuid.UUID, body: TaskCreate, ctx: Write, db: DbDep) -> TaskOut:
    project = await service.get_project(db, ctx.organisation.id, project_id)
    task = await service.create_task(db, project, body.model_dump(), actor_id=ctx.auth.user.id)
    await db.commit()
    return _task_out(task)


@router.patch("/projects/{project_id}/tasks/{task_id}", response_model=TaskOut)
async def update_task(
    project_id: uuid.UUID, task_id: uuid.UUID, body: TaskUpdate, ctx: Write, db: DbDep
) -> TaskOut:
    project = await service.get_project(db, ctx.organisation.id, project_id)
    task = await service.get_task(db, project, task_id)
    await service.update_task(db, task, body.model_dump(exclude_unset=True))
    await db.commit()
    return _task_out(task)


@router.delete("/projects/{project_id}/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(project_id: uuid.UUID, task_id: uuid.UUID, ctx: Write, db: DbDep) -> None:
    project = await service.get_project(db, ctx.organisation.id, project_id)
    await service.delete_task(db, await service.get_task(db, project, task_id))
    await db.commit()


# --- Reminders -------------------------------------------------------------------------


@router.get("/projects/{project_id}/reminders", response_model=list[ReminderOut])
async def list_reminders(project_id: uuid.UUID, ctx: Read, db: DbDep) -> list[ReminderOut]:
    project = await service.get_project(db, ctx.organisation.id, project_id)
    return [_reminder_out(r) for r in await service.list_reminders(db, project)]


@router.post(
    "/projects/{project_id}/reminders",
    status_code=status.HTTP_201_CREATED,
    response_model=ReminderOut,
)
async def create_reminder(
    project_id: uuid.UUID, body: ReminderCreate, ctx: Write, db: DbDep
) -> ReminderOut:
    project = await service.get_project(db, ctx.organisation.id, project_id)
    reminder = await service.create_reminder(
        db, project, body.model_dump(), actor_id=ctx.auth.user.id
    )
    await db.commit()
    return _reminder_out(reminder)


@router.delete(
    "/projects/{project_id}/reminders/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def cancel_reminder(
    project_id: uuid.UUID, reminder_id: uuid.UUID, ctx: Write, db: DbDep
) -> None:
    project = await service.get_project(db, ctx.organisation.id, project_id)
    await service.cancel_reminder(db, project, reminder_id)
    await db.commit()


# --- Questionnaire submissions ---------------------------------------------------------


@router.post(
    "/projects/{project_id}/submissions",
    response_model=SubmissionOut,
    responses={201: {"model": SubmissionOut}},
)
async def start_submission(
    project_id: uuid.UUID, body: SubmissionStart, ctx: Write, db: DbDep, meta: MetaDep
) -> SubmissionOut:
    """Start the questionnaire for this project, or return the one already in progress."""
    project = await service.get_project(db, ctx.organisation.id, project_id)
    submission = await questionnaires.start_submission(
        db,
        project,
        questionnaire_key=body.questionnaire_key,
        actor_id=ctx.auth.user.id,
        meta=meta,
    )
    await service.mark_started(db, project, actor_id=ctx.auth.user.id, meta=meta)
    await db.commit()
    return _submission_out(await questionnaires.view(db, submission))


@router.get("/submissions/{submission_id}", response_model=SubmissionOut)
async def get_submission(submission_id: uuid.UUID, ctx: Read, db: DbDep) -> SubmissionOut:
    submission = await questionnaires.get_submission(db, ctx.organisation.id, submission_id)
    return _submission_out(await questionnaires.view(db, submission))


@router.get("/submissions/{submission_id}/prefill", response_model=PrefillOut)
async def prefill_suggestions(
    submission_id: uuid.UUID, ctx: Read, db: DbDep, settings: SettingsDep, request: Request
) -> PrefillOut:
    """Answers we can offer from the project's property and the property facts provider.
    Nothing is saved: the customer saves the ones they want through ``/answers``."""
    submission = await questionnaires.get_submission(db, ctx.organisation.id, submission_id)
    project = await service.get_project(db, ctx.organisation.id, submission.project_id)
    provider = get_provider(settings, getattr(request.app.state, "lookups", None))
    found = await property_facts.suggestions(
        db, project, await questionnaires.view(db, submission), provider
    )
    return PrefillOut(
        provider=provider.name,
        suggestions=[
            PrefillSuggestion(
                key=s.key,
                label=s.label,
                value=s.value,
                source=s.source,
                source_url=s.source_url,
                is_mock=s.is_mock,
            )
            for s in found
        ],
    )


@router.put("/submissions/{submission_id}/answers", response_model=SubmissionOut)
async def save_answers(
    submission_id: uuid.UUID, body: AnswersUpdate, ctx: Write, db: DbDep
) -> SubmissionOut:
    submission = await questionnaires.get_submission(db, ctx.organisation.id, submission_id)
    result = await questionnaires.save_answers(
        db, submission, body.answers, actor_id=ctx.auth.user.id
    )
    await db.commit()
    return _submission_out(result)


@router.post("/submissions/{submission_id}/submit", response_model=SubmissionOut)
async def submit_answers(
    submission_id: uuid.UUID, ctx: Write, db: DbDep, meta: MetaDep
) -> SubmissionOut:
    submission = await questionnaires.get_submission(db, ctx.organisation.id, submission_id)
    result = await questionnaires.submit(db, submission, actor_id=ctx.auth.user.id, meta=meta)
    await db.commit()
    return _submission_out(result)


@router.post("/submissions/{submission_id}/reopen", response_model=SubmissionOut)
async def reopen_answers(
    submission_id: uuid.UUID, ctx: Write, db: DbDep, meta: MetaDep
) -> SubmissionOut:
    submission = await questionnaires.get_submission(db, ctx.organisation.id, submission_id)
    result = await questionnaires.reopen(db, submission, actor_id=ctx.auth.user.id, meta=meta)
    await db.commit()
    return _submission_out(result)
