from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=256)
    display_name: str = Field(min_length=1, max_length=120)


class EmailRequest(BaseModel):
    email: EmailStr


class TokenRequest(BaseModel):
    token: str = Field(min_length=16, max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=256)


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=16, max_length=200)
    password: str = Field(max_length=256)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class SwitchOrganisationRequest(BaseModel):
    organisation_id: uuid.UUID


class Accepted(BaseModel):
    """Same response whether or not the address is registered (no account enumeration)."""

    status: Literal["accepted"] = "accepted"


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    email_verified: bool


class MembershipOut(BaseModel):
    organisation_id: uuid.UUID
    name: str
    kind: str
    roles: list[str]


class SessionOut(BaseModel):
    user: UserOut
    active_organisation_id: uuid.UUID | None
    organisations: list[MembershipOut]
    # Permissions in the active organisation. For display only: the API re-checks every
    # request, so the web app must never treat this list as authorisation.
    permissions: list[str]
    csrf_token: str
    expires_at: datetime
    idle_expires_at: datetime
