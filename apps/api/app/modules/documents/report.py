"""Building a generated report: plain data from an assessment, rendered by its template.

The context holds only what the assessment stored (findings, requirements, cited sources
as they stood on the assessment date, the facts it used), so a report says nothing the
assessment did not. Labels match the web report.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assessments import approval_map
from app.modules.assessments import service as assessments
from app.modules.assessments.models import AssessmentFinding
from app.modules.documents import render
from app.modules.documents.models import (
    DocumentTemplate,
    DocumentTemplateVersion,
    GeneratedDocument,
    OutputFormat,
)
from app.modules.documents.service import list_evidence
from app.modules.marketplace import service as marketplace
from app.modules.questionnaires import service as questionnaires
from app.modules.review import professionals
from app.modules.review import service as review
from app.modules.rules.engine import decode_facts
from app.modules.rules.payload import parse_payload

BRISBANE = ZoneInfo("Australia/Brisbane")

CONFIDENCE = {
    "VERIFIED": "Verified",
    "LIKELY": "Likely",
    "REVIEW_REQUIRED": "Needs professional review",
    "UNKNOWN": "Not enough information",
}
OUTCOMES = {
    "APPROVAL_REQUIRED": "Approval required",
    "APPROVAL_LIKELY": "Approval likely required",
    "NOT_REQUIRED": "Not required",
    "EVIDENCE_REQUIRED": "Evidence needed",
    "PROFESSIONAL_REQUIRED": "Professional needed",
    "REFERRAL_CATEGORY": "Specialist help",
    "CROSS_SELL": "Related",
    "WARNING": "Warning",
    "INFO": "Information",
}
RESULTS = {"MATCH": "Applies", "NO_MATCH": "Does not apply", "UNKNOWN": "Unknown"}
CERTAINTY = {
    "REQUIRED": "Required",
    "LIKELY_REQUIRED": "Likely required",
    "MAY_APPLY": "May apply",
    "NOT_IDENTIFIED": "Not identified",
}
VERIFICATION = {
    "UNVERIFIED": "not yet verified",
    "VERIFIED": "verified",
    "DISPUTED": "disputed",
    "SUPERSEDED": "superseded",
}
PROJECT_STATUS = {
    "DRAFT": "Draft",
    "IN_PROGRESS": "In progress",
    "ASSESSED": "Assessed",
    "IN_REVIEW": "In review",
    "COMPLETED": "Completed",
    "ARCHIVED": "Archived",
}
REVIEW_STATUS = {
    "NOT_REVIEWED": (
        "Not reviewed by a professional",
        "No qualified professional has checked this report. Results marked as needing "
        "review should be confirmed before you rely on them.",
    ),
    "IN_REVIEW": (
        "Professional review in progress",
        "A qualified professional is reviewing this assessment. Results may change when "
        "they finish.",
    ),
    "CHANGES_REQUIRED": (
        "Changes requested by the reviewer",
        "The professional reviewing this assessment asked for changes before they can "
        "finish. Their notes are below.",
    ),
    "APPROVED": (
        "Reviewed and approved by a professional",
        "A qualified professional reviewed this assessment and approved it, including any "
        "changes they made below. It is still not a council decision.",
    ),
    "REVIEWED": (
        "Reviewed by a professional, not approved",
        "A qualified professional reviewed this assessment but did not approve it as it "
        "stands. Read their notes before relying on it.",
    ),
}
DISCIPLINES = {
    "TOWN_PLANNER": "Town planner",
    "SURVEYOR": "Surveyor",
    "BUILDING_CERTIFIER": "Building certifier",
    "BUILDING_DESIGNER": "Building designer",
    "ENGINEER": "Engineer",
    "MARINE_SURVEYOR": "Marine surveyor",
    "LAWYER": "Lawyer",
    "ACCOUNTANT": "Accountant",
    "GRANT_WRITER": "Grant writer",
    "OTHER": "Professional",
}


def _format_value(value: Any) -> str:
    if value is None:
        return "Not answered"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, date):
        return value.strftime("%-d %B %Y")
    if isinstance(value, list):
        if value and all(isinstance(v, str) and len(v) == 36 for v in value):
            return f"{len(value)} file{'' if len(value) == 1 else 's'} uploaded"
        return ", ".join(_format_value(v) for v in value)
    if isinstance(value, dict):
        return ", ".join(_format_value(v) for v in value.values() if v not in (None, ""))
    return str(value)


def _finding(f: AssessmentFinding, override: review.OverrideRow | None) -> dict[str, Any]:
    """A finding as the customer should read it: with the reviewer's change, if any, and
    the original kept in the reasons."""
    outcome, confidence = f.outcome_type, f.confidence
    reasons = list(f.confidence_reasons)
    if override is not None:
        outcome, confidence = override.override.new_outcome_type, override.override.new_confidence
        reasons.insert(
            0,
            f"Changed by the professional reviewer (was "
            f"{OUTCOMES.get(f.outcome_type or '', 'No outcome')}, "
            f"{CONFIDENCE.get(f.confidence, f.confidence)}): {override.override.reason}",
        )
    return {
        "rule_title": f.rule_title,
        "title": f.title,
        "detail": f.detail,
        "outcome_label": OUTCOMES.get(outcome or "", "No outcome"),
        "result_label": RESULTS.get(f.result, f.result),
        "confidence_label": CONFIDENCE.get(confidence, confidence),
        "confidence_reasons": reasons,
        "citations": [s["citation"] for s in f.sources],
    }


async def build_context(
    db: AsyncSession, generated: GeneratedDocument, version: DocumentTemplateVersion
) -> dict[str, Any]:
    assert generated.assessment_id is not None
    assessment, project, findings = await assessments.get(
        db, generated.organisation_id, generated.assessment_id
    )
    template = await db.get(DocumentTemplate, version.template_id)
    assert template is not None
    approvals, evidence_requirements = await assessments.requirements(db, assessment)
    provided: dict[Any, list[str]] = {}
    for row in await list_evidence(db, assessment):
        provided.setdefault(row.evidence.evidence_requirement_id, []).append(
            row.document.original_filename
        )
    labels = await questionnaires.fact_labels(db, project.vertical)
    facts = decode_facts(assessment.facts_snapshot)

    sources: dict[str, dict[str, Any]] = {}
    for f in findings:
        for s in f.sources:
            sources.setdefault(
                s["reference_id"],
                {
                    "citation": s["citation"],
                    "document_title": s["document_title"],
                    "organisation_name": s["organisation_name"],
                    "url": s["url"],
                    "verification": VERIFICATION.get(s["verification_status"], "unknown"),
                    "in_force": s["in_force"],
                },
            )
    missing: dict[str, None] = {}
    for f in findings:
        for fact in f.missing_facts:
            missing.setdefault(labels.get(fact, fact), None)
    for rs in assessment.rule_sets:
        for fact in rs.get("missing_facts", []):
            missing.setdefault(labels.get(fact, fact), None)
    limitations: dict[str, None] = {}
    for rs in assessment.rule_sets:
        if rs.get("scope") != "OUT_OF_SCOPE":
            for text in rs.get("limitations", []):
                limitations.setdefault(text, None)
    referral_keys: dict[str, None] = {}
    for f in findings:
        for key in parse_payload(f.payload).referral_categories:
            referral_keys.setdefault(key, None)
    referral_labels = await marketplace.labels(db, referral_keys)

    review_status, review_request, decision = await review.review_status_for(db, assessment)
    generated.review_status = review_status
    review_label, review_detail = REVIEW_STATUS[review_status]
    reviewer = None
    if review_request is not None and review_request.assigned_professional_id is not None:
        v = await professionals.view(
            db, await professionals.get_professional(db, review_request.assigned_professional_id)
        )
        discipline = DISCIPLINES.get(v.professional.discipline, "Professional")
        reviewer = f"{v.professional.display_name}, {discipline}, {v.practice.name}"
    overridden = review.current_overrides(
        await review.overrides_for_findings(db, [f.id for f in findings])
    )

    def _label(outcome: str | None, confidence: str) -> str:
        outcome_label = OUTCOMES.get(outcome or "", "No outcome")
        return f"{outcome_label} ({CONFIDENCE.get(confidence, confidence)})"

    changes = [
        {
            "finding": f.title or f.rule_title,
            "before": _label(f.outcome_type, f.confidence),
            "after": _label(o.override.new_outcome_type, o.override.new_confidence),
            "reason": o.override.reason,
            "source": o.citation,
        }
        for f in findings
        if (o := overridden.get(f.id)) is not None
    ]
    generated_at = datetime.now(BRISBANE)
    return {
        "meta": {
            "title": template.title,
            "project_title": project.title,
            "project_reference": project.reference_code,
            "project_status": PROJECT_STATUS.get(project.status, project.status),
            "assessed_on": assessment.assessed_on.strftime("%-d %B %Y"),
            "generated_at": generated_at.strftime("%-d %B %Y, %-I:%M %p") + " Brisbane time",
            "document_id": str(generated.id),
            "template_key": template.key,
            "template_version": version.version,
            "engine_version": assessment.engine_version,
            "facts_hash": assessment.facts_hash.hex()[:16],
            "review_status": review_label,
            "review_status_detail": review_detail,
        },
        "review": {
            "reviewer": reviewer,
            "decided_on": decision.created_at.astimezone(BRISBANE).strftime("%-d %B %Y")
            if decision
            else None,
            "notes": decision.notes if decision else None,
            "changes": changes,
        },
        "assessment": {
            "status": assessment.status,
            "overall_confidence_label": CONFIDENCE.get(assessment.overall_confidence, "Unknown"),
        },
        "rule_sets_in_scope": [
            rs["title"] for rs in assessment.rule_sets if rs.get("scope") == "IN_SCOPE"
        ],
        "findings": [_finding(f, overridden.get(f.id)) for f in findings],
        "approvals": [
            {
                "title": a.title,
                "certainty_label": CERTAINTY.get(a.certainty, a.certainty),
                "confidence_label": CONFIDENCE.get(a.confidence, a.confidence),
                "authority": a.authority,
                "pathway": a.pathway,
            }
            for a in approvals
        ],
        "evidence": [
            {"title": e.title, "detail": e.detail, "documents": provided.get(e.id, [])}
            for e in evidence_requirements
        ],
        "approval_map": [
            {
                "certainty_label": CERTAINTY[column],
                "approvals": [
                    {
                        "title": e.title,
                        "confidence_label": CONFIDENCE.get(e.confidence, e.confidence),
                        "authority": e.authority,
                        "pathway": e.pathway,
                    }
                    for e in entries
                    if e.certainty == column
                ],
            }
            for entries in [approval_map.build(approvals)]
            for column in approval_map.COLUMNS
        ],
        "referrals": [referral_labels[k] for k in referral_keys],
        "assumptions": [
            {"label": labels[key], "value": _format_value(facts[key])}
            for key in labels
            if key in facts
        ],
        "missing": list(missing),
        "sources": list(sources.values()),
        "limitations": list(limitations),
    }


async def render_document(db: AsyncSession, generated: GeneratedDocument) -> bytes:
    """The finished file, in the requested format."""
    version = await db.get(DocumentTemplateVersion, generated.template_version_id)
    assert version is not None
    context = await build_context(db, generated, version)
    html = render.render_html(version.body, context)
    match generated.format:
        case OutputFormat.PDF:
            content = await asyncio.to_thread(render.html_to_pdf, html)
        case OutputFormat.DOCX:
            title = f"{context['meta']['title']} - {context['meta']['project_reference']}"
            content = await asyncio.to_thread(render.html_to_docx, html, title=title)
        case _:
            content = html.encode("utf-8")
    return content
