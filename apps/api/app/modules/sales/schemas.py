from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.modules.sales.models import EnquiryStatus, OfferStatus, SaleStatus, VaultCategory

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=1000)]
Cents = Annotated[int, Field(ge=0, le=10_000_000_000_00)]
PositiveCents = Annotated[int, Field(gt=0, le=10_000_000_000_00)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DisclosureState(StrEnum):
    NOT_STARTED = "NOT_STARTED"  # nothing marked for the disclosure yet
    PREPARING = "PREPARING"  # documents marked, not given yet
    GIVEN = "GIVEN"  # given to a buyer on a date
    NOT_NEEDED = "NOT_NEEDED"  # the seller recorded why none is needed


class SaleUpdate(_In):
    status: SaleStatus | None = None
    asking_price_cents: Cents | None = None
    price_guide: Short | None = None
    listed_on: date | None = None
    contract_on: date | None = None
    settlement_on: date | None = None
    notes: Notes | None = None


class DisclosureOut(BaseModel):
    state: DisclosureState
    given_on: date | None
    given_to: str | None
    not_needed_note: str | None
    document_ids: list[uuid.UUID] = Field(description="Vault documents marked for disclosure.")
    changed_since_given: bool = Field(
        description="Documents were added to or removed from the disclosure after it was given."
    )


class SaleOut(BaseModel):
    id: uuid.UUID | None = Field(description="Null until the sale is first saved.")
    project_id: uuid.UUID
    status: SaleStatus
    next_statuses: list[SaleStatus]
    asking_price_cents: int | None
    price_guide: str | None
    listed_on: date | None
    contract_on: date | None
    settlement_on: date | None
    notes: str | None
    disclosure: DisclosureOut
    offers: int
    open_enquiries: int
    updated_at: datetime | None


class DisclosureGive(_In):
    given_on: date
    given_to: Name = Field(description="The buyer (or their representative) it was given to.")


class DisclosureNotNeeded(_In):
    note: Reason = Field(description="Why no disclosure is needed, e.g. what the rules said.")


class SaleDocumentCreate(_In):
    uploaded_document_id: uuid.UUID
    category: VaultCategory
    title: Short | None = None
    in_disclosure: bool = False


class SaleDocumentUpdate(_In):
    category: VaultCategory | None = None
    title: Short | None = None
    in_disclosure: bool | None = None


class SaleDocumentOut(BaseModel):
    id: uuid.UUID
    uploaded_document_id: uuid.UUID
    category: VaultCategory
    title: str | None
    in_disclosure: bool
    filename: str
    size_bytes: int
    scan_status: str
    created_at: datetime


class OfferCreate(_In):
    buyer_name: Name
    buyer_contact: Short | None = None
    amount_cents: PositiveCents
    deposit_cents: Cents | None = None
    subject_to_finance: bool = False
    subject_to_inspection: bool = False
    settlement_days: Annotated[int, Field(ge=0, le=730)] | None = None
    conditions: Notes | None = None
    received_on: date | None = Field(default=None, description="Defaults to today.")
    expires_at: datetime | None = None


class OfferUpdate(_In):
    status: OfferStatus | None = None
    amount_cents: PositiveCents | None = None
    deposit_cents: Cents | None = None
    subject_to_finance: bool | None = None
    subject_to_inspection: bool | None = None
    settlement_days: Annotated[int, Field(ge=0, le=730)] | None = None
    conditions: Notes | None = None
    expires_at: datetime | None = None


class OfferOut(BaseModel):
    id: uuid.UUID
    buyer_name: str
    buyer_contact: str | None
    amount_cents: int
    deposit_cents: int | None
    subject_to_finance: bool
    subject_to_inspection: bool
    settlement_days: int | None
    conditions: str | None
    status: OfferStatus
    received_on: date
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class EnquiryCreate(_In):
    name: Name
    contact: Short | None = None
    channel: Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] | None = None
    message: Notes | None = None
    received_on: date | None = Field(default=None, description="Defaults to today.")


class EnquiryUpdate(_In):
    status: EnquiryStatus | None = None
    notes: Notes | None = None


class EnquiryOut(BaseModel):
    id: uuid.UUID
    name: str
    contact: str | None
    channel: str | None
    message: str | None
    status: EnquiryStatus
    received_on: date
    notes: str | None
    created_at: datetime
