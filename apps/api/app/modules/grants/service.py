"""GrantReady: staff manage programs and rounds; assessments of grant projects record a
match per program (``matching.py`` decides it).

Programs and rounds are platform data, so their changes are audited under the staff
member's platform organisation, like sources and rules.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, not_found
from app.modules.audit import service as audit
from app.modules.grants import matching
from app.modules.grants.models import (
    GrantMatch,
    GrantProgram,
    GrantRound,
    MatchStatus,
    ProgramStatus,
)
from app.modules.projects.models import Project, Vertical
from app.modules.regulatory import service as regulatory
from app.modules.regulatory.models import SourceDocument, SourceOrganisation, SourceReference
from app.modules.regulatory.service import Actor
from app.modules.rules.models import RuleSet

AEST = timezone(timedelta(hours=10), "AEST")

# Order matches are listed in: the best news first.
STATUS_ORDER = {
    MatchStatus.STRONG_MATCH: 0,
    MatchStatus.POSSIBLE_MATCH: 1,
    MatchStatus.NEEDS_INFORMATION: 2,
    MatchStatus.NOT_ELIGIBLE: 3,
}


def today() -> date:
    """Round dates are Australian calendar dates (Queensland time, like assessments)."""
    return datetime.now(UTC).astimezone(AEST).date()


def _invalid(code: str, message: str) -> ApiError:
    return ApiError(status.HTTP_422_UNPROCESSABLE_CONTENT, code, message)


def _conflict(code: str, message: str) -> ApiError:
    return ApiError(status.HTTP_409_CONFLICT, code, message)


async def _audit(
    db: AsyncSession,
    action: str,
    actor: Actor,
    target_type: str,
    target_id: uuid.UUID,
    details: dict[str, Any],
) -> None:
    await audit.record(
        db,
        action,
        actor_user_id=actor.user_id,
        organisation_id=actor.organisation_id,
        target_type=target_type,
        target_id=target_id,
        meta=actor.meta,
        details=details,
    )


def _jsonable(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v.isoformat() if isinstance(v, date) else v for k, v in data.items()}


# --- Reading ---------------------------------------------------------------------------


@dataclass
class RoundView:
    round: GrantRound
    state: matching.RoundState
    reference: SourceReference
    document: SourceDocument


@dataclass
class ProgramView:
    program: GrantProgram
    administrator: SourceOrganisation
    rule_set: RuleSet
    rounds: list[RoundView]
    current_round_id: uuid.UUID | None


async def _views(
    db: AsyncSession, programs: Sequence[GrantProgram], on: date
) -> dict[uuid.UUID, ProgramView]:
    if not programs:
        return {}
    ids = [p.id for p in programs]
    admins = {
        o.id: o
        for o in (
            await db.execute(
                select(SourceOrganisation).where(
                    SourceOrganisation.id.in_({p.administrator_id for p in programs})
                )
            )
        ).scalars()
    }
    rule_sets = {
        r.id: r
        for r in (
            await db.execute(
                select(RuleSet).where(RuleSet.id.in_({p.rule_set_id for p in programs}))
            )
        ).scalars()
    }
    rows = (
        await db.execute(
            select(GrantRound, SourceReference, SourceDocument)
            .join(SourceReference, SourceReference.id == GrantRound.source_reference_id)
            .join(SourceDocument, SourceDocument.id == SourceReference.source_document_id)
            .where(GrantRound.program_id.in_(ids))
            .order_by(GrantRound.opens_on.desc().nulls_first(), GrantRound.created_at.desc())
        )
    ).all()
    rounds: dict[uuid.UUID, list[RoundView]] = {i: [] for i in ids}
    for r, ref, doc in rows:
        rounds[r.program_id].append(RoundView(r, matching.round_state(r, on), ref, doc))
    out = {}
    for p in programs:
        current = matching.current_round([v.round for v in rounds[p.id]], on)
        out[p.id] = ProgramView(
            program=p,
            administrator=admins[p.administrator_id],
            rule_set=rule_sets[p.rule_set_id],
            rounds=rounds[p.id],
            current_round_id=current.id if current else None,
        )
    return out


async def list_programs(
    db: AsyncSession, *, include_retired: bool = True, on: date | None = None
) -> list[ProgramView]:
    query = select(GrantProgram).order_by(GrantProgram.title)
    if not include_retired:
        query = query.where(GrantProgram.status == ProgramStatus.ACTIVE)
    programs = list((await db.execute(query)).scalars())
    views = await _views(db, programs, on or today())
    return [views[p.id] for p in programs]


async def get_program(db: AsyncSession, program_id: uuid.UUID) -> GrantProgram:
    program = await db.get(GrantProgram, program_id)
    if program is None:
        raise not_found("Grant program")
    return program


async def program_view(db: AsyncSession, program: GrantProgram) -> ProgramView:
    return (await _views(db, [program], today()))[program.id]


async def get_round(db: AsyncSession, round_id: uuid.UUID) -> GrantRound:
    found = await db.get(GrantRound, round_id)
    if found is None:
        raise not_found("Grant round")
    return found


# --- Staff changes ---------------------------------------------------------------------


async def _check_rule_set(
    db: AsyncSession, rule_set_id: uuid.UUID, exclude: uuid.UUID | None = None
) -> RuleSet:
    rule_set = await db.get(RuleSet, rule_set_id)
    if rule_set is None:
        raise _invalid("rule_set_not_found", "That rule set doesn't exist.")
    if rule_set.vertical != Vertical.GRANT:
        raise _invalid(
            "rule_set_not_grant", "A program's eligibility rules must be a GRANT rule set."
        )
    taken = (
        await db.execute(
            select(GrantProgram.id).where(
                GrantProgram.rule_set_id == rule_set_id, GrantProgram.id != exclude
            )
        )
    ).first()
    if taken:
        raise _conflict("rule_set_taken", "Another program already uses that rule set.")
    return rule_set


def _check_amounts(low: int | None, high: int | None) -> None:
    if low is not None and high is not None and high < low:
        raise _invalid("amount_range", "The maximum amount can't be less than the minimum.")


async def create_program(db: AsyncSession, data: dict[str, Any], actor: Actor) -> GrantProgram:
    if (await db.execute(select(GrantProgram.id).where(GrantProgram.key == data["key"]))).first():
        raise _conflict("key_taken", "A grant program with that key already exists.")
    await regulatory.get_organisation(db, data["administrator_id"])
    await _check_rule_set(db, data["rule_set_id"])
    _check_amounts(data.get("min_amount_cents"), data.get("max_amount_cents"))
    program = GrantProgram(created_by=actor.user_id, **data)
    db.add(program)
    await db.flush()
    await _audit(
        db,
        "grant.program.create",
        actor,
        "grant_program",
        program.id,
        {"key": program.key, "rule_set_id": str(program.rule_set_id)},
    )
    return program


async def update_program(
    db: AsyncSession, program: GrantProgram, data: dict[str, Any], actor: Actor
) -> GrantProgram:
    _check_amounts(
        data.get("min_amount_cents", program.min_amount_cents),
        data.get("max_amount_cents", program.max_amount_cents),
    )
    for name, value in data.items():
        setattr(program, name, value)
    await db.flush()
    await _audit(
        db, "grant.program.update", actor, "grant_program", program.id, {"fields": sorted(data)}
    )
    return program


async def _check_reference(db: AsyncSession, reference_id: uuid.UUID) -> SourceReference:
    ref = await db.get(SourceReference, reference_id)
    if ref is None:
        raise _invalid(
            "reference_not_found", "Cite the source reference the round's dates come from."
        )
    return ref


def _check_dates(opens_on: date | None, closes_on: date | None) -> None:
    if opens_on is not None and closes_on is not None and closes_on < opens_on:
        raise _invalid("closes_before_opens", "A round can't close before it opens.")


async def _title_taken(
    db: AsyncSession, program_id: uuid.UUID, title: str, exclude: uuid.UUID | None = None
) -> bool:
    return (
        await db.execute(
            select(GrantRound.id).where(
                GrantRound.program_id == program_id,
                GrantRound.title == title,
                GrantRound.id != exclude,
            )
        )
    ).first() is not None


async def create_round(
    db: AsyncSession, program: GrantProgram, data: dict[str, Any], actor: Actor
) -> GrantRound:
    await _check_reference(db, data["source_reference_id"])
    _check_dates(data.get("opens_on"), data.get("closes_on"))
    if await _title_taken(db, program.id, data["title"]):
        raise _conflict("title_taken", "This program already has a round with that name.")
    created = GrantRound(program_id=program.id, created_by=actor.user_id, **data)
    db.add(created)
    await db.flush()
    await _audit(
        db,
        "grant.round.create",
        actor,
        "grant_round",
        created.id,
        {"program_id": str(program.id), **_jsonable(data)},
    )
    return created


async def update_round(
    db: AsyncSession, found: GrantRound, data: dict[str, Any], actor: Actor
) -> GrantRound:
    await _check_reference(db, data["source_reference_id"])
    _check_dates(data.get("opens_on", found.opens_on), data.get("closes_on", found.closes_on))
    if "title" in data and await _title_taken(db, found.program_id, data["title"], found.id):
        raise _conflict("title_taken", "This program already has a round with that name.")
    before = {k: getattr(found, k) for k in data}
    for name, value in data.items():
        setattr(found, name, value)
    await db.flush()
    await _audit(
        db,
        "grant.round.update",
        actor,
        "grant_round",
        found.id,
        {
            "from": _jsonable(
                {k: str(v) if isinstance(v, uuid.UUID) else v for k, v in before.items()}
            ),
            "to": _jsonable(
                {k: str(v) if isinstance(v, uuid.UUID) else v for k, v in data.items()}
            ),
        },
    )
    return found


# --- Matches ---------------------------------------------------------------------------


async def record_matches(
    db: AsyncSession,
    project: Project,
    assessment_id: uuid.UUID,
    rule_sets: list[dict[str, Any]],
    findings: Sequence[matching.FindingLike],
    on: date,
) -> list[GrantMatch]:
    """One ``grant_match`` per active program whose rule set the assessment considered."""
    if project.vertical != Vertical.GRANT:
        return []
    by_key = {rs["rule_set_id"]: rs for rs in rule_sets}
    programs = list(
        (
            await db.execute(
                select(GrantProgram)
                .where(GrantProgram.status == ProgramStatus.ACTIVE)
                .order_by(GrantProgram.title)
            )
        ).scalars()
    )
    views = await _views(db, programs, on)
    decided = []
    for p in programs:
        entry = by_key.get(str(p.rule_set_id))
        if entry is None:  # rule set not published yet
            continue
        own = [f for f in findings if f.rule_set_id == p.rule_set_id]
        decision = matching.decide(entry, own)
        if decision is not None:
            decided.append((p, decision))
    decided.sort(key=lambda pd: STATUS_ORDER[pd[1].status])
    rows = []
    for ordinal, (p, d) in enumerate(decided, start=1):
        row = GrantMatch(
            organisation_id=project.organisation_id,
            assessment_id=assessment_id,
            program_id=p.id,
            round_id=views[p.id].current_round_id,
            ordinal=ordinal,
            status=d.status,
            confidence=d.confidence,
            criteria=d.criteria,
            missing_facts=d.missing_facts,
        )
        db.add(row)
        rows.append(row)
    await db.flush()
    return rows


async def matches_for(
    db: AsyncSession, assessment_id: uuid.UUID
) -> list[tuple[GrantMatch, ProgramView]]:
    rows = list(
        (
            await db.execute(
                select(GrantMatch)
                .where(GrantMatch.assessment_id == assessment_id)
                .order_by(GrantMatch.ordinal)
            )
        ).scalars()
    )
    if not rows:
        return []
    programs = list(
        (
            await db.execute(
                select(GrantProgram).where(GrantProgram.id.in_({r.program_id for r in rows}))
            )
        ).scalars()
    )
    views = await _views(db, programs, today())
    return [(r, views[r.program_id]) for r in rows]
