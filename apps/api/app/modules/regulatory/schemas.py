from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.modules.regulatory.models import (
    JURISDICTION_PATTERN,
    MAX_SNAPSHOT_CHARS,
    CaptureMethod,
    CheckOutcome,
    CheckTrigger,
    ReviewAction,
    SourceOrganisationKind,
    SourceType,
    VerificationStatus,
)


def _text(max_length: int) -> object:
    return StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)


Text20 = Annotated[str, _text(20)]
Text100 = Annotated[str, _text(100)]
Text200 = Annotated[str, _text(200)]
Text300 = Annotated[str, _text(300)]
Text2000 = Annotated[str, _text(2000)]
Text10000 = Annotated[str, _text(10000)]
Jurisdiction = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=JURISDICTION_PATTERN)
]
Url = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=2000, pattern=r"^https?://\S+$")
]


def _blank_to_none(value: object) -> object:
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Organisations ---------------------------------------------------------------------


class SourceOrganisationCreate(_In):
    name: Text200
    kind: SourceOrganisationKind
    jurisdiction: Jurisdiction
    website: Url | None = None

    _blank = field_validator("website", mode="before")(_blank_to_none)


class SourceOrganisationUpdate(_In):
    name: Text200 | None = None
    kind: SourceOrganisationKind | None = None
    jurisdiction: Jurisdiction | None = None
    website: Url | None = None

    _blank = field_validator("website", mode="before")(_blank_to_none)


class SourceOrganisationOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: SourceOrganisationKind
    jurisdiction: str
    website: str | None
    created_at: datetime


# --- Documents -------------------------------------------------------------------------


class SourceDocumentCreate(_In):
    source_organisation_id: uuid.UUID
    jurisdiction: Jurisdiction
    title: Text300
    url: Url
    source_type: SourceType
    version_label: Text100 | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    licence: Text200 | None = None
    supersedes_id: uuid.UUID | None = None
    auto_check: bool = Field(
        default=True, description="Read the official address every week for changes."
    )

    _blank = field_validator("version_label", "licence", mode="before")(_blank_to_none)


class SourceDocumentUpdate(_In):
    jurisdiction: Jurisdiction | None = None
    title: Text300 | None = None
    url: Url | None = None
    source_type: SourceType | None = None
    version_label: Text100 | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    licence: Text200 | None = None
    supersedes_id: uuid.UUID | None = None
    auto_check: bool | None = None

    _blank = field_validator("version_label", "licence", mode="before")(_blank_to_none)


class SnapshotSummary(BaseModel):
    id: uuid.UUID
    retrieved_at: datetime
    captured_at: datetime
    content_hash: str = Field(description="SHA-256 of the captured text, hex.")
    characters: int
    capture_method: CaptureMethod = Field(
        description="MANUAL: pasted by staff. FETCHED: read from the official address."
    )


class SourceCheckOut(BaseModel):
    id: uuid.UUID
    checked_at: datetime
    trigger: CheckTrigger
    outcome: CheckOutcome
    outcome_label: str
    url: str
    final_url: str | None
    http_status: int | None
    content_type: str | None
    size_bytes: int | None
    snapshot_id: uuid.UUID | None
    error: str | None


class SourceDocumentOut(BaseModel):
    id: uuid.UUID
    source_organisation_id: uuid.UUID
    organisation_name: str
    jurisdiction: str
    title: str
    url: str
    source_type: SourceType
    version_label: str | None
    effective_from: date | None
    effective_to: date | None
    licence: str | None
    supersedes_id: uuid.UUID | None
    latest_snapshot: SnapshotSummary | None
    auto_check: bool
    last_check: SourceCheckOut | None
    reference_counts: dict[str, int] = Field(description="References by verification status.")
    created_at: datetime
    updated_at: datetime


class SnapshotCreate(_In):
    content_text: Annotated[str, StringConstraints(min_length=1, max_length=MAX_SNAPSHOT_CHARS)]
    retrieved_at: datetime = Field(description="When the content was retrieved from the source.")


class SnapshotOut(SnapshotSummary):
    content_text: str


class SnapshotCaptured(SnapshotOut):
    changed: bool = Field(
        description="False when the content matched the latest snapshot (nothing new stored)."
    )


# --- References ------------------------------------------------------------------------


class SourceReferenceCreate(_In):
    section: Text200 | None = None
    clause: Text100 | None = None
    page: Text20 | None = None
    extracted_text: Text10000
    interpretation: Text2000 | None = None

    _blank = field_validator("section", "clause", "page", "interpretation", mode="before")(
        _blank_to_none
    )


class SourceReferenceUpdate(_In):
    section: Text200 | None = None
    clause: Text100 | None = None
    page: Text20 | None = None
    extracted_text: Text10000 | None = None
    interpretation: Text2000 | None = None

    _blank = field_validator("section", "clause", "page", "interpretation", mode="before")(
        _blank_to_none
    )


class SourceReferenceOut(BaseModel):
    id: uuid.UUID
    source_document_id: uuid.UUID
    document_title: str
    organisation_name: str
    url: str
    citation: str
    section: str | None
    clause: str | None
    page: str | None
    extracted_text: str
    interpretation: str | None
    verification_status: VerificationStatus
    verified_by: uuid.UUID | None
    verified_at: datetime | None
    verified_snapshot_id: uuid.UUID | None
    last_reviewed_at: datetime | None
    next_review_due: date | None
    attention: list[str] = Field(description="Why this reference needs a reviewer's attention.")
    allowed_actions: list[str]
    rule_versions: int = Field(description="Rule versions citing this reference.")
    created_at: datetime
    updated_at: datetime


class SourceReview(_In):
    action: Literal["VERIFY", "DISPUTE", "SUPERSEDE", "REOPEN"]
    notes: Text2000 | None = None
    next_review_due: date | None = Field(
        default=None, description="VERIFY only. Defaults to a year from today."
    )

    _blank = field_validator("notes", mode="before")(_blank_to_none)


class ReviewEventOut(BaseModel):
    id: uuid.UUID
    action: ReviewAction
    from_status: VerificationStatus | None
    to_status: VerificationStatus
    reviewer_id: uuid.UUID | None
    reviewer_name: str | None
    notes: str | None
    occurred_at: datetime
