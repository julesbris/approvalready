from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.modules.grants.models import MatchStatus, ProgramStatus, RoundStatus
from app.modules.regulatory.schemas import Jurisdiction, Text200, Text2000, Url, _blank_to_none
from app.modules.rules.models import KEY_PATTERN, Confidence

Text500 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
ProgramKey = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=100, pattern=KEY_PATTERN)
]
Cents = Annotated[int, Field(ge=0, le=100_000_000_000)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GrantProgramCreate(_In):
    key: ProgramKey
    title: Text200
    summary: Text2000
    administrator_id: uuid.UUID
    jurisdiction: Jurisdiction
    url: Url
    rule_set_id: uuid.UUID
    funding_summary: Text500 | None = None
    min_amount_cents: Cents | None = None
    max_amount_cents: Cents | None = None

    _blank = field_validator("funding_summary", mode="before")(_blank_to_none)


class GrantProgramUpdate(_In):
    title: Text200 | None = None
    summary: Text2000 | None = None
    url: Url | None = None
    funding_summary: Text500 | None = None
    min_amount_cents: Cents | None = None
    max_amount_cents: Cents | None = None
    status: ProgramStatus | None = None


class GrantRoundCreate(_In):
    title: Text200
    status: RoundStatus
    opens_on: date | None = None
    closes_on: date | None = None
    dates_note: Text500 | None = None
    source_reference_id: uuid.UUID

    _blank = field_validator("dates_note", mode="before")(_blank_to_none)


class GrantRoundUpdate(_In):
    """Change a round when its source changes. A new status or date must cite the
    reference it now comes from (the same one is fine if it was re-read)."""

    title: Text200 | None = None
    status: RoundStatus | None = None
    opens_on: date | None = None
    closes_on: date | None = None
    dates_note: Text500 | None = None
    source_reference_id: uuid.UUID


class RoundSourceOut(BaseModel):
    reference_id: uuid.UUID
    citation: str
    url: str
    verification_status: str


class GrantRoundOut(BaseModel):
    id: uuid.UUID
    program_id: uuid.UUID
    title: str
    status: RoundStatus = Field(description="What the source says.")
    state: RoundStatus = Field(
        description="The status as of today: an open round past its closing date is closed."
    )
    opens_on: date | None
    closes_on: date | None
    dates_note: str | None
    days_to_close: int | None
    closing_soon: bool
    check_source: bool = Field(
        description="The recorded status no longer fits the dates; staff should re-check."
    )
    source: RoundSourceOut
    updated_at: datetime


class AdministratorOut(BaseModel):
    id: uuid.UUID
    name: str


class GrantProgramOut(BaseModel):
    id: uuid.UUID
    key: str
    title: str
    summary: str
    administrator: AdministratorOut
    jurisdiction: str
    url: str
    rule_set_id: uuid.UUID
    rule_set_key: str
    funding_summary: str | None
    min_amount_cents: int | None
    max_amount_cents: int | None
    status: ProgramStatus
    rounds: list[GrantRoundOut]
    current_round_id: uuid.UUID | None


class MatchCriterionOut(BaseModel):
    kind: str = Field(description="CRITERION, or WHO_CAN_APPLY for the program's scope.")
    finding_id: uuid.UUID | None = None
    rule_key: str | None = None
    title: str
    result: str = Field(description="MATCH: met. NO_MATCH: not met. UNKNOWN: unanswered.")
    outcome: str | None = None
    missing_facts: list[str] = Field(default_factory=list)


class GrantMatchOut(BaseModel):
    id: uuid.UUID
    status: MatchStatus
    confidence: Confidence
    criteria: list[MatchCriterionOut]
    missing_facts: list[str]
    round_id_at_assessment: uuid.UUID | None
    program: GrantProgramOut

    @classmethod
    def criteria_from(cls, rows: list[dict[str, Any]]) -> list[MatchCriterionOut]:
        return [MatchCriterionOut.model_validate(c) for c in rows]
