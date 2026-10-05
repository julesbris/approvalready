from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

_ABN_WEIGHTS = (10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19)


def is_valid_abn(abn: str) -> bool:
    """Australian Business Number checksum (ATO algorithm: subtract 1 from the first digit,
    weight the digits, and the weighted sum must be divisible by 89)."""
    if len(abn) != 11 or not abn.isdigit():
        return False
    digits = [int(c) for c in abn]
    digits[0] -= 1
    return sum(d * w for d, w in zip(digits, _ABN_WEIGHTS, strict=True)) % 89 == 0


def _clean_abn(value: object) -> object:
    if isinstance(value, str):
        value = value.replace(" ", "")
        if value == "":
            return None
        if not is_valid_abn(value):
            raise ValueError("Enter a valid 11-digit ABN")
    return value


class OrganisationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["BUSINESS", "PROFESSIONAL_PRACTICE"]
    abn: str | None = None

    _abn = field_validator("abn", mode="before")(_clean_abn)


class OrganisationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    abn: str | None = None

    _abn = field_validator("abn", mode="before")(_clean_abn)


class OrganisationOut(BaseModel):
    id: uuid.UUID
    kind: str
    name: str
    abn: str | None
    status: str
    created_at: datetime
    roles: list[str]
    permissions: list[str]


class MemberOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    display_name: str
    roles: list[str]
    joined_at: datetime


class MemberRolesUpdate(BaseModel):
    roles: list[str] = Field(min_length=1, max_length=10)


class InvitationCreate(BaseModel):
    email: EmailStr
    roles: list[str] = Field(min_length=1, max_length=10)


class InvitationOut(BaseModel):
    id: uuid.UUID
    email: str
    roles: list[str]
    expires_at: datetime
    created_at: datetime


class InvitationAccept(BaseModel):
    token: str = Field(min_length=16, max_length=200)


class AuditEventOut(BaseModel):
    seq: int
    id: uuid.UUID
    occurred_at: datetime
    action: str
    actor_user_id: uuid.UUID | None
    target_type: str | None
    target_id: str | None
    details: dict[str, Any]


class AuditChainOut(BaseModel):
    ok: bool
    checked: int
    first_bad_seq: int | None
