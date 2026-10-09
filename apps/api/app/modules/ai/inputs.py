"""The data an AI task is given: built from one project's stored records, nothing else.

Each builder returns the data block (what the model reads) and its references (ids and
keys only, stored on the job). Customer-written text such as a project title stays out:
the model needs the findings and facts, not free text that could carry instructions.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, not_found
from app.modules.assessments import approval_map
from app.modules.assessments import service as assessments
from app.modules.assessments.models import Assessment, AssessmentFinding
from app.modules.grants import service as grants
from app.modules.grants.models import MatchStatus
from app.modules.marketplace import service as marketplace
from app.modules.projects.models import Project
from app.modules.questionnaires import service as questionnaires
from app.modules.rules.payload import parse_payload

_SOURCE_FIELDS = (
    "citation",
    "document_title",
    "organisation_name",
    "url",
    "section",
    "clause",
    "page",
    "verification_status",
    "in_force",
)


def _plain(value: Any) -> Any:
    """Encoded fact values (rules engine) as plain JSON: decimals become their digits."""
    if isinstance(value, dict):
        if set(value) == {"$decimal"}:
            return value["$decimal"]
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


async def explanation_input(
    db: AsyncSession, assessment: Assessment, project: Project, findings: list[AssessmentFinding]
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not findings:
        raise ApiError(409, "nothing_to_explain", "This assessment has no findings to explain.")
    labels = await questionnaires.fact_labels(db, project.vertical)
    approvals, _ = await assessments.requirements(db, assessment)
    category_keys = {k for f in findings for k in parse_payload(f.payload).referral_categories}
    categories = await marketplace.by_keys(db, category_keys)
    data: dict[str, Any] = {
        "assessment": {
            "vertical": project.vertical,
            "assessed_on": assessment.assessed_on.isoformat(),
            "status": assessment.status,
            "overall_confidence": assessment.overall_confidence,
        },
        "findings": [
            {
                "id": str(f.id),
                "rule_title": f.rule_title,
                "result": f.result,
                "outcome_type": f.outcome_type,
                "title": f.title,
                "detail": f.detail,
                "confidence": f.confidence,
                "confidence_reasons": f.confidence_reasons,
                "missing_facts": [labels.get(k, k) for k in f.missing_facts],
                "who_can_help": [
                    categories[k].label if k in categories else marketplace.fallback_label(k)
                    for k in parse_payload(f.payload).referral_categories
                ],
                "sources": [{k: s.get(k) for k in _SOURCE_FIELDS} for s in f.sources],
            }
            for f in findings
        ],
        "approvals": [
            {
                "title": e.title,
                "certainty": e.certainty,
                "authority": e.authority,
                "pathway": e.pathway,
                "finding_ids": [str(i) for i in e.finding_ids],
            }
            for e in approval_map.build(approvals)
        ],
        "limitations": _limitations(assessment),
    }
    refs = {"finding_ids": [str(f.id) for f in findings]}
    return data, refs


def _limitations(a: Assessment) -> list[str]:
    seen: dict[str, None] = {}
    for rs in a.rule_sets:
        if rs.get("scope") != "OUT_OF_SCOPE":
            for text in rs.get("limitations", []):
                seen.setdefault(text, None)
    return list(seen)


async def grant_draft_input(
    db: AsyncSession,
    assessment: Assessment,
    project: Project,
    findings: list[AssessmentFinding],
    program_id: uuid.UUID,
) -> tuple[dict[str, Any], dict[str, Any]]:
    found = [
        (m, v) for m, v in await grants.matches_for(db, assessment.id) if m.program_id == program_id
    ]
    if not found:
        raise not_found("Grant match")
    match, view = found[0]
    if match.status == MatchStatus.NOT_ELIGIBLE:
        raise ApiError(
            409,
            "not_eligible",
            "The assessment found this program's criteria are not met, so there is "
            "nothing to draft.",
        )
    labels = await questionnaires.fact_labels(db, project.vertical)
    by_id = {str(f.id): f for f in findings}
    criteria = []
    for c in match.criteria:
        finding = by_id.get(c.get("finding_id") or "")
        criteria.append(
            {
                "finding_id": c.get("finding_id"),
                "title": c["title"],
                "result": c["result"],
                "outcome": c.get("outcome"),
                "detail": finding.detail if finding else None,
                "missing_facts": [labels.get(k, k) for k in c.get("missing_facts", [])],
            }
        )
    facts = [
        {"key": k, "label": labels.get(k, k), "value": _plain(v)}
        for k, v in sorted(assessment.facts_snapshot.items())
        if v not in (None, "", [], {})
    ]
    current = next((r for r in view.rounds if r.round.id == view.current_round_id), None)
    program = view.program
    data: dict[str, Any] = {
        "program": {
            "title": program.title,
            "summary": program.summary,
            "administrator": view.administrator.name,
            "jurisdiction": program.jurisdiction,
            "url": program.url,
            "funding_summary": program.funding_summary,
            "current_round": None
            if current is None
            else {
                "title": current.round.title,
                "state": current.state.state,
                "opens_on": current.round.opens_on.isoformat() if current.round.opens_on else None,
                "closes_on": current.round.closes_on.isoformat()
                if current.round.closes_on
                else None,
            },
        },
        "match_status": match.status,
        "criteria": criteria,
        "applicant_facts": facts,
        "missing_facts": [labels.get(k, k) for k in match.missing_facts],
    }
    refs = {
        "program_id": str(program_id),
        "grant_match_id": str(match.id),
        "finding_ids": [c["finding_id"] for c in criteria if c["finding_id"]],
        "fact_keys": [f["key"] for f in facts],
    }
    return data, refs
