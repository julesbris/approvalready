"""Project plans: buying one, building it from the latest assessment's checklist, keeping it
up to date, and working through it.

* **Price.** The plan is the catalogue product ``plan.project`` (one-off, per project). When
  payments are on and staff have set a price, starting a plan opens a Stripe checkout and the
  plan waits (``PAYMENT_PENDING``) until the webhook confirms payment. When it isn't on sale
  (payments off, or no price set yet) the plan starts straight away, marked complimentary.
* **Timeline.** Each part of the checklist gets a two-week window, one after another from
  the start date, and its steps are spread across it; documents and tasks are due in the
  first two weeks. These are suggested dates: the customer changes any of them.
* **Kept in step.** Ticking a plan step that came from a project task or checklist item ticks
  that too, so the project page and the plan never disagree. Refreshing adds the steps a newer
  assessment found and ticks those already done elsewhere; it never removes or reopens one.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, not_found
from app.modules.assessments import service as assessments
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.billing import service as billing
from app.modules.billing.models import (
    Payment,
    PaymentPurpose,
    PaymentStatus,
    Price,
    PriceInterval,
    Product,
)
from app.modules.checklists.models import ChecklistItem, ItemStatus, ProjectChecklist
from app.modules.documents.models import ScanStatus, UploadedDocument
from app.modules.plans import checklist
from app.modules.plans.models import (
    PlanItemKind,
    PlanItemStatus,
    PlanStatus,
    ProjectPlan,
    ProjectPlanItem,
)
from app.modules.projects import service as projects
from app.modules.projects.models import (
    Project,
    ProjectStatus,
    ReminderChannel,
    Task,
    TaskStatus,
)

BRISBANE = ZoneInfo("Australia/Brisbane")
PRODUCT_KEY = "plan.project"
PAYMENT_SUBJECT = "project_plan"
WINDOW_DAYS = 14
# Where the customer's own steps and follow-ups go.
OWN_SECTION = {"key": "own", "kind": "OWN", "title": "Your own steps and follow-ups"}
DEFAULT_OWNER = "You"
EDITABLE_KINDS = (PlanItemKind.FOLLOW_UP, PlanItemKind.CUSTOM)


def utcnow() -> datetime:
    return datetime.now(UTC)


def today() -> date:
    return datetime.now(BRISBANE).date()


def _conflict(code: str, message: str) -> ApiError:
    return ApiError(status.HTTP_409_CONFLICT, code, message)


# --- Price -----------------------------------------------------------------------------


async def plan_price(db: AsyncSession) -> tuple[Product, Price] | None:
    """The plan's price, when one is on sale."""
    row = (
        await db.execute(
            select(Product, Price)
            .join(Price, Price.product_id == Product.id)
            .where(
                Product.key == PRODUCT_KEY,
                Product.active.is_(True),
                Price.active.is_(True),
                Price.interval == PriceInterval.ONE_TIME,
            )
        )
    ).one_or_none()
    return (row[0], row[1]) if row else None


# --- Reading ---------------------------------------------------------------------------


async def get_plan(db: AsyncSession, project: Project, *, lock: bool = False) -> ProjectPlan | None:
    query = select(ProjectPlan).where(
        ProjectPlan.organisation_id == project.organisation_id,
        ProjectPlan.project_id == project.id,
    )
    if lock:
        query = query.with_for_update()
    return (await db.execute(query)).scalar_one_or_none()


async def require_active(db: AsyncSession, project: Project, *, lock: bool = False) -> ProjectPlan:
    plan = await get_plan(db, project, lock=lock)
    if plan is None or plan.status != PlanStatus.ACTIVE:
        raise not_found("Project plan")
    return plan


async def items(db: AsyncSession, plan: ProjectPlan) -> list[ProjectPlanItem]:
    return list(
        (
            await db.execute(
                select(ProjectPlanItem)
                .where(
                    ProjectPlanItem.organisation_id == plan.organisation_id,
                    ProjectPlanItem.plan_id == plan.id,
                )
                .order_by(ProjectPlanItem.position, ProjectPlanItem.created_at)
            )
        ).scalars()
    )


