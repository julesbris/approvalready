"""Content packs: reviewed JSON files of sources and rules, loaded by staff on purpose.

A pack (``app/modules/rules/packs/<name>.json``) holds source organisations, documents and
references, and rule sets with their rules. ``python -m app.cli rules load-pack <name>``
creates whatever does not exist yet through the normal services, so every row is audited
under the staff member running it, exactly as if they had typed it into the admin screens.

Loading never changes anything that already exists: a source organisation is matched by
name, a document by URL, a reference by document and section, a rule set by key and a rule
by key within its set. Edits after loading happen in the admin screens (and a changed rule
there is a new version, as always).

References are created ``UNVERIFIED`` and without snapshots: a person has to capture the
source and verify each reference before any finding can be ``VERIFIED``. Rules are created
as drafts unless ``--publish`` is given, in which case each one goes through the publish
gate like any other draft (and stays a draft if it fails).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.regulatory import service as regulatory
from app.modules.regulatory.models import SourceDocument, SourceOrganisation, SourceReference
from app.modules.regulatory.schemas import (
    SourceDocumentCreate,
    SourceOrganisationCreate,
    SourceReferenceCreate,
)
from app.modules.regulatory.service import Actor
from app.modules.rules import service
from app.modules.rules.models import Rule, RuleSet, SourceRelationship
from app.modules.rules.schemas import (
    OutcomeIn,
    RuleSetCreate,
    RuleVersionContent,
    TestCaseIn,
    Title,
)

PACKS_DIR = Path(__file__).parent / "packs"

Ref = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,59}$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PackOrganisation(SourceOrganisationCreate):
    ref: Ref


class PackDocument(SourceDocumentCreate):
    source_organisation_id: None = None  # type: ignore[assignment]
    ref: Ref
    organisation: Ref


class PackReference(SourceReferenceCreate):
    ref: Ref
    document: Ref


class PackRuleSource(_Strict):
    reference: Ref
    relationship: SourceRelationship = SourceRelationship.BASIS


class PackRule(_Strict):
    key: str
    title: Title
    condition: dict[str, object]
    effective_from: str
    max_confidence: str = "LIKELY"
    notes: str | None = None
    outcomes: list[OutcomeIn]
    sources: list[PackRuleSource]
    test_cases: list[TestCaseIn]


class PackRuleSet(RuleSetCreate):
    rules: list[PackRule]


class Pack(_Strict):
    key: str
    title: str
    notes: str
    organisations: list[PackOrganisation]
    documents: list[PackDocument]
    references: list[PackReference]
    rule_sets: list[PackRuleSet]

    @model_validator(mode="after")
    def _refs_resolve(self) -> Pack:
        problems: list[str] = []
        for kind, items in (
            ("organisation", [o.ref for o in self.organisations]),
            ("document", [d.ref for d in self.documents]),
            ("reference", [r.ref for r in self.references]),
        ):
            if len(set(items)) != len(items):
                problems.append(f"duplicate {kind} ref")
        orgs = {o.ref for o in self.organisations}
        docs = {d.ref for d in self.documents}
        refs = {r.ref for r in self.references}
        problems += [
            f"document {d.ref}: no organisation {d.organisation}"
            for d in self.documents
            if d.organisation not in orgs
        ]
        problems += [
            f"reference {r.ref}: no document {r.document}"
            for r in self.references
            if r.document not in docs
        ]
        problems += [
            f"rule {rs.key}.{rule.key}: no reference {s.reference}"
            for rs in self.rule_sets
            for rule in rs.rules
            for s in rule.sources
            if s.reference not in refs
        ]
        if problems:
            raise ValueError("; ".join(problems))
        return self


def available() -> list[str]:
    return sorted(p.stem for p in PACKS_DIR.glob("*.json"))


def load_file(name: str) -> Pack:
    path = PACKS_DIR / f"{name}.json"
    if not path.is_file() or name not in available():
        raise FileNotFoundError(f"No content pack named {name!r}. Available: {available()}")
    return Pack.model_validate(json.loads(path.read_text(encoding="utf-8")))


@dataclass
class LoadReport:
    created: list[str] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)
    published: list[str] = field(default_factory=list)
    not_published: list[str] = field(default_factory=list)  # with the gate's reasons
    warnings: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        out = [f"created: {c}" for c in self.created]
        out += [f"already there (left unchanged): {e}" for e in self.existing]
        out += [f"published: {p}" for p in self.published]
        out += [f"NOT published: {n}" for n in self.not_published]
        out += [f"warning: {w}" for w in self.warnings]
        return out


async def load(db: AsyncSession, pack: Pack, actor: Actor, *, publish: bool) -> LoadReport:
    report = LoadReport()

    org_ids = {}
    for o in pack.organisations:
        found = (
            await db.execute(select(SourceOrganisation).where(SourceOrganisation.name == o.name))
        ).scalar_one_or_none()
        if found is None:
            found = await regulatory.create_organisation(db, o.model_dump(exclude={"ref"}), actor)
            report.created.append(f"source organisation {o.name}")
        else:
            report.existing.append(f"source organisation {o.name}")
        org_ids[o.ref] = found.id

    docs = {}
    for d in pack.documents:
        doc = (
            (await db.execute(select(SourceDocument).where(SourceDocument.url == d.url)))
            .scalars()
            .first()
        )
        if doc is None:
            data = d.model_dump(exclude={"ref", "organisation"})
            data["source_organisation_id"] = org_ids[d.organisation]
            doc = await regulatory.create_document(db, data, actor)
            report.created.append(f"source document {d.title}")
        else:
            report.existing.append(f"source document {d.title}")
        docs[d.ref] = doc

    ref_ids = {}
    for r in pack.references:
        doc = docs[r.document]
        found_ref = (
            (
                await db.execute(
                    select(SourceReference).where(
                        SourceReference.source_document_id == doc.id,
                        SourceReference.section.is_not_distinct_from(r.section),
                        SourceReference.clause.is_not_distinct_from(r.clause),
                    )
                )
            )
            .scalars()
            .first()
        )
        label = f"reference {doc.title}, {r.section or r.clause or r.ref}"
        if found_ref is None:
            found_ref = await regulatory.create_reference(
                db, doc, r.model_dump(exclude={"ref", "document"}), actor
            )
            report.created.append(label)
        else:
            report.existing.append(label)
        ref_ids[r.ref] = found_ref.id

    for rs in pack.rule_sets:
        rule_set = (
            await db.execute(select(RuleSet).where(RuleSet.key == rs.key))
        ).scalar_one_or_none()
        if rule_set is None:
            rule_set = await service.create_rule_set(
                db, rs.model_dump(exclude={"rules"}, mode="json"), actor
            )
            report.created.append(f"rule set {rs.key}")
        else:
            report.existing.append(f"rule set {rs.key}")
        for pr in rs.rules:
            name = f"rule {rs.key}.{pr.key}"
            taken = (
                await db.execute(
                    select(Rule.id).where(Rule.rule_set_id == rule_set.id, Rule.key == pr.key)
                )
            ).first()
            if taken:
                report.existing.append(name)
                continue
            _, version = await service.create_rule(
                db, rule_set, {"key": pr.key, "title": pr.title, "condition": pr.condition}, actor
            )
            content = RuleVersionContent.model_validate(
                {
                    "condition": pr.condition,
                    "effective_from": pr.effective_from,
                    "max_confidence": pr.max_confidence,
                    "notes": pr.notes,
                    "outcomes": [o.model_dump(mode="json") for o in pr.outcomes],
                    "sources": [
                        {
                            "source_reference_id": str(ref_ids[s.reference]),
                            "relationship": s.relationship,
                        }
                        for s in pr.sources
                    ],
                    "test_cases": [t.model_dump(mode="json") for t in pr.test_cases],
                }
            )
            await service.save_draft(db, version, content.model_dump(), actor)
            report.created.append(f"{name} (draft)")
            if not publish:
                continue
            view = await service.get_version(db, version.id)
            gate = await service.publish_checks(db, view)
            report.warnings += [f"{name}: {w}" for w in gate.warnings]
            if gate.ready:
                await service.publish(db, view, actor)
                report.published.append(name)
            else:
                reasons = "; ".join(m for _, passed, m in gate.checks if not passed)
                report.not_published.append(f"{name}: {reasons}")
    return report
