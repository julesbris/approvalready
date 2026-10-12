"""``/v1/guidance``: how to get each kind of approval (read-only reference data)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import AuthDep, DbDep
from app.modules.guidance import forms as official_forms
from app.modules.guidance import guides
from app.modules.guidance.forms import OfficialForm
from app.modules.guidance.guides import ApprovalGuide
from app.modules.projects.models import Vertical
from app.modules.regulatory.models import SourceReference, VerificationStatus

router = APIRouter(prefix="/v1/guidance", tags=["guidance"])


class GuideChecked(BaseModel):
    verified: bool
    verified_at: datetime | None


class ApprovalGuideOut(ApprovalGuide):
    checked: GuideChecked
    forms: list[OfficialForm]  # type: ignore[assignment]  # the forms themselves, not ids


@router.get("/forms", response_model=list[OfficialForm])
async def forms(_: AuthDep, vertical: Vertical | None = None) -> list[OfficialForm]:
    """Official forms with a direct link to each: the ones a product's findings, checklists
    and plan steps can name when ``vertical`` is given, otherwise all of them."""
    if vertical is None:
        return list(official_forms.library().forms)
    return official_forms.for_vertical(vertical)


@router.get("/approvals", response_model=list[ApprovalGuideOut])
async def approval_guides(
    _: AuthDep,
    db: DbDep,
    kind: Annotated[list[str] | None, Query(max_length=60)] = None,
    vertical: Vertical | None = None,
) -> list[ApprovalGuideOut]:
    """Guides for the approval kinds asked for (all of them when none are), in plan order,
    limited to one product's guides when ``vertical`` is given."""
    if kind:
        found = guides.for_kinds(kind, vertical)
    else:
        found = [g for g in guides.guides() if vertical is None or vertical in g.verticals]
    # A guide reads as checked once a person has verified its reference from the guides_au pack.
    rows = (
        await db.execute(
            select(SourceReference.section, SourceReference.verified_at).where(
                SourceReference.section.in_([g.reference_section for g in found]),
                SourceReference.verification_status == VerificationStatus.VERIFIED,
            )
        )
    ).all()
    verified: dict[str, datetime | None] = {}
    for section, at in rows:
        if section is None:
            continue
        latest = verified.get(section)
        verified[section] = max(latest, at) if latest and at else latest or at
    return [
        ApprovalGuideOut(
            **(g.model_dump() | {"forms": official_forms.by_ids(g.forms)}),
            checked=GuideChecked(
                verified=g.reference_section in verified,
                verified_at=verified.get(g.reference_section),
            ),
        )
        for g in found
    ]
