"""Authoring, testing and publishing rules; loading published rules for assessments.

Lifecycle of a rule version: a draft is edited freely (``save_draft`` replaces its whole
content), checked by the publish gate, then published by someone with ``rule.publish``.
Publishing retires the rule's previous published version. Published and retired versions
never change (database triggers); a fix is a new version, copied from the latest one.

The publish gate (``publish_checks``) blocks publishing unless the condition is valid, the
version has an effective date and at least one outcome, it cites at least one ``BASIS``
source, none of its sources is disputed or superseded, and it has test cases that all pass.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from fastapi import status
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, not_found
from app.modules.audit import service as audit
from app.modules.conditions import parse_condition, referenced_facts
from app.modules.conditions.ast import FACT_PATTERN, dump_condition
from app.modules.questionnaires import service as questionnaires
from app.modules.regulatory import service as regulatory
from app.modules.regulatory.models import (
    SourceDocument,
    SourceOrganisation,
    SourceReference,
    VerificationStatus,
)
from app.modules.regulatory.service import Actor
from app.modules.rules import engine
from app.modules.rules.models import (
    Confidence,
    Rule,
    RuleFactDependency,
    RuleOutcome,
    RuleSet,
    RuleSource,
    RuleTestCase,
    RuleVersion,
    RuleVersionStatus,
    SourceRelationship,
)

S = RuleVersionStatus


def utcnow() -> datetime:
    return datetime.now(UTC)


def _invalid(code: str, message: str, fields: dict[str, str] | None = None) -> ApiError:
    return ApiError(status.HTTP_422_UNPROCESSABLE_CONTENT, code, message, fields=fields)


def _conflict(code: str, message: str, fields: dict[str, str] | None = None) -> ApiError:
    return ApiError(status.HTTP_409_CONFLICT, code, message, fields=fields)


def validated_condition(document: dict[str, Any], field: str = "condition") -> dict[str, Any]:
    """Parse a condition AST and return its normalised JSON, or a 422 naming the field."""
    try:
        return dump_condition(parse_condition(document))
    except (ValidationError, ValueError) as exc:
        message = (
            exc.errors()[0]["msg"] if isinstance(exc, ValidationError) else str(exc)
        ).removeprefix("Value error, ")
        raise _invalid(
            "invalid_condition", "The condition is not valid.", fields={field: message}
        ) from exc


async def _audit(
    db: AsyncSession,
    action: str,
    actor: Actor,
    target_type: str,
    target_id: uuid.UUID,
    **details: Any,
) -> None:
    await audit.record(
        db,
        action,
        actor_user_id=actor.user_id,
        organisation_id=actor.organisation_id,
        target_type=target_type,
        target_id=target_id,
        meta=actor.meta,
        details=details or None,
    )


# --- Rule sets -------------------------------------------------------------------------


async def list_rule_sets(db: AsyncSession, vertical: str | None = None) -> list[RuleSet]:
    stmt = select(RuleSet).order_by(RuleSet.vertical, RuleSet.key)
    if vertical is not None:
        stmt = stmt.where(RuleSet.vertical == vertical)
    return list((await db.execute(stmt)).scalars())


async def get_rule_set(db: AsyncSession, rule_set_id: uuid.UUID) -> RuleSet:
    found = await db.get(RuleSet, rule_set_id)
    if found is None:
        raise not_found("Rule set")
    return found


async def create_rule_set(db: AsyncSession, data: dict[str, Any], actor: Actor) -> RuleSet:
    if (await db.execute(select(RuleSet.id).where(RuleSet.key == data["key"]))).first():
        raise _conflict("key_taken", "A rule set with that key already exists.")
    if data.get("applies_when") is not None:
        data["applies_when"] = validated_condition(data["applies_when"], "applies_when")
    rule_set = RuleSet(created_by=actor.user_id, **data)
    db.add(rule_set)
    await db.flush()
    await _audit(db, "rule.set_created", actor, "rule_set", rule_set.id, key=rule_set.key)
    return rule_set


async def update_rule_set(
    db: AsyncSession, rule_set: RuleSet, changes: dict[str, Any], actor: Actor
) -> RuleSet:
    changes = {
        k: v for k, v in changes.items() if v is not None or k in ("description", "applies_when")
    }
    if changes.get("applies_when") is not None:
        changes["applies_when"] = validated_condition(changes["applies_when"], "applies_when")
    applied = sorted(k for k, v in changes.items() if getattr(rule_set, k) != v)
    for key in applied:
        setattr(rule_set, key, changes[key])
    if applied:
        await db.flush()
        await _audit(db, "rule.set_updated", actor, "rule_set", rule_set.id, fields=applied)
    return rule_set


@dataclass(frozen=True)
class RuleRow:
    rule: Rule
    published: RuleVersion | None
    draft: RuleVersion | None
    latest_version: int


async def rules_of(db: AsyncSession, rule_set: RuleSet) -> list[RuleRow]:
    rules = list(
        (
            await db.execute(select(Rule).where(Rule.rule_set_id == rule_set.id).order_by(Rule.key))
        ).scalars()
    )
    versions: dict[uuid.UUID, list[RuleVersion]] = defaultdict(list)
    if rules:
        for v in (
            await db.execute(
                select(RuleVersion)
                .where(RuleVersion.rule_id.in_([r.id for r in rules]))
                .order_by(RuleVersion.version)
            )
        ).scalars():
            versions[v.rule_id].append(v)
    return [
        RuleRow(
            rule=r,
            published=next((v for v in versions[r.id] if v.status == S.PUBLISHED), None),
            draft=next((v for v in versions[r.id] if v.status == S.DRAFT), None),
            latest_version=max((v.version for v in versions[r.id]), default=0),
        )
        for r in rules
    ]


# --- Rules and versions ----------------------------------------------------------------


async def get_rule(db: AsyncSession, rule_id: uuid.UUID) -> tuple[Rule, RuleSet]:
    row = (
        await db.execute(
            select(Rule, RuleSet)
            .join(RuleSet, RuleSet.id == Rule.rule_set_id)
            .where(Rule.id == rule_id)
        )
    ).one_or_none()
    if row is None:
        raise not_found("Rule")
    return row[0], row[1]


async def versions_of(db: AsyncSession, rule: Rule) -> list[RuleVersion]:
    return list(
        (
            await db.execute(
                select(RuleVersion)
                .where(RuleVersion.rule_id == rule.id)
                .order_by(RuleVersion.version)
            )
        ).scalars()
    )


async def create_rule(
    db: AsyncSession, rule_set: RuleSet, data: dict[str, Any], actor: Actor
) -> tuple[Rule, RuleVersion]:
    condition = validated_condition(data["condition"])
    taken = await db.execute(
        select(Rule.id).where(Rule.rule_set_id == rule_set.id, Rule.key == data["key"])
    )
    if taken.first():
        raise _conflict("key_taken", "This rule set already has a rule with that key.")
    rule = Rule(
        rule_set_id=rule_set.id, key=data["key"], title=data["title"], created_by=actor.user_id
    )
    db.add(rule)
    await db.flush()
    version = RuleVersion(rule_id=rule.id, version=1, condition=condition, created_by=actor.user_id)
    db.add(version)
    await db.flush()
    await _set_dependencies(db, version)
    await _audit(db, "rule.created", actor, "rule", rule.id, key=rule.key, rule_set=rule_set.key)
    return rule, version


async def rename_rule(db: AsyncSession, rule: Rule, title: str, actor: Actor) -> Rule:
    if rule.title != title:
        rule.title = title
        await db.flush()
        await _audit(db, "rule.updated", actor, "rule", rule.id, fields=["title"])
    return rule


@dataclass(frozen=True)
class VersionView:
    version: RuleVersion
    rule: Rule
    rule_set: RuleSet
    outcomes: list[RuleOutcome]
    sources: list[tuple[RuleSource, regulatory.ReferenceView]]
    test_cases: list[RuleTestCase]
    fact_paths: list[str]


async def get_version(db: AsyncSession, version_id: uuid.UUID) -> VersionView:
    row = (
        await db.execute(
            select(RuleVersion, Rule, RuleSet)
            .join(Rule, Rule.id == RuleVersion.rule_id)
            .join(RuleSet, RuleSet.id == Rule.rule_set_id)
            .where(RuleVersion.id == version_id)
        )
    ).one_or_none()
    if row is None:
        raise not_found("Rule version")
    version, rule, rule_set = row
    outcomes = list(
        (
            await db.execute(
                select(RuleOutcome)
                .where(RuleOutcome.rule_version_id == version.id)
                .order_by(RuleOutcome.on_result)
            )
        ).scalars()
    )
    links = list(
        (
            await db.execute(
                select(RuleSource)
                .where(RuleSource.rule_version_id == version.id)
                .order_by(RuleSource.relationship, RuleSource.created_at)
            )
        ).scalars()
    )
    refs = {
        v.reference.id: v
        for v in await regulatory.list_references(db, ids=[s.source_reference_id for s in links])
    }
    tests = list(
        (
            await db.execute(
                select(RuleTestCase)
                .where(RuleTestCase.rule_version_id == version.id)
                .order_by(RuleTestCase.name)
            )
        ).scalars()
    )
    paths = list(
        (
            await db.execute(
                select(RuleFactDependency.fact_path)
                .where(RuleFactDependency.rule_version_id == version.id)
                .order_by(RuleFactDependency.fact_path)
            )
        ).scalars()
    )
    return VersionView(
        version=version,
        rule=rule,
        rule_set=rule_set,
        outcomes=outcomes,
        sources=[(s, refs[s.source_reference_id]) for s in links],
        test_cases=tests,
        fact_paths=paths,
    )


def _require_draft(version: RuleVersion) -> None:
    if version.status != S.DRAFT:
        raise _conflict(
            "version_immutable",
            f"Version {version.version} is {version.status.lower()} and can't be changed. "
            "Create a new version instead.",
        )


async def _set_dependencies(db: AsyncSession, version: RuleVersion) -> None:
    await db.execute(
        delete(RuleFactDependency).where(RuleFactDependency.rule_version_id == version.id)
    )
    paths = sorted({leaf.fact for leaf in referenced_facts(parse_condition(version.condition))})
    for path in paths:
        db.add(RuleFactDependency(rule_version_id=version.id, fact_path=path))
    await db.flush()


async def new_version(db: AsyncSession, rule: Rule, actor: Actor) -> RuleVersion:
    """A new draft copied from the rule's latest version (one draft at a time)."""
    versions = await versions_of(db, rule)
    if any(v.status == S.DRAFT for v in versions):
        raise _conflict("draft_exists", "This rule already has a draft. Edit that one.")
    latest = await get_version(db, versions[-1].id)
    draft = RuleVersion(
        rule_id=rule.id,
        version=latest.version.version + 1,
        condition=latest.version.condition,
        effective_from=latest.version.effective_from,
        effective_to=latest.version.effective_to,
        max_confidence=latest.version.max_confidence,
        notes=latest.version.notes,
        created_by=actor.user_id,
    )
    db.add(draft)
    await db.flush()
    for o in latest.outcomes:
        db.add(
            RuleOutcome(
                rule_version_id=draft.id,
                on_result=o.on_result,
                outcome_type=o.outcome_type,
                title=o.title,
                detail=o.detail,
            )
        )
    for link, _ in latest.sources:
        db.add(
            RuleSource(
                rule_version_id=draft.id,
                source_reference_id=link.source_reference_id,
                relationship=link.relationship,
            )
        )
    for t in latest.test_cases:
        db.add(
            RuleTestCase(
                rule_version_id=draft.id,
                name=t.name,
                facts=t.facts,
                expected_result=t.expected_result,
            )
        )
    await db.flush()
    await _set_dependencies(db, draft)
    await _audit(db, "rule.version_created", actor, "rule_version", draft.id, version=draft.version)
    return draft


