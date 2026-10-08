"""Running assessments: facts from a submitted questionnaire, evaluated against every
published rule of the project's vertical, stored with everything needed to explain and
reproduce the result.

Assessment dates are calendar dates in AEST (UTC+10, Queensland time, no daylight saving),
so a rule or source that takes effect "on 1 July" does so from midnight in Australia.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, not_found
from app.modules.assessments.models import Assessment, AssessmentFinding, AssessmentStatus
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.conditions import parse_condition, trace
from app.modules.projects import service as projects
from app.modules.projects.models import Project, ProjectStatus
from app.modules.questionnaires import service as questionnaires
from app.modules.questionnaires.models import QuestionnaireSubmission, SubmissionStatus
from app.modules.rules import engine
from app.modules.rules import service as rules
from app.modules.rules.models import RuleVersion

AEST = timezone(timedelta(hours=10), "AEST")


def assessment_date(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(AEST).date()


async def latest_submitted(db: AsyncSession, project: Project) -> QuestionnaireSubmission | None:
    return (
        await db.execute(
            select(QuestionnaireSubmission)
            .where(
                QuestionnaireSubmission.project_id == project.id,
                QuestionnaireSubmission.status == SubmissionStatus.SUBMITTED,
            )
            .order_by(QuestionnaireSubmission.submitted_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def run(
    db: AsyncSession,
    project: Project,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
    on: date | None = None,
) -> Assessment:
    if project.status == ProjectStatus.ARCHIVED:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "project_archived",
            "This project is archived. Move it back into progress to assess it.",
        )
    submission = await latest_submitted(db, project)
    if submission is None:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "answers_not_submitted",
            "Submit the questionnaire before running an assessment.",
        )
    on = on or assessment_date()
    facts = (await questionnaires.view(db, submission)).state.facts
    results = [
        engine.evaluate_rule_set(spec, facts, on)
        for spec in await rules.published_rule_sets(db, project.vertical)
    ]
    applicable = any(r.scope in ("IN_SCOPE", "NEEDS_INFORMATION") for r in results)
    snapshot = engine.encode_facts(facts)
    assessment = Assessment(
        organisation_id=project.organisation_id,
        project_id=project.id,
        submission_id=submission.id,
        assessed_on=on,
        engine_version=engine.ENGINE_VERSION,
        facts_snapshot=snapshot,
        facts_hash=engine.canonical_hash(snapshot),
        status=AssessmentStatus.COMPLETED if applicable else AssessmentStatus.NO_APPLICABLE_RULES,
        overall_confidence=engine.overall_confidence(
            [r for r in results if r.scope != "OUT_OF_SCOPE"]
        ),
        rule_sets=[r.as_json() for r in results],
        created_by=actor_id,
    )
    db.add(assessment)
    await db.flush()
    findings = [f for r in results for f in r.findings]
    for ordinal, f in enumerate(findings, start=1):
        db.add(
            AssessmentFinding(
                organisation_id=project.organisation_id,
                assessment_id=assessment.id,
                ordinal=ordinal,
                rule_set_id=f.rule_set_id,
                rule_version_id=f.rule_version_id,
                rule_key=f.rule_key,
                rule_title=f.rule_title,
                result=f.result,
                outcome_type=f.outcome.outcome_type if f.outcome else None,
                title=f.outcome.title if f.outcome else None,
                detail=f.outcome.detail if f.outcome else None,
                confidence=f.confidence,
                confidence_reasons=f.confidence_reasons,
                trace=f.trace,
                missing_facts=f.missing_facts,
                sources=f.sources,
            )
        )
    await db.flush()
    await db.refresh(assessment)
    await audit.record(
        db,
        "assessment.run",
        actor_user_id=actor_id,
        organisation_id=project.organisation_id,
        target_type="assessment",
        target_id=assessment.id,
        meta=meta,
        details={
            "project_id": str(project.id),
            "status": assessment.status,
            "overall_confidence": assessment.overall_confidence,
            "findings": len(findings),
            "facts_hash": assessment.facts_hash.hex(),
        },
    )
    await projects.mark_assessed(db, project, actor_id=actor_id, meta=meta)
    return assessment


async def list_for_project(db: AsyncSession, project: Project) -> list[tuple[Assessment, int]]:
    counts = (
        select(AssessmentFinding.assessment_id, func.count(AssessmentFinding.id).label("n"))
        .group_by(AssessmentFinding.assessment_id)
        .subquery()
    )
    rows = await db.execute(
        select(Assessment, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.assessment_id == Assessment.id)
        .where(Assessment.project_id == project.id)
        .order_by(Assessment.created_at.desc(), Assessment.id.desc())
    )
    return [(a, int(n)) for a, n in rows.all()]


async def get(
    db: AsyncSession, organisation_id: uuid.UUID, assessment_id: uuid.UUID
) -> tuple[Assessment, Project, list[AssessmentFinding]]:
    row = (
        await db.execute(
            select(Assessment, Project)
            .join(Project, Project.id == Assessment.project_id)
            .where(
                Assessment.id == assessment_id,
                Assessment.organisation_id == organisation_id,
                Project.deleted_at.is_(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise not_found("Assessment")
    findings = list(
        (
            await db.execute(
                select(AssessmentFinding)
                .where(AssessmentFinding.assessment_id == assessment_id)
                .order_by(AssessmentFinding.ordinal)
            )
        ).scalars()
    )
    return row[0], row[1], findings


def _trace_facts(node: dict[str, Any], found: set[str]) -> None:
    if node.get("kind") == "leaf":
        found.add(node["fact"])
    for child in node.get("children", []):
        _trace_facts(child, found)


async def fact_labels(
    db: AsyncSession, project: Project, assessment: Assessment, findings: list[AssessmentFinding]
) -> dict[str, str]:
    """Question labels for every fact the assessment mentions (traces, missing facts)."""
    mentioned: set[str] = set()
    for f in findings:
        _trace_facts(f.trace, mentioned)
    for rs in assessment.rule_sets:
        if rs.get("scope_trace"):
            _trace_facts(rs["scope_trace"], mentioned)
    labels = await questionnaires.fact_labels(db, project.vertical)
    return {k: labels[k] for k in sorted(mentioned) if k in labels}


async def replay_matches(db: AsyncSession, assessment: Assessment) -> bool:
    """Re-evaluate the stored facts with the pinned rule versions: every result and trace
    must come out identical (the reproducibility guarantee)."""
    if engine.canonical_hash(assessment.facts_snapshot) != assessment.facts_hash:
        return False
    facts = engine.decode_facts(assessment.facts_snapshot)
    findings = (
        await db.execute(
            select(AssessmentFinding, RuleVersion)
            .join(RuleVersion, RuleVersion.id == AssessmentFinding.rule_version_id)
            .where(AssessmentFinding.assessment_id == assessment.id)
        )
    ).all()
    return all(
        trace(parse_condition(version.condition), facts) == finding.trace
        for finding, version in findings
    )
