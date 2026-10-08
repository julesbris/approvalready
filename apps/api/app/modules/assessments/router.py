"""``/v1/organisations/{organisation_id}``: run and read a project's assessments."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import DbDep, MetaDep, OrgContext, require_org_permission
from app.modules.assessments import service
from app.modules.assessments.models import Assessment, AssessmentFinding
from app.modules.assessments.schemas import (
    AssessmentOut,
    AssessmentSummary,
    FindingOut,
    FindingSourceOut,
    RuleSetScopeOut,
)
from app.modules.projects import service as projects
from app.modules.projects.models import Project
from app.modules.tenancy.rbac import Perm

router = APIRouter(prefix="/v1/organisations/{organisation_id}", tags=["assessments"])

Read = Annotated[OrgContext, Depends(require_org_permission(Perm.PROJECT_READ))]
Write = Annotated[OrgContext, Depends(require_org_permission(Perm.PROJECT_WRITE))]


def summary_out(a: Assessment, findings: int) -> AssessmentSummary:
    return AssessmentSummary(
        id=a.id,
        project_id=a.project_id,
        submission_id=a.submission_id,
        assessed_on=a.assessed_on,
        status=a.status,
        overall_confidence=a.overall_confidence,
        findings=findings,
        created_at=a.created_at,
    )


async def _detail(
    db: DbDep, a: Assessment, project: Project, findings: list[AssessmentFinding]
) -> AssessmentOut:
    return AssessmentOut(
        **summary_out(a, len(findings)).model_dump(),
        engine_version=a.engine_version,
        facts_hash=a.facts_hash.hex(),
        facts=a.facts_snapshot,
        fact_labels=await service.fact_labels(db, project, a, findings),
        rule_sets=[RuleSetScopeOut.model_validate(rs) for rs in a.rule_sets],
        finding_list=[
            FindingOut(
                id=f.id,
                rule_set_id=f.rule_set_id,
                rule_version_id=f.rule_version_id,
                rule_key=f.rule_key,
                rule_title=f.rule_title,
                result=f.result,
                outcome_type=f.outcome_type,
                title=f.title,
                detail=f.detail,
                confidence=f.confidence,
                confidence_reasons=f.confidence_reasons,
                missing_facts=f.missing_facts,
                trace=f.trace,
                sources=[FindingSourceOut.model_validate(s) for s in f.sources],
            )
            for f in findings
        ],
    )


@router.post(
    "/projects/{project_id}/assessments",
    status_code=status.HTTP_201_CREATED,
    response_model=AssessmentOut,
)
async def run_assessment(
    project_id: uuid.UUID, ctx: Write, db: DbDep, meta: MetaDep
) -> AssessmentOut:
    """Assess the project's latest submitted answers against the published rules."""
    project = await projects.get_project(db, ctx.organisation.id, project_id)
    assessment = await service.run(db, project, actor_id=ctx.auth.user.id, meta=meta)
    await db.commit()
    a, p, findings = await service.get(db, ctx.organisation.id, assessment.id)
    return await _detail(db, a, p, findings)


@router.get("/projects/{project_id}/assessments", response_model=list[AssessmentSummary])
async def list_assessments(project_id: uuid.UUID, ctx: Read, db: DbDep) -> list[AssessmentSummary]:
    project = await projects.get_project(db, ctx.organisation.id, project_id)
    return [summary_out(a, n) for a, n in await service.list_for_project(db, project)]


@router.get("/assessments/{assessment_id}", response_model=AssessmentOut)
async def get_assessment(assessment_id: uuid.UUID, ctx: Read, db: DbDep) -> AssessmentOut:
    a, p, findings = await service.get(db, ctx.organisation.id, assessment_id)
    return await _detail(db, a, p, findings)