def _check_test_facts(test_cases: Sequence[dict[str, Any]]) -> None:
    pattern = re.compile(FACT_PATTERN)
    errors: dict[str, str] = {}
    names: set[str] = set()
    for i, case in enumerate(test_cases):
        if case["name"] in names:
            errors[f"test_cases.{i}.name"] = "Test case names must be unique."
        names.add(case["name"])
        bad = [k for k in case["facts"] if not pattern.match(k) or len(k) > 120]
        if bad:
            errors[f"test_cases.{i}.facts"] = f"Not a fact path: {', '.join(sorted(bad))}"
    if errors:
        raise _invalid("invalid_test_cases", "Some test cases need attention.", fields=errors)


async def save_draft(
    db: AsyncSession, version: RuleVersion, content: dict[str, Any], actor: Actor
) -> RuleVersion:
    _require_draft(version)
    condition = validated_condition(content["condition"])
    if (
        content.get("effective_from")
        and content.get("effective_to")
        and content["effective_to"] <= content["effective_from"]
    ):
        raise _invalid("invalid_dates", "The end date must be after the start date.")
    results = [o["on_result"] for o in content["outcomes"]]
    if len(results) != len(set(results)):
        raise _invalid("duplicate_outcome", "Give each result at most one outcome.")
    ref_ids = [s["source_reference_id"] for s in content["sources"]]
    if len(ref_ids) != len(set(ref_ids)):
        raise _invalid("duplicate_source", "Cite each source reference once.")
    found = {v.reference.id for v in await regulatory.list_references(db, ids=ref_ids)}
    if missing := [str(r) for r in ref_ids if r not in found]:
        raise _invalid("unknown_source", f"Source reference not found: {', '.join(missing)}")
    _check_test_facts(content["test_cases"])

    version.condition = condition
    version.effective_from = content.get("effective_from")
    version.effective_to = content.get("effective_to")
    version.max_confidence = content["max_confidence"]
    version.notes = content.get("notes")
    for model in (RuleOutcome, RuleSource, RuleTestCase):
        await db.execute(delete(model).where(model.rule_version_id == version.id))
    for o in content["outcomes"]:
        db.add(RuleOutcome(rule_version_id=version.id, **o))
    for s in content["sources"]:
        db.add(RuleSource(rule_version_id=version.id, **s))
    for t in content["test_cases"]:
        db.add(RuleTestCase(rule_version_id=version.id, **t))
    version.updated_at = utcnow()
    await db.flush()
    await _set_dependencies(db, version)
    await _audit(db, "rule.draft_saved", actor, "rule_version", version.id, version=version.version)
    return version


