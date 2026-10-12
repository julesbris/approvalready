"""``/v1/councils``: how to apply to each council, in every state we cover (read-only
reference data)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import AuthDep, DbDep
from app.core.errors import not_found
from app.modules.councils import directory, states
from app.modules.councils.directory import Council, CouncilFees, CouncilSource
from app.modules.guidance import forms as official_forms
from app.modules.guidance.forms import OfficialForm
from app.modules.regulatory.models import SourceReference, VerificationStatus

router = APIRouter(prefix="/v1/councils", tags=["councils"])


class CouncilSummary(BaseModel):
    key: str
    name: str
    state: str


class CouncilChecked(BaseModel):
    verified: bool
    verified_at: datetime | None


class CouncilOut(Council):
    checked: CouncilChecked
    general_steps: list[str]
    general_source: CouncilSource
    # The state's application forms every council uses, each with a direct link.
    forms: list[OfficialForm]
    # Fees the state sets for every council (when the council's own aren't listed).
    state_fees: CouncilFees | None
    # Where every council's applications are lodged, when the state runs one portal.
    state_portal: CouncilSource | None
    planning_scheme_label: str
    zoning_lookup_url: str | None


@router.get("", response_model=list[CouncilSummary])
async def list_councils(_: AuthDep) -> list[CouncilSummary]:
    return [CouncilSummary(key=c.key, name=c.name, state=c.state) for c in directory.councils()]


@router.get("/{key}", response_model=CouncilOut)
async def get_council(key: str, _: AuthDep, db: DbDep) -> CouncilOut:
    council = directory.by_key(key)
    if council is None:
        raise not_found("Council")
    # Checked once a person has verified the council's reference from its state's pack.
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
    state = states.for_state(council.state)
    return CouncilOut(
        **council.model_dump(),
        checked=CouncilChecked(verified=verified_at is not None, verified_at=verified_at),
        general_steps=list(state.general_steps) if state else [],
        general_source=state.source if state else council.sources[0],
        forms=official_forms.by_ids(state.forms) if state else [],
        state_fees=state.fees if state else None,
        state_portal=state.portal if state else None,
        planning_scheme_label=state.planning_scheme_label if state else "planning scheme",
        zoning_lookup_url=state.zoning_lookup_url if state else None,
    )
