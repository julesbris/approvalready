"""GrantReady staff screens: ``/v1/admin/grant-programs`` and ``/v1/admin/grant-rounds``.

Customers see programs through their grant assessments (``grant_matches`` on the
assessment), with each program's rounds as they stand today.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import DbDep, MetaDep, OrgContext, require_platform_permission
from app.modules.grants import service
from app.modules.grants.models import GrantMatch, MatchStatus, ProgramStatus, RoundStatus
from app.modules.grants.schemas import (
    AdministratorOut,
    GrantMatchOut,
    GrantProgramCreate,
    GrantProgramOut,
    GrantProgramUpdate,
    GrantRoundCreate,
    GrantRoundOut,
    GrantRoundUpdate,
    MatchCriterionOut,
    RoundSourceOut,
)
from app.modules.grants.service import ProgramView, RoundView
from app.modules.regulatory import service as regulatory
from app.modules.regulatory.service import Actor
from app.modules.rules.models import Confidence
from app.modules.tenancy.rbac import Perm

router = APIRouter(prefix="/v1/admin", tags=["admin: grants"])

# Programs and rounds are source-backed data: the people who capture sources keep them.
Manage = Annotated[OrgContext, Depends(require_platform_permission(Perm.SOURCE_MANAGE))]


def _actor(ctx: OrgContext, meta: MetaDep) -> Actor:
    return Actor(ctx.auth.user.id, ctx.organisation.id, meta)


def round_out(v: RoundView) -> GrantRoundOut:
    r = v.round
    return GrantRoundOut(
        id=r.id,
        program_id=r.program_id,
        title=r.title,
        status=RoundStatus(r.status),
        state=v.state.state,
        opens_on=r.opens_on,
        closes_on=r.closes_on,
        dates_note=r.dates_note,
        days_to_close=v.state.days_to_close,
        closing_soon=v.state.closing_soon,
        check_source=v.state.check_source,
        source=RoundSourceOut(
            reference_id=v.reference.id,
            citation=regulatory.citation(v.reference, v.document),
            url=v.document.url,
            verification_status=v.reference.verification_status,
        ),
        updated_at=r.updated_at,
    )


def program_out(v: ProgramView) -> GrantProgramOut:
    p = v.program
    return GrantProgramOut(
        id=p.id,
        key=p.key,
        title=p.title,
        summary=p.summary,
        administrator=AdministratorOut(id=v.administrator.id, name=v.administrator.name),
        jurisdiction=p.jurisdiction,
        url=p.url,
        rule_set_id=p.rule_set_id,
        rule_set_key=v.rule_set.key,
        funding_summary=p.funding_summary,
        min_amount_cents=p.min_amount_cents,
        max_amount_cents=p.max_amount_cents,
        status=ProgramStatus(p.status),
        rounds=[round_out(r) for r in v.rounds],
        current_round_id=v.current_round_id,
    )


def match_out(m: GrantMatch, v: ProgramView) -> GrantMatchOut:
    return GrantMatchOut(
        id=m.id,
        status=MatchStatus(m.status),
        confidence=Confidence(m.confidence),
        criteria=[MatchCriterionOut.model_validate(c) for c in m.criteria],
        missing_facts=m.missing_facts,
        round_id_at_assessment=m.round_id,
        program=program_out(v),
    )


@router.get("/grant-programs", response_model=list[GrantProgramOut])
async def list_programs(ctx: Manage, db: DbDep) -> list[GrantProgramOut]:
    return [program_out(v) for v in await service.list_programs(db)]


@router.post("/grant-programs", status_code=status.HTTP_201_CREATED, response_model=GrantProgramOut)
async def create_program(
    body: GrantProgramCreate, ctx: Manage, db: DbDep, meta: MetaDep
) -> GrantProgramOut:
    program = await service.create_program(db, body.model_dump(), _actor(ctx, meta))
    await db.commit()
    return program_out(await service.program_view(db, program))


@router.get("/grant-programs/{program_id}", response_model=GrantProgramOut)
async def get_program(program_id: uuid.UUID, ctx: Manage, db: DbDep) -> GrantProgramOut:
    return program_out(await service.program_view(db, await service.get_program(db, program_id)))


@router.patch("/grant-programs/{program_id}", response_model=GrantProgramOut)
async def update_program(
    program_id: uuid.UUID, body: GrantProgramUpdate, ctx: Manage, db: DbDep, meta: MetaDep
) -> GrantProgramOut:
    program = await service.get_program(db, program_id)
    await service.update_program(
        db, program, body.model_dump(exclude_unset=True), _actor(ctx, meta)
    )
    await db.commit()
    return program_out(await service.program_view(db, program))


@router.post(
    "/grant-programs/{program_id}/rounds",
    status_code=status.HTTP_201_CREATED,
    response_model=GrantProgramOut,
)
async def create_round(
    program_id: uuid.UUID, body: GrantRoundCreate, ctx: Manage, db: DbDep, meta: MetaDep
) -> GrantProgramOut:
    program = await service.get_program(db, program_id)
    await service.create_round(db, program, body.model_dump(), _actor(ctx, meta))
    await db.commit()
    return program_out(await service.program_view(db, program))


@router.patch("/grant-rounds/{round_id}", response_model=GrantProgramOut)
async def update_round(
    round_id: uuid.UUID, body: GrantRoundUpdate, ctx: Manage, db: DbDep, meta: MetaDep
) -> GrantProgramOut:
    found = await service.get_round(db, round_id)
    await service.update_round(db, found, body.model_dump(exclude_unset=True), _actor(ctx, meta))
    await db.commit()
    return program_out(
        await service.program_view(db, await service.get_program(db, found.program_id))
    )