async def delete_draft(db: AsyncSession, view: VersionView, actor: Actor) -> None:
    _require_draft(view.version)
    if view.version.version == 1:
        raise _conflict(
            "first_version", "The first version of a rule can't be deleted. Edit it instead."
        )
    await db.delete(view.version)
    await db.flush()
    await _audit(
        db, "rule.draft_deleted", actor, "rule", view.rule.id, version=view.version.version
    )


# --- Sources as the engine sees them ---------------------------------------------------


async def source_states(
    db: AsyncSession, version_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, tuple[engine.SourceState, ...]]:
    if not version_ids:
        return {}
    rows = (
        await db.execute(
            select(RuleSource, SourceReference, SourceDocument, SourceOrganisation)
            .join(SourceReference, SourceReference.id == RuleSource.source_reference_id)
            .join(SourceDocument, SourceDocument.id == SourceReference.source_document_id)
            .join(
                SourceOrganisation, SourceOrganisation.id == SourceDocument.source_organisation_id
            )
            .where(RuleSource.rule_version_id.in_(list(version_ids)))
            .order_by(RuleSource.relationship, SourceReference.id)
        )
    ).all()
    snapshots = await regulatory.latest_snapshots(db, list({d.id for _, _, d, _ in rows}))
    states: dict[uuid.UUID, list[engine.SourceState]] = defaultdict(list)
    for link, ref, doc, org in rows:
        latest = snapshots.get(doc.id)
        states[link.rule_version_id].append(
            engine.SourceState(
                reference_id=ref.id,
                relationship=link.relationship,
                status=ref.verification_status,
                document_title=doc.title,
                organisation_name=org.name,
                url=doc.url,
                section=ref.section,
                clause=ref.clause,
                page=ref.page,
                effective_from=doc.effective_from,
                effective_to=doc.effective_to,
                next_review_due=ref.next_review_due,
                verified_snapshot_id=ref.verified_snapshot_id,
                latest_snapshot_id=latest.id if latest else None,
            )
        )
    return {v: tuple(states.get(v, ())) for v in version_ids}


