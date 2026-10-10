from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from app.modules.privacy.schemas import PolicyOut


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=256)
    display_name: str = Field(min_length=1, max_length=120)
    # Agreement to the current Terms of Use and Privacy Policy (Milestone 19); required.
    accept_terms: bool = False


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
    # Two-step sign-in (an authenticator app code after the password) is on.
    mfa_enabled: bool = False


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
    # The active organisation is the platform's, but staff pages stay closed until the user
    # turns on two-step sign-in and signs in with it (``permissions`` is empty meanwhile).
    staff_mfa_required: bool = False
    # Current Terms of Use / Privacy Policy versions this user hasn't agreed to yet
    # (Milestone 19). The web app asks for agreement while this is not empty.
    policies_to_accept: list[PolicyOut] = Field(default_factory=list)


class MfaChallengeOut(BaseModel):
    """The password was right; a code from the authenticator app (or a recovery code) is
    needed next, at ``POST /v1/auth/login/mfa``."""

    mfa_required: Literal[True] = True


class MfaCodeRequest(BaseModel):
    # Six digits from the app, or a recovery code (``abcd-efgh-jkmn-pqrs``).
    code: str = Field(min_length=6, max_length=40)


class MfaSetupRequest(BaseModel):
    password: str = Field(max_length=256)


class MfaDisableRequest(BaseModel):
    password: str = Field(max_length=256)
    code: str = Field(min_length=6, max_length=40)


class MfaStatusOut(BaseModel):
    enabled: bool
    enabled_at: datetime | None
    recovery_codes_left: int
    # Staff routes need two-step sign-in (STAFF_MFA_REQUIRED).
    required_for_staff: bool


class MfaSetupOut(BaseModel):
    secret: str
    otpauth_uri: str
    qr_svg: str


class RecoveryCodesOut(BaseModel):
    """Shown once. Each code signs in once in place of an authenticator code."""

    recovery_codes: list[str]
