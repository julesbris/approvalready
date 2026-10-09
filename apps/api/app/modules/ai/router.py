"""AI drafts on an assessment, the AI status, and the staff usage and prompt views."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    AuthDep,
    DbDep,
    LimiterDep,
    MetaDep,
    OrgContext,
    ResourcesDep,
    SettingsDep,
    require_org_permission,
    require_platform_permission,
)
from app.core.config import AIProviderKind, Settings
from app.core.errors import ApiError, rate_limited
from app.core.ratelimit import Limit
from app.modules.ai import service
from app.modules.ai.models import AIJob, AITask, PromptVersion
from app.modules.ai.outputs import AssessmentExplanationV1, GrantDraftV1
from app.modules.ai.schemas import (
    AIJobOut,
    AIStatusOut,
    AIUsageOut,
    AIUsageRowOut,
    ExplanationIn,
    GrantDraftIn,
    PromptVersionOut,
)
from app.modules.tenancy.rbac import Perm

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/organisations/{organisation_id}", tags=["ai"])
status_router = APIRouter(prefix="/v1/ai", tags=["ai"])
admin_router = APIRouter(prefix="/v1/admin/ai", tags=["admin: ai"])

Read = Annotated[OrgContext, Depends(require_org_permission(Perm.PROJECT_READ))]
Write = Annotated[OrgContext, Depends(require_org_permission(Perm.PROJECT_WRITE))]
# Usage covers every organisation (totals only): administrators, like the audit log.
Staff = Annotated[OrgContext, Depends(require_platform_permission(Perm.PLATFORM_AUDIT_READ))]


def _enabled(settings: Settings) -> bool:
    return settings.ai_provider != AIProviderKind.NONE and (
        settings.ai_provider != AIProviderKind.ANTHROPIC or settings.anthropic_api_key is not None
    )


def status_out(settings: Settings) -> AIStatusOut:
    enabled = _enabled(settings)
    return AIStatusOut(
        enabled=enabled,
        provider=str(settings.ai_provider) if enabled else "none",
        model=settings.ai_model
        if enabled and settings.ai_provider == AIProviderKind.ANTHROPIC
        else None,
        mock=settings.ai_provider == AIProviderKind.MOCK,
    )


def job_out(job: AIJob, prompt: PromptVersion) -> AIJobOut:
    explanation = grant_draft = None
    if job.output is not None:
        if job.task == AITask.ASSESSMENT_EXPLANATION:
            explanation = AssessmentExplanationV1.model_validate(job.output)
        else:
            grant_draft = GrantDraftV1.model_validate(job.output)
    return AIJobOut(
        id=job.id,
        task=job.task,
        status=job.status,
        assessment_id=job.assessment_id,
        subject_id=job.subject_id,
        prompt_version=prompt.version,
        output_schema=f"{prompt.output_schema_name}.v{prompt.output_schema_version}",
        explanation=explanation,
        grant_draft=grant_draft,
        error=job.error,
        validation_errors=job.validation_errors or [],
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


async def jobs_out(db: DbDep, jobs: list[AIJob]) -> list[AIJobOut]:
    versions = await service.prompt_versions(db, [j.prompt_version_id for j in jobs])
    return [job_out(j, versions[j.prompt_version_id]) for j in jobs]


@status_router.get("/status", response_model=AIStatusOut)
async def ai_status(auth: AuthDep, settings: SettingsDep) -> AIStatusOut:
    """Whether AI drafting is switched on (the screens hide it when it is not)."""
    return status_out(settings)


async def _request(
    task: AITask,
    assessment_id: uuid.UUID,
    subject_id: uuid.UUID | None,
    regenerate: bool,
    ctx: OrgContext,
    db: DbDep,
    meta: MetaDep,
    resources: ResourcesDep,
    limiter: LimiterDep,
    settings: Settings,
) -> AIJobOut:
    if not _enabled(settings):
        raise ApiError(409, "ai_disabled", "AI drafting is switched off on this server.")
    job, created = await service.request_job(
        db,
        organisation_id=ctx.organisation.id,
        assessment_id=assessment_id,
        task=task,
        subject_id=subject_id,
        regenerate=regenerate,
        actor_id=ctx.auth.user.id,
        meta=meta,
    )
    if created:
        # Only new calls to the provider count towards the limit.
        limit = Limit("ai", settings.ai_jobs_per_user_per_hour, 3600)
        subject = str(ctx.auth.user.id)
        if await limiter.hit(limit, subject) > limit.max_hits:
            await db.rollback()
            raise rate_limited(await limiter.retry_after(limit, subject))
    await db.commit()
    org_id, job_id = ctx.organisation.id, job.id
    if created:
        try:
            await resources.jobs.ai(org_id, job_id)
        except Exception:
            # The scheduler's sweep re-queues it; the request still succeeds.
            log.exception("could not queue AI job")
    db.expire_all()  # an inline job changed the row in another session
    return (await jobs_out(db, [await service.get_job(db, org_id, job_id)]))[0]


@router.post(
    "/assessments/{assessment_id}/ai/explanation",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AIJobOut,
)
async def request_explanation(
    assessment_id: uuid.UUID,
    ctx: Write,
    db: DbDep,
    meta: MetaDep,
    resources: ResourcesDep,
    limiter: LimiterDep,
    settings: SettingsDep,
    body: ExplanationIn | None = None,
) -> AIJobOut:
    """Ask for a plain-language explanation of the findings. Poll the job until it is no
    longer PENDING. The same findings give back the same job unless ``regenerate``."""
    return await _request(
        AITask.ASSESSMENT_EXPLANATION,
        assessment_id,
        None,
        body is not None and body.regenerate,
        ctx,
        db,
        meta,
        resources,
        limiter,
        settings,
    )


@router.post(
    "/assessments/{assessment_id}/ai/grant-drafts",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AIJobOut,
)
async def request_grant_draft(
    assessment_id: uuid.UUID,
    body: GrantDraftIn,
    ctx: Write,
    db: DbDep,
    meta: MetaDep,
    resources: ResourcesDep,
    limiter: LimiterDep,
    settings: SettingsDep,
) -> AIJobOut:
    """Ask for grant application notes for one matched program, from the applicant's own
    answers. Not offered for programs whose criteria are not met."""
    return await _request(
        AITask.GRANT_DRAFT,
        assessment_id,
        body.program_id,
        body.regenerate,
        ctx,
        db,
        meta,
        resources,
        limiter,
        settings,
    )


@router.get("/assessments/{assessment_id}/ai-jobs", response_model=list[AIJobOut])
async def list_jobs(assessment_id: uuid.UUID, ctx: Read, db: DbDep) -> list[AIJobOut]:
    """Every AI draft for the assessment, newest first."""
    return await jobs_out(
        db, await service.jobs_for_assessment(db, ctx.organisation.id, assessment_id)
    )


@router.get("/ai-jobs/{job_id}", response_model=AIJobOut)
async def get_job(job_id: uuid.UUID, ctx: Read, db: DbDep) -> AIJobOut:
    return (await jobs_out(db, [await service.get_job(db, ctx.organisation.id, job_id)]))[0]


# --- Staff ------------------------------------------------------------------------------


@admin_router.get("/usage", response_model=AIUsageOut)
async def usage(
    ctx: Staff,
    db: DbDep,
    settings: SettingsDep,
    days: Annotated[int, Query(ge=1, le=366)] = 30,
) -> AIUsageOut:
    """Calls, tokens and cost by provider, model, task and outcome, across all
    organisations. Totals only: no prompts, outputs or customer data."""
    since = datetime.now(UTC) - timedelta(days=days)
    st = status_out(settings)
    return AIUsageOut(
        provider=st.provider,
        model=st.model,
        enabled=st.enabled,
        since=since,
        rows=[AIUsageRowOut(**vars(r)) for r in await service.usage_since(db, since)],
    )


@admin_router.get("/prompts", response_model=list[PromptVersionOut])
async def list_prompts(ctx: Staff, db: DbDep) -> list[PromptVersionOut]:
    """Every prompt version, newest first per task. Prompts change only through reviewed
    files in the repository."""
    return [
        PromptVersionOut.model_validate(p, from_attributes=True)
        for p in await service.published_prompts(db)
    ]