def _spec(view: VersionView, sources: tuple[engine.SourceState, ...]) -> engine.RuleSpec:
    v = view.version
    return engine.RuleSpec(
        rule_version_id=v.id,
        rule_set_id=view.rule_set.id,
        rule_key=view.rule.key,
        rule_title=view.rule.title,
        condition=parse_condition(v.condition),
        outcomes={
            o.on_result: engine.OutcomeSpec(o.outcome_type, o.title, o.detail)
            for o in view.outcomes
        },
        sources=sources,
        max_confidence=Confidence(v.max_confidence),
        effective_from=v.effective_from,
        effective_to=v.effective_to,
    )


async def evaluate_version(
    db: AsyncSession, view: VersionView, facts: dict[str, Any], on: date
) -> engine.Finding:
    """Try a version (draft or not) against facts: the admin's "try it"."""
    sources = (await source_states(db, [view.version.id]))[view.version.id]
    return engine.evaluate_rule(_spec(view, sources), engine.decode_facts(facts), on)


# --- Publish gate ----------------------------------------------------------------------


@dataclass(frozen=True)
class GateResult:
    checks: list[tuple[str, bool, str]]
    warnings: list[str]
    test_results: list[engine.TestCaseResult]

    @property
    def ready(self) -> bool:
        return all(passed for _, passed, _ in self.checks)


