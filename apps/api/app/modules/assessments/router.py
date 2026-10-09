"""``/v1/organisations/{organisation_id}``: run and read a project's assessments."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import DbDep, MetaDep, OrgContext, require_org_permission
from app.modules.assessments import approval_map, service
from app.modules.assessments.models import Assessment, AssessmentFinding
from app.modules.assessments.schemas import (
    ApprovalMapEntryOut,
    ApprovalRequirementOut,
    AssessmentOut,
    AssessmentSummary,
    EvidenceRequirementOut,
    FindingOut,
    FindingSourceOut,
    ReferralCategoryOut,
    RuleSetScopeOut,
)
from app.modules.grants import router as grants_router
from app.modules.grants import service as grants
from app.modules.marketplace import service as marketplace
from app.modules.projects import service as projects
from app.modules.projects.models import Project
from app.modules.rules.payload import parse_payload
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


async def _referral_categories(
    db: DbDep, findings: list[AssessmentFinding]
) -> list[ReferralCategoryOut]:
    by_key: dict[str, list[uuid.UUID]] = {}
    for f in findings:
        for key in parse_payload(f.payload).referral_categories:
            by_key.setdefault(key, []).append(f.id)
    # A category retired since the assessment keeps its name; an unknown key gets a readable one.
    known = await marketplace.by_keys(db, by_key)
    return [
        ReferralCategoryOut(
            key=k,
            label=known[k].label if k in known else marketplace.fallback_label(k),
            description=known[k].description if k in known else None,
            finding_ids=ids,
        )
        for k, ids in by_key.items()
    ]


def _limitations(a: Assessment) -> list[str]:
    seen: dict[str, None] = {}
    for rs in a.rule_sets:
        if rs.get("scope") != "OUT_OF_SCOPE":
            for text in rs.get("limitations", []):
                seen.setdefault(text, None)
    return list(seen)


async def assessment_detail(
    db: DbDep, a: Assessment, project: Project, findings: list[AssessmentFinding]
) -> AssessmentOut:
    approvals, evidence = await service.requirements(db, a)
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
                referral_categories=parse_payload(f.payload).referral_categories,
            )
            for f in findings
        ],
        approval_requirements=[
            ApprovalRequirementOut.model_validate(r, from_attributes=True) for r in approvals
        ],
        evidence_requirements=[
            EvidenceRequirementOut.model_validate(r, from_attributes=True) for r in evidence
        ],
        approval_map=[
            ApprovalMapEntryOut.model_validate(e, from_attributes=True)
            for e in approval_map.build(approvals)
        ],
        referral_categories=await _referral_categories(db, findings),
        limitations=_limitations(a),
        grant_matches=[
            grants_router.match_out(m, v) for m, v in await grants.matches_for(db, a.id)
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
    return await assessment_detail(db, a, p, findings)


@router.get("/projects/{project_id}/assessments", response_model=list[AssessmentSummary])
async def list_assessments(project_id: uuid.UUID, ctx: Read, db: DbDep) -> list[AssessmentSummary]:
    project = await projects.get_project(db, ctx.organisation.id, project_id)
    return [summary_out(a, n) for a, n in await service.list_for_project(db, project)]


@router.get("/assessments/{assessment_id}", response_model=AssessmentOut)
async def get_assessment(assessment_id: uuid.UUID, ctx: Read, db: DbDep) -> AssessmentOut:
    a, p, findings = await service.get(db, ctx.organisation.id, assessment_id)
    return await assessment_detail(db, a, p, findings)
