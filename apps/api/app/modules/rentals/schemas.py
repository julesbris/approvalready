from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.modules.rentals.models import (
    ApplicationStatus,
    InspectionKind,
    InspectionStatus,
    ItemCondition,
    ListingStatus,
    MaintenancePriority,
    MaintenanceStatus,
    RentPeriod,
    TenancyStatus,
)

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Count = Annotated[int, Field(ge=0, le=30)]
Cents = Annotated[int, Field(ge=0, le=10_000_000_000)]
PositiveCents = Annotated[int, Field(gt=0, le=10_000_000_000)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Rental and listing ----------------------------------------------------------------


class RentalUpdate(_In):
    bedrooms: Count | None = None
    bathrooms: Count | None = None
    parking: Count | None = None
    furnished: bool | None = None
    pets_considered: bool | None = None
    listing_status: ListingStatus | None = None
    headline: Short | None = None
    description: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)] | None
    ) = None
    rent_cents: PositiveCents | None = Field(
        default=None, description="The advertised rent: a fixed amount per rent period."
    )
    rent_period: RentPeriod | None = None
    available_from: date | None = None


class RentalOut(BaseModel):
    id: uuid.UUID | None = Field(description="Null until the rental is first saved.")
    project_id: uuid.UUID
    bedrooms: int | None
    bathrooms: int | None
    parking: int | None
    furnished: bool | None
    pets_considered: bool | None
    listing_status: ListingStatus
    headline: str | None
    description: str | None
    rent_cents: int | None
    rent_period: RentPeriod
    available_from: date | None
    applications: int
    current_tenancy_id: uuid.UUID | None
    open_maintenance: int
    upcoming_inspections: int
    updated_at: datetime | None


# --- Applications ----------------------------------------------------------------------


class ApplicationCheckOut(BaseModel):
    key: str
    label: str
    provided: bool | None = Field(description="Null until someone has looked.")


class ApplicationCreate(_In):
    applicant_name: Name
    applicant_contact: Short | None = None
    household_size: Annotated[int, Field(ge=1, le=30)] | None = None
    preferred_start_on: date | None = None
    received_on: date | None = Field(default=None, description="Defaults to today.")
    notes: Notes | None = None


class ApplicationUpdate(_In):
    status: ApplicationStatus | None = None
    checks: dict[str, bool | None] | None = Field(
        default=None, description="Check key → provided (true/false) or not looked at (null)."
    )
    notes: Notes | None = None


class ApplicationOut(BaseModel):
    id: uuid.UUID
    applicant_name: str
    applicant_contact: str | None
    household_size: int | None
    preferred_start_on: date | None
    received_on: date
    status: ApplicationStatus
    checks: list[ApplicationCheckOut]
    missing: list[str] = Field(description="Labels of the documents not provided yet.")
    notes: str | None
    tenancy_id: uuid.UUID | None
    created_at: datetime


# --- Tenancies -------------------------------------------------------------------------


class TenancyCreate(_In):
    tenant_names: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)
    ]
    tenant_contact: Short | None = None
    start_on: date
    end_on: date | None = Field(default=None, description="Leave out for a periodic agreement.")
    rent_cents: PositiveCents
    rent_period: RentPeriod = RentPeriod.WEEK
    bond_cents: Cents | None = None
    bond_lodged_on: date | None = None
    bond_reference: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] | None
    ) = None
    last_rent_increase_on: date | None = None
    next_rent_review_on: date | None = None
    notes: Notes | None = None


class TenancyUpdate(_In):
    tenant_names: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
        | None
    ) = None
    tenant_contact: Short | None = None
    start_on: date | None = None
    end_on: date | None = None
    rent_cents: PositiveCents | None = None
    rent_period: RentPeriod | None = None
    bond_cents: Cents | None = None
    bond_lodged_on: date | None = None
    bond_reference: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] | None
    ) = None
    last_rent_increase_on: date | None = None
    next_rent_review_on: date | None = None
    ended_on: date | None = Field(default=None, description="When the tenant moved out.")
    notes: Notes | None = None


class TenancyOut(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID | None
    tenant_names: str
    tenant_contact: str | None
    status: TenancyStatus
    start_on: date
    end_on: date | None
    periodic: bool
    rent_cents: int
    rent_period: RentPeriod
    bond_cents: int | None
    bond_lodged_on: date | None
    bond_reference: str | None
    bond_to_lodge: bool = Field(description="A bond was taken and no lodgement is recorded.")
    last_rent_increase_on: date | None
    next_rent_review_on: date | None
    ended_on: date | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


# --- Inspections -----------------------------------------------------------------------


class InspectionCreate(_In):
    kind: InspectionKind
    scheduled_at: datetime
    tenancy_id: uuid.UUID | None = None
    rooms: list[Label] | None = Field(
        default=None,
        max_length=30,
        description="Rooms to inspect; defaults from the rental's bedrooms and bathrooms.",
    )
    notes: Notes | None = None


class InspectionUpdate(_In):
    status: InspectionStatus | None = None
    scheduled_at: datetime | None = None
    notes: Notes | None = None


class InspectionItemCreate(_In):
    room: Label
    item: Label


class InspectionItemUpdate(_In):
    condition: ItemCondition | None = None
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None
    photo_document_ids: list[uuid.UUID] | None = Field(default=None, max_length=10)


class InspectionItemOut(BaseModel):
    id: uuid.UUID
    position: int
    room: str
    item: str
    condition: ItemCondition | None
    notes: str | None
    photo_document_ids: list[uuid.UUID]


class InspectionOut(BaseModel):
    id: uuid.UUID
    tenancy_id: uuid.UUID | None
    kind: InspectionKind
    status: InspectionStatus
    scheduled_at: datetime
    completed_at: datetime | None
    notes: str | None
    items_total: int
    items_checked: int
    created_at: datetime


class InspectionDetailOut(InspectionOut):
    project_id: uuid.UUID
    items: list[InspectionItemOut]


# --- Maintenance -----------------------------------------------------------------------


class MaintenanceCreate(_In):
    title: Name
    detail: Notes | None = None
    priority: MaintenancePriority = MaintenancePriority.ROUTINE
    reported_on: date | None = Field(default=None, description="Defaults to today.")
    reported_by: Short | None = None
    tenancy_id: uuid.UUID | None = None


class MaintenanceUpdate(_In):
    title: Name | None = None
    detail: Notes | None = None
    priority: MaintenancePriority | None = None
    status: MaintenanceStatus | None = None
    scheduled_on: date | None = None
    resolved_on: date | None = None
    tradesperson: Short | None = None
    cost_cents: Cents | None = None


class MaintenanceOut(BaseModel):
    id: uuid.UUID
    tenancy_id: uuid.UUID | None
    title: str
    detail: str | None
    priority: MaintenancePriority
    status: MaintenanceStatus
    reported_on: date
    reported_by: str | None
    scheduled_on: date | None
    resolved_on: date | None
    tradesperson: str | None
    cost_cents: int | None
    created_at: datetime
    updated_at: datetime