async def publish_checks(db: AsyncSession, view: VersionView) -> GateResult:
    v = view.version
    checks: list[tuple[str, bool, str]] = []

    def check(key: str, passed: bool, ok: str, problem: str) -> None:
        checks.append((key, passed, ok if passed else problem))

    check("draft", v.status == S.DRAFT, "Draft.", f"Version is {v.status.lower()}.")
    try:
        condition = parse_condition(v.condition)
    except (ValidationError, ValueError):
        condition = None
    check("condition", condition is not None, "Condition is valid.", "Condition is not valid.")
    check(
        "effective_from",
        v.effective_from is not None,
        "Has an effective date.",
        "Set the date this rule takes effect.",
    )
    check(
        "outcomes",
        bool(view.outcomes),
        "Has an outcome.",
        "Add at least one outcome (what a result means for the customer).",
    )
    check(
        "basis_source",
        any(link.relationship == SourceRelationship.BASIS for link, _ in view.sources),
        "Cites a source as its basis.",
        "Cite at least one source reference as the basis for this rule.",
    )
    unusable = [
        regulatory.citation(ref.reference, ref.document)
        for _, ref in view.sources
        if ref.reference.verification_status
        in (VerificationStatus.DISPUTED, VerificationStatus.SUPERSEDED)
    ]
    check(
        "sources_usable",
        not unusable,
        "No cited source is disputed or superseded.",
        f"Disputed or superseded: {'; '.join(unusable)}.",
    )

    results: list[engine.TestCaseResult] = []
    if condition is not None:
        results = [
            engine.run_test_case(condition, t.name, t.facts, t.expected_result)
            for t in view.test_cases
        ]
    failing = [r.name for r in results if not r.passed]
    check(
        "test_cases",
        bool(results) and not failing,
        f"All {len(results)} test case(s) pass.",
        f"Failing: {', '.join(failing)}." if failing else "Add at least one test case.",
    )

    warnings: list[str] = []
    unverified = [
        regulatory.citation(ref.reference, ref.document)
        for _, ref in view.sources
        if ref.reference.verification_status == VerificationStatus.UNVERIFIED
    ]
    if unverified:
        warnings.append(
            "Not verified yet, so findings will be 'likely' at best: " + "; ".join(unverified)
        )
    known = await questionnaires.fact_labels(db, view.rule_set.vertical)
    uncollected = [p for p in view.fact_paths if p not in known]
    if uncollected:
        warnings.append(
            "No published questionnaire collects these facts, so they will be unknown: "
            + ", ".join(uncollected)
        )
    return GateResult(checks, warnings, results)


