"""``/v1/councils``: how to apply to each Queensland council (read-only reference data)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import AuthDep, DbDep
from app.core.errors import not_found
from app.modules.councils import directory
from app.modules.councils.directory import Council, CouncilSource
from app.modules.regulatory.models import SourceReference, VerificationStatus

router = APIRouter(prefix="/v1/councils", tags=["councils"])


class CouncilSummary(BaseModel):
    key: str
    name: str


class CouncilChecked(BaseModel):
    verified: bool
    verified_at: datetime | None


class CouncilOut(Council):
    checked: CouncilChecked
    general_steps: list[str]
    general_source: CouncilSource


@router.get("", response_model=list[CouncilSummary])
async def list_councils(_: AuthDep) -> list[CouncilSummary]:
    return [CouncilSummary(key=c.key, name=c.name) for c in directory.councils()]


@router.get("/{key}", response_model=CouncilOut)
async def get_council(key: str, _: AuthDep, db: DbDep) -> CouncilOut:
    council = directory.by_key(key)
    if council is None:
        raise not_found("Council")
    # CouncilChecked once a person has verified the council's reference from the councils_qld pack.
    verified_at = (
        await db.execute(
            select(SourceReference.verified_at)
            .where(
                SourceReference.section == council.reference_section,
                SourceReference.verification_status == VerificationStatus.VERIFIED,
            )
            .order_by(SourceReference.verified_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return CouncilOut(
        **council.model_dump(),
        checked=CouncilChecked(verified=verified_at is not None, verified_at=verified_at),
        general_steps=list(directory.GENERAL_STEPS),
        general_source=directory.GENERAL_SOURCE,
    )
