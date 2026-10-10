"""AI jobs: request a draft, run it through a provider, validate and post-check it.

Nothing an AI job produces changes a finding, requirement, match or report. Its output is
stored on the job, shown beside the findings as an AI-written draft, and only once it has
passed schema validation and the post-checks in ``validation.py``.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, not_found
from app.modules.ai import inputs, prompts, validation
from app.modules.ai.models import AIJob, AIProviderLog, AITask, CallStatus, JobStatus, PromptVersion
from app.modules.ai.outputs import AssessmentExplanationV1, GrantDraftV1, get_schema
from app.modules.ai.provider import (
    AIDisabled,
    AIProvider,
    ProviderError,
    ProviderResult,
    StructuredRequest,
    TransientProviderError,
)
from app.modules.assessments import service as assessments
from app.modules.assessments.models import Assessment, AssessmentFinding
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.projects.models import Project

log = logging.getLogger(__name__)

MAX_ERRORS = 20


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Prices:
    """US dollars per million tokens (``AI_*_PRICE_PER_MTOK_USD``)."""

    input_per_mtok: float = 0.0
    output_per_mtok: float = 0.0

    def cost_micros(self, tokens_in: int | None, tokens_out: int | None) -> int | None:
        if tokens_in is None and tokens_out is None:
            return None
        # Dollars per million tokens is exactly millionths of a dollar per token.
        return round(
            (tokens_in or 0) * self.input_per_mtok + (tokens_out or 0) * self.output_per_mtok
        )


async def _build_input(
    db: AsyncSession,
    task: AITask,
    assessment: Assessment,
    project: Project,
    findings: list[AssessmentFinding],
    subject_id: uuid.UUID | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if task == AITask.ASSESSMENT_EXPLANATION:
        return await inputs.explanation_input(db, assessment, project, findings)
    if subject_id is None:
        raise ApiError(422, "program_required", "Choose the grant program to draft for.")
    return await inputs.grant_draft_input(db, assessment, project, findings, subject_id)


def _input_hash(prompt: PromptVersion, data: dict[str, Any]) -> bytes:
    canonical = validation.canonical({"prompt_version_id": str(prompt.id), "data": data})
    return hashlib.sha256(canonical.encode()).digest()


async def request_job(
    db: AsyncSession,
    *,
    organisation_id: uuid.UUID,
    assessment_id: uuid.UUID,
    task: AITask,
    subject_id: uuid.UUID | None,
    regenerate: bool,
    actor_id: uuid.UUID,
    meta: RequestMeta,
) -> tuple[AIJob, bool]:
    """The job for this request, and whether it is new. Asking again for the same input
    returns the pending or finished job instead of paying for another call, unless the
    customer asks to regenerate."""
    assessment, project, findings = await assessments.get(db, organisation_id, assessment_id)
    prompt = await prompts.published(db, task)
    if prompt is None:
        raise ApiError(503, "ai_unavailable", "AI drafting is not set up on this server yet.")
    data, refs = await _build_input(db, task, assessment, project, findings, subject_id)
    input_hash = _input_hash(prompt, data)
    if not regenerate:
        existing = (
            await db.execute(
                select(AIJob)
                .where(
                    AIJob.assessment_id == assessment.id,
                    AIJob.task == task,
                    AIJob.input_hash == input_hash,
                    AIJob.status.in_([JobStatus.PENDING, JobStatus.SUCCEEDED]),
                )
                .order_by(AIJob.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing, False
    job = AIJob(
        organisation_id=organisation_id,
        project_id=project.id,
        assessment_id=assessment.id,
        task=task,
        subject_id=subject_id,
        prompt_version_id=prompt.id,
        input_refs=refs,
        input_hash=input_hash,
        status=JobStatus.PENDING,
        created_by=actor_id,
    )
    db.add(job)
    await db.flush()
    await audit.record(
        db,
        "ai.job_requested",
        actor_user_id=actor_id,
        organisation_id=organisation_id,
        target_type="ai_job",
        target_id=job.id,
        meta=meta,
        details={"task": str(task), "assessment_id": str(assessment.id)}
        | ({"subject_id": str(subject_id)} if subject_id else {}),
    )
    return job, True


async def get_job(
    db: AsyncSession, organisation_id: uuid.UUID, job_id: uuid.UUID, *, lock: bool = False
) -> AIJob:
    query = (
        select(AIJob)
        .join(Project, Project.id == AIJob.project_id)
        .where(
            AIJob.id == job_id,
            AIJob.organisation_id == organisation_id,
            Project.deleted_at.is_(None),
        )
    )
    if lock:
        query = query.with_for_update(of=AIJob)
    job = (await db.execute(query)).scalar_one_or_none()
    if job is None:
        raise not_found("AI draft")
    return job


async def jobs_for_assessment(
    db: AsyncSession, organisation_id: uuid.UUID, assessment_id: uuid.UUID
) -> list[AIJob]:
    await assessments.get(db, organisation_id, assessment_id)  # 404 for others
    return list(
        (
            await db.execute(
                select(AIJob)
                .where(AIJob.assessment_id == assessment_id)
                .order_by(AIJob.created_at.desc())
            )
        ).scalars()
    )


async def prompt_versions(
    db: AsyncSession, ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, PromptVersion]:
    if not ids:
        return {}
    rows = (await db.execute(select(PromptVersion).where(PromptVersion.id.in_(set(ids))))).scalars()
    return {p.id: p for p in rows}


# --- Running a job (worker, or inline in tests) -----------------------------------------


def _check(task: str, output: Any, data: dict[str, Any]) -> list[str]:
    if isinstance(output, AssessmentExplanationV1):
        return validation.check_explanation(output, data)
    if isinstance(output, GrantDraftV1):
        return validation.check_grant_draft(output, data)
    raise ValueError(f"no post-check for {task}")


def _validation_messages(exc: ValidationError) -> list[str]:
    return [
        f"{'.'.join(str(p) for p in e['loc']) or 'answer'}: {e['msg']}"
        for e in exc.errors()[:MAX_ERRORS]
    ]


async def run_job(
    db: AsyncSession,
    provider: AIProvider,
    prices: Prices,
    organisation_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    final_attempt: bool,
) -> str | None:
    """Run one pending job. Raises ``TransientProviderError`` (after committing the call's
    log row) when the worker should retry later."""
    try:
        job = await get_job(db, organisation_id, job_id, lock=True)
    except ApiError:
        return None
    if job.status != JobStatus.PENDING:
        return None
    job.attempts += 1
    prompt = (
        await db.execute(select(PromptVersion).where(PromptVersion.id == job.prompt_version_id))
    ).scalar_one()
    schema = get_schema(prompt.output_schema_name, prompt.output_schema_version)
    try:
        assessment, project, findings = await assessments.get(
            db, organisation_id, job.assessment_id
        )
        data, _ = await _build_input(
            db, AITask(job.task), assessment, project, findings, job.subject_id
        )
    except ApiError as exc:
        return await _finish(
            db,
            job,
            JobStatus.FAILED,
            error=str(exc.detail["message"]) if isinstance(exc.detail, dict) else str(exc.detail),
        )
    request = StructuredRequest(
        task=job.task,
        system=prompt.system_prompt,
        user=prompts.render_user(prompt, data),
        schema=schema.json_schema(),
        data=data,
    )

    def log_call(
        status: CallStatus,
        model: str,
        tokens_in: int | None,
        tokens_out: int | None,
        latency_ms: int,
        error: str | None = None,
    ) -> None:
        db.add(
            AIProviderLog(
                organisation_id=organisation_id,
                ai_job_id=job.id,
                project_id=job.project_id,
                task=job.task,
                prompt_version_id=prompt.id,
                schema_name=schema.name,
                schema_version=schema.version,
                provider=provider.name,
                model=(model or provider.model)[:100],
                request_tokens=tokens_in,
                response_tokens=tokens_out,
                cost_micros=prices.cost_micros(tokens_in, tokens_out),
                latency_ms=latency_ms,
                status=status,
                error=error[:500] if error else None,
            )
        )

    started = utcnow()
    try:
        result: ProviderResult = await provider.generate_structured(request)
    except AIDisabled as exc:
        return await _finish(db, job, JobStatus.FAILED, error=str(exc))
    except ProviderError as exc:
        elapsed = int((utcnow() - started).total_seconds() * 1000)
        log_call(
            CallStatus.REFUSED if exc.refused else CallStatus.ERROR,
            exc.model,
            exc.request_tokens,
            exc.response_tokens,
            elapsed,
            str(exc),
        )
        if isinstance(exc, TransientProviderError) and not final_attempt:
            await db.commit()
            raise
        message = (
            "The AI provider declined to write this draft."
            if exc.refused
            else "The AI provider could not write this draft. Try again later."
        )
        return await _finish(db, job, JobStatus.FAILED, error=message)

    log_call(
        CallStatus.OK,
        result.model,
        result.request_tokens,
        result.response_tokens,
        result.latency_ms,
    )
    try:
        output = schema.model.model_validate(result.output)
    except ValidationError as exc:
        return await _finish(db, job, JobStatus.REJECTED, errors=_validation_messages(exc))
    errors = _check(job.task, output, data)
    if errors:
        return await _finish(db, job, JobStatus.REJECTED, errors=errors[:MAX_ERRORS])
    job.output = output.model_dump(mode="json")
    return await _finish(db, job, JobStatus.SUCCEEDED)


async def _finish(
    db: AsyncSession,
    job: AIJob,
    status: JobStatus,
    *,
    error: str | None = None,
    errors: list[str] | None = None,
) -> str:
    job.status = status
    job.completed_at = utcnow()
    if status == JobStatus.REJECTED:
        job.error = "The AI draft did not pass our checks, so it is not shown. Try again."
        job.validation_errors = errors
        log.warning("AI output rejected", extra={"ai_job_id": str(job.id), "errors": errors})
    elif error:
        job.error = error[:500]
    await db.flush()
    await audit.record(
        db,
        "ai.job_completed",
        organisation_id=job.organisation_id,
        target_type="ai_job",
        target_id=job.id,
        details={"task": job.task, "status": str(status)},
    )
    await db.commit()
    return str(status)


# --- Platform views ---------------------------------------------------------------------


@dataclass(frozen=True)
class UsageRow:
    provider: str
    model: str
    task: str
    status: str
    calls: int
    request_tokens: int
    response_tokens: int
    cost_micros: int


async def usage_since(db: AsyncSession, since: datetime) -> list[UsageRow]:
    """Totals across every organisation (no tenant data: counts and sums only)."""
    rows = await db.execute(text("SELECT * FROM ai_usage_summary(:since)"), {"since": since})
    return [UsageRow(*r) for r in rows]


async def published_prompts(db: AsyncSession) -> list[PromptVersion]:
    return list(
        (
            await db.execute(
                select(PromptVersion).order_by(PromptVersion.task, PromptVersion.version.desc())
            )
        ).scalars()
    )