def content_hash(view: VersionView) -> bytes:
    v = view.version
    return engine.canonical_hash(
        {
            "condition": v.condition,
            "effective_from": v.effective_from.isoformat() if v.effective_from else None,
            "effective_to": v.effective_to.isoformat() if v.effective_to else None,
            "max_confidence": v.max_confidence,
            "outcomes": sorted(
                [o.on_result, o.outcome_type, o.title, o.detail] for o in view.outcomes
            ),
            "sources": sorted(
                [str(link.source_reference_id), link.relationship] for link, _ in view.sources
            ),
            "test_cases": sorted([t.name, t.facts, t.expected_result] for t in view.test_cases),
        }
    )


async def publish(db: AsyncSession, view: VersionView, actor: Actor) -> RuleVersion:
    gate = await publish_checks(db, view)
    if not gate.ready:
        raise _conflict(
            "publish_blocked",
            "This version can't be published yet.",
            fields={key: message for key, passed, message in gate.checks if not passed},
        )
    current = (
        await db.execute(
            select(RuleVersion).where(
                RuleVersion.rule_id == view.rule.id, RuleVersion.status == S.PUBLISHED
            )
        )
    ).scalar_one_or_none()
    if current is not None:
        current.status = S.RETIRED
        await db.flush()
    v = view.version
    v.content_hash = content_hash(view)
    v.status = S.PUBLISHED
    v.published_by = actor.user_id
    v.published_at = utcnow()
    await db.flush()
    await _audit(
        db,
        "rule.version_published",
        actor,
        "rule_version",
        v.id,
        rule=view.rule.key,
        version=v.version,
        content_hash=v.content_hash.hex(),
        retired_version=current.version if current else None,
    )
    return v


async def retire(db: AsyncSession, view: VersionView, actor: Actor) -> RuleVersion:
    v = view.version
    if v.status != S.PUBLISHED:
        raise _conflict("not_published", "Only the published version can be retired.")
    v.status = S.RETIRED
    await db.flush()
    await _audit(
        db,
        "rule.version_retired",
        actor,
        "rule_version",
        v.id,
        rule=view.rule.key,
        version=v.version,
    )
    return v


# --- Published rules for assessments ---------------------------------------------------


async def published_rule_sets(db: AsyncSession, vertical: str) -> list[engine.RuleSetSpec]:
    """Every rule set of the vertical with at least one published rule, with those rules
    and the current state of their sources."""
    rows = (
        await db.execute(
            select(RuleVersion, Rule, RuleSet)
            .join(Rule, Rule.id == RuleVersion.rule_id)
            .join(RuleSet, RuleSet.id == Rule.rule_set_id)
            .where(RuleSet.vertical == vertical, RuleVersion.status == S.PUBLISHED)
            .order_by(RuleSet.key, Rule.key)
        )
    ).all()
    version_ids = [v.id for v, _, _ in rows]
    outcomes: dict[uuid.UUID, list[RuleOutcome]] = defaultdict(list)
    if version_ids:
        for o in (
            await db.execute(
                select(RuleOutcome).where(RuleOutcome.rule_version_id.in_(version_ids))
            )
        ).scalars():
            outcomes[o.rule_version_id].append(o)
    sources = await source_states(db, version_ids)
    by_set: dict[uuid.UUID, tuple[RuleSet, list[engine.RuleSpec]]] = {}
    for v, rule, rule_set in rows:
        view = VersionView(v, rule, rule_set, outcomes[v.id], [], [], [])
        by_set.setdefault(rule_set.id, (rule_set, []))[1].append(_spec(view, sources[v.id]))
    return [
        engine.RuleSetSpec(
            id=rs.id,
            key=rs.key,
            title=rs.title,
            applies_when=parse_condition(rs.applies_when) if rs.applies_when else None,
            applies_when_json=rs.applies_when,
            rules=tuple(specs),
        )
        for rs, specs in by_set.values()
    ]
