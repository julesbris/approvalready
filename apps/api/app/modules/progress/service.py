"""What's left on a project: the next things the customer needs to do or send, in order.

The project page shows it as a checklist, and the keep-going nudges (``nudges.py``) name the
same items, so an email always matches what the person sees when they click through. Every
item links straight to the page where it gets done.

Read with the project's organisation bound (requests and jobs alike), so row-level security
applies. Item details come from our own reviewed content (question labels, evidence names)
and the customer's own tasks, never from their answers or files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assessments.models import Assessment, EvidenceRequirement
from app.modules.checklists.models import ChecklistItem, ItemStatus, ProjectChecklist
from app.modules.documents.models import Evidence, EvidenceStatus
from app.modules.projects.models import Project, ProjectStatus, Task, TaskStatus
from app.modules.questionnaires import service as questionnaires
from app.modules.questionnaires.models import QuestionnaireSubmission, SubmissionStatus

# How many specifics an item lists (the count says how many there are in all).
DETAIL_LIMIT = 5

# Nothing is left to nudge about once a project is finished or put away.
CLOSED_STATUSES = (ProjectStatus.COMPLETED, ProjectStatus.ARCHIVED)


class ProgressStep(StrEnum):
    START = "START"  # no answers yet
    QUESTIONS = "QUESTIONS"  # required questions still unanswered
    SUBMIT = "SUBMIT"  # every required question answered, not submitted
    RESULTS = "RESULTS"  # submitted, not assessed (or assessed on older answers)
    DOCUMENTS = "DOCUMENTS"  # documents the assessment asks for, not yet provided
    TASKS = "TASKS"  # open tasks
    CHECKLIST = "CHECKLIST"  # required checklist items not ticked off


@dataclass(frozen=True)
class Item:
    step: ProgressStep
    title: str
    count: int
    link_path: str
    details: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WhatsLeft:
    items: list[Item]

    @property
    def done(self) -> bool:
        return not self.items


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


async def _latest_submission(db: AsyncSession, project: Project) -> QuestionnaireSubmission | None:
    # The questionnaire page opens the most recently updated answers; so does this.
    return (
        await db.execute(
            select(QuestionnaireSubmission)
            .where(
                QuestionnaireSubmission.project_id == project.id,
                QuestionnaireSubmission.organisation_id == project.organisation_id,
            )
            .order_by(QuestionnaireSubmission.updated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _answers_items(
    db: AsyncSession, project: Project, submission: QuestionnaireSubmission | None
) -> list[Item]:
    questions = f"/projects/{project.id}/questionnaire"
    if submission is None:
        return [Item(ProgressStep.START, "Answer the questions about your project", 1, questions)]
    if submission.status != SubmissionStatus.IN_PROGRESS:
        return []
    view = await questionnaires.view(db, submission)
    missing = view.state.missing_required
    if not missing:
        return [Item(ProgressStep.SUBMIT, "Check and submit your answers", 1, questions)]
    labels = [view.spec.by_key[k].label for k in missing[:DETAIL_LIMIT]]
    title = f"Answer {_plural(len(missing), 'more question', 'more questions')}"
    return [Item(ProgressStep.QUESTIONS, title, len(missing), questions, labels)]


async def _assessment_items(
    db: AsyncSession, project: Project, submission: QuestionnaireSubmission
) -> list[Item]:
    latest = (
        await db.execute(
            select(Assessment)
            .where(
                Assessment.project_id == project.id,
                Assessment.organisation_id == project.organisation_id,
            )
            .order_by(Assessment.created_at.desc(), Assessment.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest is None or latest.submission_id != submission.id:
        return [
            Item(
                ProgressStep.RESULTS,
                "Run the assessment to see what approvals you need",
                1,
                f"/projects/{project.id}#assessment-title",
            )
        ]
    offered = exists().where(
        Evidence.evidence_requirement_id == EvidenceRequirement.id,
        Evidence.status != EvidenceStatus.REJECTED,
    )
    missing = list(
        (
            await db.execute(
                select(EvidenceRequirement.title)
                .where(EvidenceRequirement.assessment_id == latest.id, ~offered)
                .order_by(EvidenceRequirement.ordinal)
            )
        ).scalars()
    )
    if not missing:
        return []
    return [
        Item(
            ProgressStep.DOCUMENTS,
            f"Send {_plural(len(missing), 'document', 'documents')}",
            len(missing),
            f"/projects/{project.id}/assessments/{latest.id}#evidence-title",
            missing[:DETAIL_LIMIT],
        )
    ]


async def _task_items(db: AsyncSession, project: Project) -> list[Item]:
    tasks = list(
        (
            await db.execute(
                select(Task)
                .where(
                    Task.project_id == project.id,
                    Task.organisation_id == project.organisation_id,
                    Task.deleted_at.is_(None),
                    Task.status == TaskStatus.OPEN,
                )
                .order_by(Task.due_on.asc().nulls_last(), Task.created_at)
            )
        ).scalars()
    )
    if not tasks:
        return []
    details = [
        f"{t.title} (due {t.due_on.strftime('%-d %b %Y')})" if t.due_on else t.title
        for t in tasks[:DETAIL_LIMIT]
    ]
    return [
        Item(
            ProgressStep.TASKS,
            f"Finish {_plural(len(tasks), 'task', 'tasks')}",
            len(tasks),
            f"/projects/{project.id}#tasks-title",
            details,
        )
    ]


async def _checklist_items(db: AsyncSession, project: Project) -> list[Item]:
    titles = list(
        (
            await db.execute(
                select(ChecklistItem.title)
                .join(ProjectChecklist, ProjectChecklist.id == ChecklistItem.checklist_id)
                .where(
                    ProjectChecklist.project_id == project.id,
                    ProjectChecklist.organisation_id == project.organisation_id,
                    ChecklistItem.required.is_(True),
                    ChecklistItem.status == ItemStatus.OPEN,
                )
                .order_by(ProjectChecklist.created_at, ChecklistItem.ordinal)
            )
        ).scalars()
    )
    if not titles:
        return []
    return [
        Item(
            ProgressStep.CHECKLIST,
            f"Tick off {_plural(len(titles), 'checklist item', 'checklist items')}",
            len(titles),
            f"/projects/{project.id}#checklists-title",
            titles[:DETAIL_LIMIT],
        )
    ]


async def whats_left(db: AsyncSession, project: Project) -> WhatsLeft:
    """The project's remaining steps, first thing to do first. Empty once it is completed
    or archived, or when nothing is left."""
    if project.status in CLOSED_STATUSES or project.deleted_at is not None:
        return WhatsLeft([])
    submission = await _latest_submission(db, project)
    items = await _answers_items(db, project, submission)
    if submission is not None and submission.status == SubmissionStatus.SUBMITTED:
        items += await _assessment_items(db, project, submission)
    items += await _task_items(db, project)
    items += await _checklist_items(db, project)
    return WhatsLeft(items)
