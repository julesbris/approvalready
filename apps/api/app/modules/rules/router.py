"""``/v1/admin/rule-*``: authoring, testing and publishing rules (platform organisation
active). ``rule.author`` drafts and tests; ``rule.publish`` publishes and retires."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import DbDep, MetaDep, OrgContext, require_platform_permission
from app.modules.projects.models import Vertical
from app.modules.regulatory import service as regulatory
from app.modules.rules import engine, service
from app.modules.rules.models import RuleSet
from app.modules.rules.schemas import (
    EvaluateIn,
    EvaluateOut,
    OutcomeOut,
    PublishCheck,
    PublishChecksOut,
    RuleCreate,
    RuleOut,
    RuleSetCreate,
    RuleSetOut,
    RuleSetUpdate,
    RuleSourceOut,
    RuleSummary,
    RuleUpdate,
    RuleVersionContent,
    RuleVersionOut,
    RuleVersionSummary,
    TestCaseOut,
    TestCaseResultOut,
)
from app.modules.tenancy.rbac import Perm

router = APIRouter(prefix="/v1/admin", tags=["admin: rules"])

Author = Annotated[OrgContext, Depends(require_platform_permission(Perm.RULE_AUTHOR))]
Publisher = Annotated[OrgContext, Depends(require_platform_permission(Perm.RULE_PUBLISH))]


def _actor(ctx: OrgContext, meta: MetaDep | None) -> regulatory.Actor:
    return regulatory.Actor(ctx.auth.user.id, ctx.organisation.id, meta)


async def _rule_set_out(db: DbDep, rule_set: RuleSet) -> RuleSetOut:
    return RuleSetOut(
        id=rule_set.id,
        key=rule_set.key,
        vertical=Vertical(rule_set.vertical),
        jurisdiction=rule_set.jurisdiction,
        title=rule_set.title,
        description=rule_set.description,
        applies_when=rule_set.applies_when,
        limitations=rule_set.limitations,
        rules=[
            RuleSummary(
                id=row.rule.id,
                key=row.rule.key,
                title=row.rule.title,
                published_version=row.published.version if row.published else None,
                published_version_id=row.published.id if row.published else None,
                draft_version_id=row.draft.id if row.draft else None,
                latest_version=row.latest_version,
            )
            for row in await service.rules_of(db, rule_set)
        ],
        created_at=rule_set.created_at,
        updated_at=rule_set.updated_at,
    )


def _version_out(view: service.VersionView) -> RuleVersionOut:
    v = view.version
    return RuleVersionOut(
        id=v.id,
        rule_id=view.rule.id,
        rule_key=view.rule.key,
        rule_title=view.rule.title,
        rule_set_id=view.rule_set.id,
        rule_set_key=view.rule_set.key,
        vertical=Vertical(view.rule_set.vertical),
        version=v.version,
        status=v.status,
        condition=v.condition,
        effective_from=v.effective_from,
        effective_to=v.effective_to,
        max_confidence=v.max_confidence,
        notes=v.notes,
        outcomes=[
            OutcomeOut(
                on_result=o.on_result,
                outcome_type=o.outcome_type,
                title=o.title,
                detail=o.detail,
                payload=o.payload,
            )
            for o in view.outcomes
        ],
        sources=[
            RuleSourceOut(
                source_reference_id=link.source_reference_id,
                relationship=link.relationship,
                citation=regulatory.citation(ref.reference, ref.document),
                url=ref.document.url,
                verification_status=ref.reference.verification_status,
            )
            for link, ref in view.sources
        ],
        test_cases=[
            TestCaseOut(
                name=t.name,
                facts=t.facts,
                expected_result=t.expected_result,
            )
            for t in view.test_cases
        ],
        fact_paths=view.fact_paths,
        content_hash=v.content_hash.hex() if v.content_hash else None,
        created_by=v.created_by,
        published_by=v.published_by,
        published_at=v.published_at,
        created_at=v.created_at,
        updated_at=v.updated_at,
    )


def _test_result_out(r: engine.TestCaseResult) -> TestCaseResultOut:
    return TestCaseResultOut(
        name=r.name, expected=r.expected, actual=r.actual, passed=r.passed, trace=r.trace
    )


# --- Rule sets -------------------------------------------------------------------------


@router.get("/rule-sets", response_model=list[RuleSetOut])
async def list_rule_sets(
    ctx: Author, db: DbDep, vertical: Vertical | None = None
) -> list[RuleSetOut]:
    return [await _rule_set_out(db, rs) for rs in await service.list_rule_sets(db, vertical)]


@router.post("/rule-sets", status_code=status.HTTP_201_CREATED, response_model=RuleSetOut)
async def create_rule_set(body: RuleSetCreate, ctx: Author, db: DbDep, meta: MetaDep) -> RuleSetOut:
    rule_set = await service.create_rule_set(db, body.model_dump(), _actor(ctx, meta))
    await db.commit()
    return await _rule_set_out(db, rule_set)


@router.get("/rule-sets/{rule_set_id}", response_model=RuleSetOut)
async def get_rule_set(rule_set_id: uuid.UUID, ctx: Author, db: DbDep) -> RuleSetOut:
    return await _rule_set_out(db, await service.get_rule_set(db, rule_set_id))


@router.patch("/rule-sets/{rule_set_id}", response_model=RuleSetOut)
async def update_rule_set(
    rule_set_id: uuid.UUID, body: RuleSetUpdate, ctx: Author, db: DbDep, meta: MetaDep
) -> RuleSetOut:
    rule_set = await service.get_rule_set(db, rule_set_id)
    await service.update_rule_set(
        db, rule_set, body.model_dump(exclude_unset=True), _actor(ctx, meta)
    )
    await db.commit()
    return await _rule_set_out(db, rule_set)


# --- Rules -----------------------------------------------------------------------------


async def _rule_out(db: DbDep, rule_id: uuid.UUID) -> RuleOut:
    rule, rule_set = await service.get_rule(db, rule_id)
    return RuleOut(
        id=rule.id,
        rule_set_id=rule_set.id,
        rule_set_key=rule_set.key,
        key=rule.key,
        title=rule.title,
        versions=[
            RuleVersionSummary.model_validate(v, from_attributes=True)
            for v in await service.versions_of(db, rule)
        ],
    )


@router.post(
    "/rule-sets/{rule_set_id}/rules", status_code=status.HTTP_201_CREATED, response_model=RuleOut
)
async def create_rule(
    rule_set_id: uuid.UUID, body: RuleCreate, ctx: Author, db: DbDep, meta: MetaDep
) -> RuleOut:
    """Create a rule with its first draft version."""
    rule_set = await service.get_rule_set(db, rule_set_id)
    rule, _ = await service.create_rule(db, rule_set, body.model_dump(), _actor(ctx, meta))
    await db.commit()
    return await _rule_out(db, rule.id)


@router.get("/rules/{rule_id}", response_model=RuleOut)
async def get_rule(rule_id: uuid.UUID, ctx: Author, db: DbDep) -> RuleOut:
    return await _rule_out(db, rule_id)


@router.patch("/rules/{rule_id}", response_model=RuleOut)
async def update_rule(
    rule_id: uuid.UUID, body: RuleUpdate, ctx: Author, db: DbDep, meta: MetaDep
) -> RuleOut:
    rule, _ = await service.get_rule(db, rule_id)
    await service.rename_rule(db, rule, body.title, _actor(ctx, meta))
    await db.commit()
    return await _rule_out(db, rule_id)


@router.post(
    "/rules/{rule_id}/versions", status_code=status.HTTP_201_CREATED, response_model=RuleVersionOut
)
async def create_rule_version(
    rule_id: uuid.UUID, ctx: Author, db: DbDep, meta: MetaDep
) -> RuleVersionOut:
    """Start a new draft, copied from the latest version."""
    rule, _ = await service.get_rule(db, rule_id)
    draft = await service.new_version(db, rule, _actor(ctx, meta))
    await db.commit()
    return _version_out(await service.get_version(db, draft.id))


# --- Versions --------------------------------------------------------------------------


@router.get("/rule-versions/{version_id}", response_model=RuleVersionOut)
async def get_rule_version(version_id: uuid.UUID, ctx: Author, db: DbDep) -> RuleVersionOut:
    return _version_out(await service.get_version(db, version_id))


@router.put("/rule-versions/{version_id}", response_model=RuleVersionOut)
async def save_rule_version(
    version_id: uuid.UUID, body: RuleVersionContent, ctx: Author, db: DbDep, meta: MetaDep
) -> RuleVersionOut:
    view = await service.get_version(db, version_id)
    await service.save_draft(db, view.version, body.model_dump(), _actor(ctx, meta))
    await db.commit()
    return _version_out(await service.get_version(db, version_id))


@router.delete("/rule-versions/{version_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule_version(version_id: uuid.UUID, ctx: Author, db: DbDep, meta: MetaDep) -> None:
    await service.delete_draft(db, await service.get_version(db, version_id), _actor(ctx, meta))
    await db.commit()


@router.get("/rule-versions/{version_id}/checks", response_model=PublishChecksOut)
async def check_rule_version(version_id: uuid.UUID, ctx: Author, db: DbDep) -> PublishChecksOut:
    """Run the publish gate (including every test case) without publishing."""
    gate = await service.publish_checks(db, await service.get_version(db, version_id))
    return PublishChecksOut(
        ready=gate.ready,
        checks=[PublishCheck(key=k, passed=p, message=m) for k, p, m in gate.checks],
        warnings=gate.warnings,
        test_results=[_test_result_out(r) for r in gate.test_results],
    )


@router.post("/rule-versions/{version_id}/evaluate", response_model=EvaluateOut)
async def evaluate_rule_version(
    version_id: uuid.UUID, body: EvaluateIn, ctx: Author, db: DbDep
) -> EvaluateOut:
    """Try the version against some facts, with the confidence its sources allow today."""
    view = await service.get_version(db, version_id)
    finding = await service.evaluate_version(db, view, body.facts, body.on or regulatory.today())
    return EvaluateOut(
        result=finding.result,
        outcome=(
            OutcomeOut(
                on_result=finding.result,
                outcome_type=finding.outcome.outcome_type,
                title=finding.outcome.title,
                detail=finding.outcome.detail,
                payload=finding.outcome.payload,
            )
            if finding.outcome
            else None
        ),
        confidence=finding.confidence,
        confidence_reasons=finding.confidence_reasons,
        missing_facts=finding.missing_facts,
        trace=finding.trace,
    )


@router.post("/rule-versions/{version_id}/publish", response_model=RuleVersionOut)
async def publish_rule_version(
    version_id: uuid.UUID, ctx: Publisher, db: DbDep, meta: MetaDep
) -> RuleVersionOut:
    view = await service.get_version(db, version_id)
    await service.publish(db, view, _actor(ctx, meta))
    await db.commit()
    return _version_out(await service.get_version(db, version_id))


@router.post("/rule-versions/{version_id}/retire", response_model=RuleVersionOut)
async def retire_rule_version(
    version_id: uuid.UUID, ctx: Publisher, db: DbDep, meta: MetaDep
) -> RuleVersionOut:
    view = await service.get_version(db, version_id)
    await service.retire(db, view, _actor(ctx, meta))
    await db.commit()
    return _version_out(await service.get_version(db, version_id))
