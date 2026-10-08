from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.modules.entities.models import (
    AustralianState,
    EmployeeBand,
    EntityType,
    OwnershipRole,
    Propulsion,
    TurnoverBand,
    VesselType,
)
from app.modules.tenancy.schemas import is_valid_abn

Text200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
OptText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None
ShortCode = Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)] | None
Rego = Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)] | None


def is_valid_acn(acn: str) -> bool:
    """Australian Company Number check digit (ASIC: weights 8..1, complement of sum mod 10)."""
    if len(acn) != 9 or not acn.isdigit():
        return False
    total = sum(int(d) * w for d, w in zip(acn[:8], range(8, 0, -1), strict=True))
    return (10 - total % 10) % 10 == int(acn[8])


def _blank_to_none(value: object) -> object:
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AddressIn(_In):
    line1: Text200
    line2: OptText = None
    suburb: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    state: AustralianState
    postcode: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9]{4}$")]

    _blank = field_validator("line2", mode="before")(_blank_to_none)


class AddressOut(BaseModel):
    line1: str
    line2: str | None
    suburb: str
    state: str
    postcode: str
    lga_code: str | None


class PropertyCreate(_In):
    address: AddressIn
    relationship: OwnershipRole = OwnershipRole.OWNER
    lot_plan: ShortCode = None
    title_reference: ShortCode = None
    land_area_m2: Decimal | None = Field(default=None, gt=0, le=10**10, decimal_places=2)

    _blank = field_validator("lot_plan", "title_reference", mode="before")(_blank_to_none)


class PropertyUpdate(_In):
    address: AddressIn | None = None
    lot_plan: ShortCode = None
    title_reference: ShortCode = None
    land_area_m2: Decimal | None = Field(default=None, gt=0, le=10**10, decimal_places=2)

    _blank = field_validator("lot_plan", "title_reference", mode="before")(_blank_to_none)


class PropertyOut(BaseModel):
    id: uuid.UUID
    address: AddressOut
    relationships: list[str]
    lot_plan: str | None
    title_reference: str | None
    land_area_m2: Decimal | None
    created_at: datetime
    updated_at: datetime


class VesselFields(_In):
    hull_material: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] | None
    ) = None
    propulsion: Propulsion | None = None
    length_m: Decimal | None = Field(default=None, gt=0, le=500, decimal_places=2)
    max_passengers: int | None = Field(default=None, ge=0, le=10_000)
    crew: int | None = Field(default=None, ge=0, le=1_000)
    operating_area: OptText = None
    activity: OptText = None
    uvi: Rego = None
    hin: Rego = None
    state_rego: Rego = None

    _blank = field_validator(
        "hull_material", "operating_area", "activity", "uvi", "hin", "state_rego", mode="before"
    )(_blank_to_none)


class VesselCreate(VesselFields):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    vessel_type: VesselType


class VesselUpdate(VesselFields):
    name: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
        | None
    ) = None
    vessel_type: VesselType | None = None


class VesselOut(BaseModel):
    id: uuid.UUID
    name: str
    vessel_type: str
    length_m: Decimal | None
    hull_material: str | None
    propulsion: str | None
    max_passengers: int | None
    crew: int | None
    operating_area: str | None
    activity: str | None
    uvi: str | None
    hin: str | None
    state_rego: str | None
    created_at: datetime
    updated_at: datetime


class BusinessFields(_In):
    trading_name: OptText = None
    abn: str | None = None
    acn: str | None = None
    gst_registered: bool | None = None
    established_on: date | None = None
    employee_band: EmployeeBand | None = None
    turnover_band: TurnoverBand | None = None
    anzsic_code: Annotated[str, StringConstraints(pattern=r"^[0-9]{1,4}$")] | None = None
    address: AddressIn | None = None

    _blank = field_validator("trading_name", "anzsic_code", mode="before")(_blank_to_none)

    @field_validator("abn", mode="before")
    @classmethod
    def _abn(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.replace(" ", "")
            if value == "":
                return None
            if not is_valid_abn(value):
                raise ValueError("Enter a valid 11-digit ABN")
        return value

    @field_validator("acn", mode="before")
    @classmethod
    def _acn(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.replace(" ", "")
            if value == "":
                return None
            if not is_valid_acn(value):
                raise ValueError("Enter a valid 9-digit ACN")
        return value


class BusinessCreate(BusinessFields):
    legal_name: Text200
    entity_type: EntityType


class BusinessUpdate(BusinessFields):
    legal_name: Text200 | None = None
    entity_type: EntityType | None = None


class BusinessOut(BaseModel):
    id: uuid.UUID
    legal_name: str
    trading_name: str | None
    abn: str | None
    acn: str | None
    entity_type: str
    gst_registered: bool | None
    established_on: date | None
    employee_band: str | None
    turnover_band: str | None
    anzsic_code: str | None
    address: AddressOut | None
    created_at: datetime
    updated_at: datetime
