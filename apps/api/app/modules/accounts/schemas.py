from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class AccountSearch(BaseModel):
    """Search by email, name, business name or ABN. Sent in the body, not the address, so
    customers' email addresses stay out of logs."""

    query: str = Field(default="", max_length=200)
    status: Literal["ACTIVE", "SUSPENDED", "UNVERIFIED", "CLOSED", "STAFF"] | None = None


class AccountSummary(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    status: str
    email_verified: bool
    mfa_enabled: bool
    created_at: datetime
    last_login_at: datetime | None
    closed: bool
    # The account's highest platform role (STAFF, ADMIN, SUPERADMIN), if any.
    platform_role: str | None
    organisations: int


class AccountMembership(BaseModel):
    organisation_id: uuid.UUID
    name: str
    kind: str
    organisation_status: str
    abn: str | None
    member_status: str
    roles: list[str]
    joined_at: datetime


class AccountSession(BaseModel):
    id: uuid.UUID
    surface: str
    ip: str | None
    user_agent: str | None
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime


class AccountEvent(BaseModel):
    seq: int
    occurred_at: datetime
    action: str
    # Who did it: the account itself, someone else (named by email when we still know it),
    # or the system (no actor).
    by: Literal["self", "other", "system"]
    actor_email: str | None
    ip: str | None
    details: dict[str, Any]


class StaffNoteOut(BaseModel):
    id: uuid.UUID
    kind: Literal["NOTE", "CALL", "EMAIL"]
    subject: str | None
    body: str
    project_reference: str | None
    created_at: datetime
    # Who wrote it (null once that staff account is gone).
    author_name: str | None
    # Whether the signed-in staff member may delete it (the API checks again).
    can_delete: bool


class AccountDetail(AccountSummary):
    password_set: bool
    password_changed_at: datetime | None
    recovery_codes_left: int
    memberships: list[AccountMembership]
    sessions: list[AccountSession]
    events: list[AccountEvent]
    # What the signed-in staff member may do to this account (the API checks again).
    allowed_actions: list[str]
    # Staff notes, calls and emails, newest first.
    notes: list[StaffNoteOut]
    # Whether the signed-in staff member may add a note or email this person.
    can_contact: bool


class AccountActionIn(BaseModel):
    action: Literal[
        "resend_verification",
        "send_password_reset",
        "sign_out_everywhere",
        "reset_two_step",
        "suspend",
        "restore",
    ]
    # Required for reset_two_step and suspend; saved in the audit log.
    reason: str = Field(default="", max_length=500)


class AccountActionOut(BaseModel):
    message: str
    account: AccountDetail


class StaffNoteIn(BaseModel):
    kind: Literal["NOTE", "CALL"] = "NOTE"
    body: str = Field(min_length=1, max_length=4000)
    project_reference: str | None = Field(default=None, max_length=40)


class StaffEmailIn(BaseModel):
    """An email from staff to the person, sent from the team address. A copy is kept as a
    note on the account."""

    subject: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=8000)
    project_reference: str | None = Field(default=None, max_length=40)
