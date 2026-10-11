"""The checklist an assessment leads to: every approval it found, broken into the things to
have ready and the steps to take, with forms, costs, timeframes, fees, contacts and what
commonly goes wrong; then the documents to gather and anything else to do.

One builder serves two places. The free checklist report (``<VERTICAL>_CHECKLIST``
templates) prints it with tick boxes, and a paid project plan (``plans.service``) copies its
steps into a tracker with owners, due dates and uploads. Each step has a ``key`` that stays
the same for the same thing across assessments, so refreshing a plan adds only what's new.

Everything comes from what the assessment stored and from reviewed files in the repository:

* approvals (``approval_requirements``) with their step-by-step guide
  (``guidance/approval_guides.json``) when there is one;
* for PlanningReady, how to apply to the council the answers name (``councils``);
* for GrantReady, the programs matched, what is still unconfirmed and the round dates;
* the project's checklists (vessel, selling and renting checklists), with what is ticked;
* the documents the findings asked for, with what has been provided;
* tasks the findings and reviewers added.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assessments import approval_map
from app.modules.assessments import service as assessments
from app.modules.assessments.models import Assessment, AssessmentFinding
from app.modules.checklists import service as checklists
from app.modules.checklists.models import ItemStatus
from app.modules.councils import directory as councils
from app.modules.documents.service import list_evidence
from app.modules.grants import service as grants
from app.modules.guidance import guides as guidance
from app.modules.projects.models import Project, Task, TaskSource, TaskStatus, Vertical
from app.modules.regulatory.models import SourceReference, VerificationStatus
from app.modules.rules.engine import decode_facts
from app.modules.rules.payload import Certainty, parse_payload

CERTAINTY = {
    Certainty.REQUIRED: "Required",
    Certainty.LIKELY_REQUIRED: "Likely required",
    Certainty.MAY_APPLY: "May apply",
}
GRANT_STATUSES = ("STRONG_MATCH", "POSSIBLE_MATCH", "NEEDS_INFORMATION")
GRANT_STATUS = {
    "STRONG_MATCH": "Meets every criterion we check",
    "POSSIBLE_MATCH": "Might be eligible",
    "NEEDS_INFORMATION": "We need more information",
}


class SectionKind:
    APPROVAL = "APPROVAL"
    COUNCIL = "COUNCIL"
    GRANT = "GRANT"
    CHECKLIST = "CHECKLIST"
    DOCUMENTS = "DOCUMENTS"
    TASKS = "TASKS"


class StepKind:
    PREPARE = "PREPARE"  # something to have ready before starting
    STEP = "STEP"  # a step in the process, in order
    DOCUMENT = "DOCUMENT"  # a document to gather
    TASK = "TASK"  # a task the assessment or a reviewer added
    CHECK = "CHECK"  # an item on one of the project's checklists


@dataclass
class Step:
    key: str
    kind: str
    title: str
    detail: str | None = None
    timeframe: str | None = None
    cost: str | None = None
    link_url: str | None = None
    link_label: str | None = None
    # Already settled elsewhere: a document provided, a checklist item ticked, a task done.
    done: bool = False
    not_applicable: bool = False


@dataclass
class Section:
    key: str
    kind: str
    title: str
    authority: str | None = None
    summary: str | None = None
    certainty_label: str | None = None
    timeframe: str | None = None
    cost_summary: str | None = None
    # Kinds of professional who can help with this part (marketplace category keys).
    category_keys: list[str] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    fees: list[dict[str, str | None]] = field(default_factory=list)
    contacts: list[dict[str, str | None]] = field(default_factory=list)
    watch_out: list[str] = field(default_factory=list)
    sources: list[dict[str, str]] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    # Gathered from official websites on this date; ``verified`` once our team checked it.
    checked_on: str | None = None
    verified: bool = False

    def summary_dict(self) -> dict[str, Any]:
        """The section without its steps (what a plan keeps alongside its items)."""
        return {
            "key": self.key,
            "kind": self.kind,
            "title": self.title,
            "authority": self.authority,
            "summary": self.summary,
            "certainty_label": self.certainty_label,
            "timeframe": self.timeframe,
            "cost_summary": self.cost_summary,
            "category_keys": list(self.category_keys),
            "fees": list(self.fees),
            "contacts": list(self.contacts),
            "watch_out": list(self.watch_out),
            "sources": list(self.sources),
            "gaps": list(self.gaps),
            "checked_on": self.checked_on,
            "verified": self.verified,
        }


@dataclass
class Checklist:
    sections: list[Section]

    @property
    def total(self) -> int:
        return sum(1 for s in self.sections for st in s.steps if not st.not_applicable)

    @property
    def done(self) -> int:
        return sum(1 for s in self.sections for st in s.steps if st.done and not st.not_applicable)

    @property
    def category_keys(self) -> list[str]:
        keys: list[str] = []
        for s in self.sections:
            for k in s.category_keys:
                if k not in keys:
                    keys.append(k)
        return keys


async def verified_sections(db: AsyncSession, sections: list[str]) -> set[str]:
    """Which source-reference sections (one per guide or council entry) a person verified."""
    if not sections:
        return set()
    rows = await db.execute(
        select(SourceReference.section).where(
            SourceReference.section.in_(sections),
            SourceReference.verification_status == VerificationStatus.VERIFIED,
        )
    )
    return {s for s in rows.scalars() if s}


def _guide_section(
    guide: guidance.ApprovalGuide, entry: approval_map.MapEntry, categories: list[str]
) -> Section:
    key = f"approval:{guide.kind}"
    steps = [
        Step(key=f"{key}:ready:{i}", kind=StepKind.PREPARE, title=line)
        for i, line in enumerate(guide.before_you_start, start=1)
    ]
    for i, s in enumerate(guide.steps, start=1):
        link = s.form or None
        steps.append(
            Step(
                key=f"{key}:step:{i}",
                kind=StepKind.STEP,
                title=s.title,
                detail=s.detail,
                timeframe=s.timeframe,
                cost=s.cost,
                link_url=link.url if link else s.url,
                link_label=link.name if link else ("Official page" if s.url else None),
            )
        )
    return Section(
        key=key,
        kind=SectionKind.APPROVAL,
        title=guide.title,
        authority=guide.authority,
        summary=guide.summary,
        certainty_label=CERTAINTY.get(entry.certainty),
        timeframe=guide.timeframe,
        cost_summary=guide.cost_summary,
        category_keys=categories,
        steps=steps,
        fees=[{"label": f.label, "amount": f.amount, "note": f.note} for f in guide.fees],
        contacts=[
            {
                "name": c.name,
                "phone": c.phone,
                "email": c.email,
                "url": c.url,
                "hours": c.hours,
                "note": c.note,
            }
            for c in guide.contacts
        ],
        watch_out=list(guide.watch_out),
        sources=[{"title": s.title, "url": s.url} for s in guide.sources],
        gaps=list(guide.gaps),
        checked_on=guide.checked_on.isoformat(),
    )


def _bare_section(entry: approval_map.MapEntry, categories: list[str]) -> Section:
    """An approval without a step-by-step guide yet: what the assessment says about it."""
    key = f"approval:{entry.kind}"
    who = entry.authority or "the authority that decides it"
    detail = f"Apply to {who}" + (f" ({entry.pathway})." if entry.pathway else ".")
    return Section(
        key=key,
        kind=SectionKind.APPROVAL,
        title=entry.title,
        authority=entry.authority,
        summary=entry.pathway,
        certainty_label=CERTAINTY.get(entry.certainty),
        category_keys=categories,
        steps=[
            Step(
                key=f"{key}:confirm",
                kind=StepKind.STEP,
                title=f"Confirm with {who} that this applies and what they need",
            ),
            Step(key=f"{key}:apply", kind=StepKind.STEP, title="Apply", detail=detail),
        ],
    )


def _council_section(council: councils.Council, categories: list[str]) -> Section:
    key = f"council:{council.key}"
    steps: list[Step] = []
    pre = council.pre_lodgement
    if pre is not None and pre.available:
        steps.append(
            Step(
                key=f"{key}:prelodgement",
                kind=StepKind.PREPARE,
                title="Book a pre-lodgement meeting with council",
                detail=pre.note,
                link_url=pre.url,
                link_label="How to book" if pre.url else None,
            )
        )
    if council.planning_scheme is not None and council.planning_scheme.name:
        steps.append(
            Step(
                key=f"{key}:scheme",
                kind=StepKind.PREPARE,
                title=f"Check your plans against the {council.planning_scheme.name}",
                link_url=council.planning_scheme.url,
                link_label="Planning scheme" if council.planning_scheme.url else None,
            )
        )
    for i, line in enumerate(council.steps, start=1):
        steps.append(Step(key=f"{key}:step:{i}", kind=StepKind.STEP, title=line))
    if council.lodgement:
        ways = council.lodgement
        first = next((w for w in ways if w.url), None)
        steps.append(
            Step(
                key=f"{key}:lodge",
                kind=StepKind.STEP,
                title="Lodge your application with council",
                detail="; ".join(w.label + (f" ({w.email})" if w.email else "") for w in ways),
                link_url=first.url if first else None,
                link_label=first.label if first else None,
            )
        )
    else:
        steps.append(
            Step(
                key=f"{key}:lodge",
                kind=StepKind.STEP,
                title="Ask council how to lodge your application",
                detail=council.contact.phone,
                link_url=council.planning_url or council.website,
                link_label="Council planning page" if council.planning_url else None,
            )
        )
    fees = []
    if council.fees is not None:
        fees = [{"label": f.label, "amount": f.amount, "note": f.note} for f in council.fees.items]
    contact = council.contact
    return Section(
        key=key,
        kind=SectionKind.COUNCIL,
        title=f"Apply to {council.name}",
        authority=council.name,
        summary="How this council takes development applications, from its own website.",
        category_keys=categories,
        steps=steps,
        fees=fees,
        contacts=[
            {
                "name": council.name,
                "phone": contact.phone,
                "email": contact.email,
                "url": council.planning_url or council.website,
                "hours": contact.hours,
                "note": contact.address,
            }
        ],
        sources=[{"title": s.title, "url": s.url} for s in council.sources],
        gaps=list(council.gaps),
        checked_on=council.checked_on.isoformat(),
    )


def _date(value: Any) -> str | None:
    return value.strftime("%-d %B %Y") if value else None


async def _grant_sections(db: AsyncSession, assessment: Assessment) -> list[Section]:
    out = []
    for match, view in await grants.matches_for(db, assessment.id):
        if match.status not in GRANT_STATUSES:
            continue
        program = view.program
        key = f"grant:{program.id}"
        steps = [
            Step(
                key=f"{key}:confirm:{i}",
                kind=StepKind.PREPARE,
                title=f"Confirm: {c['title']}",
                detail="Not answered yet, so we couldn't check it.",
            )
            for i, c in enumerate(match.criteria, start=1)
            if c.get("result") == "UNKNOWN"
        ]
        current = next((r for r in view.rounds if r.round.id == view.current_round_id), None)
        if current is not None:
            closes = _date(current.round.closes_on)
            steps.append(
                Step(
                    key=f"{key}:round",
                    kind=StepKind.STEP,
                    title=f"Check the round dates: {current.round.title}",
                    detail=(f"Closes {closes}. " if closes else "")
                    + (current.round.dates_note or ""),
                    link_url=current.document.url,
                    link_label="Round details",
                )
            )
        steps += [
            Step(
                key=f"{key}:guidelines",
                kind=StepKind.STEP,
                title="Read the program guidelines and eligibility rules in full",
                link_url=program.url,
                link_label="Program page" if program.url else None,
            ),
            Step(
                key=f"{key}:apply",
                kind=StepKind.STEP,
                title="Prepare and submit your application before the round closes",
                detail=program.funding_summary,
            ),
        ]
        out.append(
            Section(
                key=key,
                kind=SectionKind.GRANT,
                title=program.title,
                authority=view.administrator.name,
                summary=program.summary,
                certainty_label=GRANT_STATUS[match.status],
                category_keys=["grant_writer"],
                steps=steps,
            )
        )
    return out


async def build(
    db: AsyncSession,
    assessment: Assessment,
    project: Project,
    findings: list[AssessmentFinding],
) -> Checklist:
    """The checklist for an assessment, in the order to work through it. Bind the project's
    organisation first."""
    vertical = Vertical(project.vertical)
    approvals, evidence = await assessments.requirements(db, assessment)
    by_finding = {f.id: f for f in findings}

    def categories_for(finding_ids: list[uuid.UUID]) -> list[str]:
        keys: list[str] = []
        for fid in finding_ids:
            f = by_finding.get(fid)
            if f is None or f.payload is None:
                continue
            for key in parse_payload(f.payload).referral_categories:
                if key not in keys:
                    keys.append(key)
        return keys

    every_category = categories_for([f.id for f in findings])
    entries = [e for e in approval_map.build(approvals) if e.certainty != Certainty.NOT_IDENTIFIED]
    found = {g.kind: g for g in guidance.for_kinds([e.kind for e in entries], vertical)}
    guided = sorted(
        (e for e in entries if e.kind in found), key=lambda e: (found[e.kind].order, e.title)
    )
    sections = [_guide_section(found[e.kind], e, categories_for(e.finding_ids)) for e in guided]
    sections += [
        _bare_section(e, categories_for(e.finding_ids)) for e in entries if e.kind not in found
    ]

    facts = decode_facts(assessment.facts_snapshot)
    if vertical == Vertical.PLANNING:
        lga = facts.get("property.lga")
        council = councils.by_key(lga) if isinstance(lga, str) else None
        if council is not None:
            sections.append(_council_section(council, every_category))
    if vertical == Vertical.GRANT:
        sections += await _grant_sections(db, assessment)

    for view in await checklists.list_for_project(db, project):
        c = view.checklist
        sections.append(
            Section(
                key=f"checklist:{c.checklist_key}",
                kind=SectionKind.CHECKLIST,
                title=c.title,
                summary=c.description,
                steps=[
                    Step(
                        key=f"checklist:{c.checklist_key}:{i.item_key}",
                        kind=StepKind.CHECK,
                        title=i.title,
                        detail=i.detail,
                        done=i.status == ItemStatus.DONE,
                        not_applicable=i.status == ItemStatus.NOT_APPLICABLE,
                    )
                    for i in view.items
                ],
                sources=[
                    {"title": f"{s['title']}, {s['organisation']}", "url": s.get("url") or ""}
                    for s in c.sources
                ],
            )
        )

    if evidence:
        provided: dict[uuid.UUID, list[str]] = {}
        for row in await list_evidence(db, assessment):
            provided.setdefault(row.evidence.evidence_requirement_id, []).append(
                row.document.original_filename
            )
        seen: set[str] = set()
        steps = []
        for e in evidence:
            key = f"document:{e.kind}:{e.title}"[:200]
            if key in seen:
                continue
            seen.add(key)
            files = provided.get(e.id, [])
            steps.append(
                Step(
                    key=key,
                    kind=StepKind.DOCUMENT,
                    title=e.title,
                    detail=e.detail,
                    done=bool(files),
                    link_label=", ".join(files) if files else None,
                )
            )
        sections.append(
            Section(
                key="documents",
                kind=SectionKind.DOCUMENTS,
                title="Documents to gather",
                summary="What the findings asked you to show. Upload each one to the project.",
                steps=steps,
            )
        )

    tasks = list(
        (
            await db.execute(
                select(Task)
                .where(
                    Task.project_id == project.id,
                    Task.deleted_at.is_(None),
                    Task.source.in_([TaskSource.RULE, TaskSource.REVIEWER]),
                    Task.status != TaskStatus.CANCELLED,
                )
                .order_by(Task.created_at, Task.id)
            )
        ).scalars()
    )
    if tasks:
        sections.append(
            Section(
                key="tasks",
                kind=SectionKind.TASKS,
                title="Other things to do",
                summary="Tasks your assessment or your reviewer added to the project.",
                steps=[
                    Step(
                        key=f"task:{t.id}",
                        kind=StepKind.TASK,
                        title=t.title,
                        detail=t.notes,
                        done=t.status == TaskStatus.DONE,
                    )
                    for t in tasks
                ],
            )
        )

    checked = await verified_sections(
        db,
        [found[e.kind].reference_section for e in guided]
        + [
            f"Council directory: {s.key.removeprefix('council:')}"
            for s in sections
            if s.kind == SectionKind.COUNCIL
        ],
    )
    for s in sections:
        if s.kind == SectionKind.APPROVAL and s.key.removeprefix("approval:") in found:
            s.verified = found[s.key.removeprefix("approval:")].reference_section in checked
        elif s.kind == SectionKind.COUNCIL:
            s.verified = f"Council directory: {s.key.removeprefix('council:')}" in checked
    return Checklist(sections)