async def get_item(db: AsyncSession, plan: ProjectPlan, item_id: uuid.UUID) -> ProjectPlanItem:
    item = (
        await db.execute(
            select(ProjectPlanItem)
            .where(
                ProjectPlanItem.organisation_id == plan.organisation_id,
                ProjectPlanItem.plan_id == plan.id,
                ProjectPlanItem.id == item_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if item is None:
        raise not_found("Plan step")
    return item


async def project_documents(db: AsyncSession, project: Project) -> dict[uuid.UUID, str]:
    """The project's usable uploads (virus-checked, not deleted): id to file name."""
    rows = await db.execute(
        select(UploadedDocument.id, UploadedDocument.original_filename).where(
            UploadedDocument.organisation_id == project.organisation_id,
            UploadedDocument.project_id == project.id,
            UploadedDocument.deleted_at.is_(None),
            UploadedDocument.scan_status == ScanStatus.CLEAN,
        )
    )
    return {i: name for i, name in rows.all()}


# --- Building --------------------------------------------------------------------------


async def _latest_checklist(
    db: AsyncSession, project: Project
) -> tuple[uuid.UUID, checklist.Checklist]:
    assessed = await assessments.list_for_project(db, project)
    if not assessed:
        raise _conflict(
            "assessment_required",
            "Answer the questions and run your assessment first: the plan is built from it.",
        )
    assessment, _, findings = await assessments.get(db, project.organisation_id, assessed[0][0].id)
    return assessment.id, await checklist.build(db, assessment, project, findings)


def schedule(starts_on: date, sections: list[checklist.Section]) -> dict[str, date]:
    """Suggested due dates by step key: each approval, council, grant or checklist part gets
    a two-week window after the one before; documents and tasks fall in the first window."""
    due: dict[str, date] = {}
    cursor = starts_on
    for s in sections:
        if not s.steps:
            continue
        early = s.kind in (checklist.SectionKind.DOCUMENTS, checklist.SectionKind.TASKS)
        start = starts_on if early else cursor
        n = len(s.steps)
        for i, step in enumerate(s.steps):
            due[step.key] = start + timedelta(days=max(1, math.ceil(WINDOW_DAYS * (i + 1) / n)))
        if not early:
            cursor += timedelta(days=WINDOW_DAYS)
    return due


def _sections_json(built: checklist.Checklist) -> list[dict[str, Any]]:
    return [s.summary_dict() for s in built.sections]


def _new_item(
    plan: ProjectPlan,
    section: checklist.Section,
    step: checklist.Step,
    *,
    position: int,
    due_on: date | None,
    actor_id: uuid.UUID | None,
    now: datetime,
) -> ProjectPlanItem:
    settled = step.done or step.not_applicable
    return ProjectPlanItem(
        organisation_id=plan.organisation_id,
        plan_id=plan.id,
        source_key=step.key[:200],
        section_key=section.key[:200],
        position=position,
        kind=step.kind,
        title=step.title[:600],
        detail=step.detail[:2000] if step.detail else None,
        timeframe=step.timeframe,
        cost=step.cost,
        link_url=step.link_url,
        link_label=step.link_label,
        owner=DEFAULT_OWNER,
        due_on=due_on,
        status=PlanItemStatus.NOT_APPLICABLE
        if step.not_applicable
        else PlanItemStatus.DONE
        if step.done
        else PlanItemStatus.OPEN,
        completed_at=now if settled else None,
        created_by=actor_id,
    )


async def start(
    db: AsyncSession,
    project: Project,
    *,
    price: tuple[Product, Price] | None,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> ProjectPlan:
    """Start a plan from the latest assessment. With a price, it waits for payment (and a
    plan already waiting is reused, so a second click doesn't charge twice)."""
    if project.status == ProjectStatus.ARCHIVED:
        raise _conflict("project_archived", "Move this project back into progress first.")
    plan = await get_plan(db, project, lock=True)
    if plan is not None:
        if plan.status == PlanStatus.ACTIVE:
            raise _conflict("plan_exists", "This project already has a project plan.")
        payment = await db.get(Payment, plan.payment_id)
        if payment is not None and payment.status == PaymentStatus.PENDING:
            return plan
        # The earlier payment failed or was cancelled: start again from scratch.
        await db.delete(plan)
        await db.flush()
    assessment_id, built = await _latest_checklist(db, project)
    if not built.sections:
        raise _conflict(
            "nothing_to_plan",
            "Your assessment didn't find any steps to plan yet. Answer any missing questions "
            "and run it again.",
        )
    plan_id = uuid.uuid4()
    payment = None
    if price is not None:
        payment = await billing.start_payment(
            db,
            organisation_id=project.organisation_id,
            purpose=PaymentPurpose.PRODUCT,
            product=price[0],
            price=price[1],
            subject_type=PAYMENT_SUBJECT,
            subject_id=plan_id,
            actor_id=actor_id,
        )
    now = utcnow()
    starts_on = today()
    plan = ProjectPlan(
        id=plan_id,
        organisation_id=project.organisation_id,
        project_id=project.id,
        assessment_id=assessment_id,
        status=PlanStatus.PAYMENT_PENDING if payment else PlanStatus.ACTIVE,
        payment_id=payment.id if payment else None,
        complimentary=payment is None,
        starts_on=starts_on,
        activated_at=None if payment else now,
        sections=_sections_json(built),
        created_by=actor_id,
    )
    db.add(plan)
    await db.flush()
    due = schedule(starts_on, built.sections)
    position = 0
    for section in built.sections:
        for step in section.steps:
            position += 1
            db.add(
                _new_item(
                    plan,
                    section,
                    step,
                    position=position,
                    due_on=due.get(step.key),
                    actor_id=actor_id,
                    now=now,
                )
            )
    await db.flush()
    await audit.record(
        db,
        "plan.started",
        actor_user_id=actor_id,
        organisation_id=project.organisation_id,
        target_type="project_plan",
        target_id=plan.id,
        meta=meta,
        details={
            "project_id": str(project.id),
            "assessment_id": str(assessment_id),
            "steps": position,
        }
        | ({"payment_id": str(payment.id)} if payment else {"complimentary": True}),
    )
    return plan


async def _activate(db: AsyncSession, plan: ProjectPlan, *, now: datetime) -> None:
    """Start the timeline from today: the dates move by however long payment took."""
    shift = today() - plan.starts_on
    plan.status = PlanStatus.ACTIVE
    plan.activated_at = now
    plan.starts_on = today()
    if shift.days:
        for item in await items(db, plan):
            if item.due_on is not None:
                item.due_on += shift
    await db.flush()


async def payment_received(db: AsyncSession, payment: Payment) -> None:
    """Stripe confirmed a plan's payment (webhook, organisation bound): switch it on."""
    plan = (
        await db.execute(
            select(ProjectPlan)
            .where(
                ProjectPlan.organisation_id == payment.organisation_id,
                ProjectPlan.id == payment.subject_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if plan is None or plan.status == PlanStatus.ACTIVE:
        return
    await _activate(db, plan, now=utcnow())
    await audit.record(
        db,
        "plan.activated",
        organisation_id=plan.organisation_id,
        target_type="project_plan",
        target_id=plan.id,
        details={"payment_id": str(payment.id)},
    )


async def cancel_pending(db: AsyncSession, plan: ProjectPlan) -> str | None:
    """Give up on a plan that hasn't been paid for. Returns the checkout page to close."""
    if plan.status != PlanStatus.PAYMENT_PENDING:
        raise _conflict("plan_active", "This plan is already paid for.")
    session_id = None
    if plan.payment_id is not None:
        payment = await billing.get_payment(db, plan.organisation_id, plan.payment_id, lock=True)
        session_id = payment.stripe_checkout_session_id
        await billing.cancel_payment(db, payment)
    await db.delete(plan)
    await db.flush()
    return session_id


async def refresh(
    db: AsyncSession, project: Project, plan: ProjectPlan, *, actor_id: uuid.UUID
) -> int:
    """Bring the plan up to the latest assessment. Returns how many steps were added."""
    assessment_id, built = await _latest_checklist(db, project)
    existing = {i.source_key: i for i in await items(db, plan) if i.source_key}
    last = (
        await db.execute(
            select(func.max(ProjectPlanItem.position)).where(ProjectPlanItem.plan_id == plan.id)
        )
    ).scalar_one() or 0
    due = schedule(today(), built.sections)
    now = utcnow()
    added = 0
    for section in built.sections:
        for step in section.steps:
            item = existing.get(step.key[:200])
            if item is None:
                last += 1
                added += 1
                db.add(
                    _new_item(
                        plan,
                        section,
                        step,
                        position=last,
                        due_on=due.get(step.key),
                        actor_id=actor_id,
                        now=now,
                    )
                )
            elif step.done and item.status == PlanItemStatus.OPEN:
                item.status = PlanItemStatus.DONE
                item.completed_at = now
    # Keep the parts this assessment no longer names (their steps stay in the plan).
    fresh = {s["key"]: s for s in _sections_json(built)}
    kept = [s for s in plan.sections if s["key"] not in fresh]
    plan.sections = list(fresh.values()) + kept
    plan.assessment_id = assessment_id
    await db.flush()
    return added


# --- Working through it ----------------------------------------------------------------


async def _sync_source(
    db: AsyncSession, plan: ProjectPlan, item: ProjectPlanItem, actor_id: uuid.UUID
) -> None:
    """Tick (or untick) the project task or checklist item this step came from."""
    key = item.source_key or ""
    now = utcnow()
    if key.startswith("task:"):
        try:
            task_id = uuid.UUID(key.removeprefix("task:"))
        except ValueError:
            return
        task = (
            await db.execute(
                select(Task).where(
                    Task.organisation_id == plan.organisation_id,
                    Task.project_id == plan.project_id,
                    Task.id == task_id,
                    Task.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if task is None or task.status == TaskStatus.CANCELLED:
            return
        wanted = TaskStatus.DONE if item.status == PlanItemStatus.DONE else TaskStatus.OPEN
        if task.status != wanted:
            task.status = wanted
            task.completed_at = now if wanted == TaskStatus.DONE else None
    elif key.startswith("checklist:"):
        parts = key.split(":")
        if len(parts) != 3:
            return
        row = (
            await db.execute(
                select(ChecklistItem)
                .join(ProjectChecklist, ProjectChecklist.id == ChecklistItem.checklist_id)
                .where(
                    ProjectChecklist.organisation_id == plan.organisation_id,
                    ProjectChecklist.project_id == plan.project_id,
                    ProjectChecklist.checklist_key == parts[1],
                    ChecklistItem.item_key == parts[2],
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return
        wanted_item = {
            PlanItemStatus.DONE: ItemStatus.DONE,
            PlanItemStatus.NOT_APPLICABLE: ItemStatus.NOT_APPLICABLE,
        }.get(PlanItemStatus(item.status), ItemStatus.OPEN)
        if row.status != wanted_item:
            row.status = wanted_item
            row.completed_at = None if wanted_item == ItemStatus.OPEN else now
            row.completed_by = None if wanted_item == ItemStatus.OPEN else actor_id
    await db.flush()


async def _check_documents(
    db: AsyncSession, project: Project, ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    usable = await project_documents(db, project)
    unknown = [i for i in ids if i not in usable]
    if unknown:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "document_unavailable",
            "Choose files uploaded to this project that have passed the virus check.",
        )
    return list(dict.fromkeys(ids))


async def update_item(
    db: AsyncSession,
    project: Project,
    plan: ProjectPlan,
    item: ProjectPlanItem,
    changes: dict[str, Any],
    *,
    actor_id: uuid.UUID,
) -> ProjectPlanItem:
    if "status" in changes and changes["status"] is None:
        del changes["status"]
    if "title" in changes:
        if item.kind not in EDITABLE_KINDS:
            raise _conflict("not_editable", "Only your own steps can be renamed.")
        if not changes["title"]:
            del changes["title"]
    if changes.get("assignee_user_id") is not None:
        await projects._require_member(db, plan.organisation_id, changes["assignee_user_id"])
    if "document_ids" in changes:
        changes["document_ids"] = await _check_documents(db, project, changes["document_ids"] or [])
    new_status = changes.get("status")
    if new_status is not None and new_status != item.status:
        item.completed_at = None if new_status == PlanItemStatus.OPEN else utcnow()
    for key, value in changes.items():
        setattr(item, key, value)
    await db.flush()
    if new_status is not None:
        await _sync_source(db, plan, item, actor_id)
    return item


async def _next_position(db: AsyncSession, plan: ProjectPlan) -> int:
    last = (
        await db.execute(
            select(func.max(ProjectPlanItem.position)).where(ProjectPlanItem.plan_id == plan.id)
        )
    ).scalar_one()
    return (last or 0) + 1


def _ensure_own_section(plan: ProjectPlan) -> None:
    if not any(s["key"] == OWN_SECTION["key"] for s in plan.sections):
        plan.sections = [*plan.sections, dict(OWN_SECTION)]


async def add_item(
    db: AsyncSession,
    project: Project,
    plan: ProjectPlan,
    data: dict[str, Any],
    *,
    actor_id: uuid.UUID,
) -> ProjectPlanItem:
    """One of the customer's own steps, in a part of the plan or in their own list."""
    section_key = data.pop("section_key", None) or OWN_SECTION["key"]
    if section_key == OWN_SECTION["key"]:
        _ensure_own_section(plan)
    elif not any(s["key"] == section_key for s in plan.sections):
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "unknown_section",
            "Choose a part of this plan.",
        )
    if data.get("assignee_user_id") is not None:
        await projects._require_member(db, plan.organisation_id, data["assignee_user_id"])
    item = ProjectPlanItem(
        organisation_id=plan.organisation_id,
        plan_id=plan.id,
        section_key=section_key,
        position=await _next_position(db, plan),
        kind=PlanItemKind.CUSTOM,
        owner=data.pop("owner", None) or DEFAULT_OWNER,
        created_by=actor_id,
        **data,
    )
    db.add(item)
    await db.flush()
    return item


async def delete_item(db: AsyncSession, item: ProjectPlanItem) -> None:
    if item.kind not in EDITABLE_KINDS:
        raise _conflict(
            "not_deletable",
            "Steps from your checklist can't be removed. Mark it as not applying instead.",
        )
    await db.delete(item)
    await db.flush()


async def add_follow_up(
    db: AsyncSession,
    project: Project,
    plan: ProjectPlan,
    *,
    partner_id: uuid.UUID,
    name: str,
    contact: str | None,
    section_key: str | None,
    due_on: date,
    remind: bool,
    actor_id: uuid.UUID,
) -> ProjectPlanItem:
    """A step to call a suggested partner, due on ``due_on``, with an email reminder that
    morning when asked for."""
    if section_key and not any(s["key"] == section_key for s in plan.sections):
        section_key = None
    if not section_key:
        _ensure_own_section(plan)
    item = ProjectPlanItem(
        organisation_id=plan.organisation_id,
        plan_id=plan.id,
        section_key=section_key or OWN_SECTION["key"],
        position=await _next_position(db, plan),
        kind=PlanItemKind.FOLLOW_UP,
        title=f"Call {name}"[:600],
        detail=contact,
        partner_organisation_id=partner_id,
        owner=DEFAULT_OWNER,
        due_on=due_on,
        created_by=actor_id,
    )
    db.add(item)
    await db.flush()
    if remind:
        fires_at = datetime.combine(due_on, time(9), tzinfo=BRISBANE)
        if fires_at > utcnow():
            await projects.create_reminder(
                db,
                project,
                {
                    "title": f"Follow up with {name}"[:200],
                    "fires_at": fires_at,
                    "channel": ReminderChannel.EMAIL,
                    "body": (contact or "")[:1000] or None,
                    "link_path": f"/projects/{project.id}/plan",
                },
                actor_id=actor_id,
            )
    return item


# --- Progress --------------------------------------------------------------------------


def progress(rows: list[ProjectPlanItem], on: date) -> dict[str, Any]:
    counted = [i for i in rows if i.status != PlanItemStatus.NOT_APPLICABLE]
    done = sum(1 for i in counted if i.status == PlanItemStatus.DONE)
    open_ = [i for i in counted if i.status == PlanItemStatus.OPEN]
    dated = sorted((i for i in open_ if i.due_on is not None), key=lambda i: i.due_on or on)
    return {
        "total": len(counted),
        "done": done,
        "percent": round(100 * done / len(counted)) if counted else 0,
        "overdue": sum(1 for i in dated if i.due_on is not None and i.due_on < on),
        "due_this_week": sum(
            1 for i in dated if i.due_on is not None and on <= i.due_on <= on + timedelta(days=7)
        ),
        "next_item_id": dated[0].id if dated else (open_[0].id if open_ else None),
        "finish_on": max((i.due_on for i in counted if i.due_on), default=None),
    }
