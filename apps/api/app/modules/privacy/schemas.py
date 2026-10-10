from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, EmailStr, Field, computed_field

from app.modules.privacy.models import (
    PolicyDocument,
    PrivacyRequestKind,
    PrivacyRequestSource,
    PrivacyRequestStatus,
)


class PolicyOut(BaseModel):
    document: PolicyDocument
    title: str
    path: str
    version: str


class AcceptPoliciesRequest(BaseModel):
    documents: list[PolicyDocument] = Field(min_length=1, max_length=len(PolicyDocument))


class CloseAccountRequest(BaseModel):
    password: str = Field(max_length=256)
    # Needed when two-step sign-in is on: an authenticator or recovery code.
    code: str | None = Field(default=None, max_length=64)


class PrivacyRequestIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    kind: PrivacyRequestKind
    details: str = Field(min_length=10, max_length=4000)


class PrivacyRequestCreated(BaseModel):
    reference: str
    due_at: datetime


class PrivacyRequestOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    name: str
    email: str
    kind: PrivacyRequestKind
    source: PrivacyRequestSource
    details: str
    status: PrivacyRequestStatus
    created_at: datetime
    due_at: datetime
    resolved_at: datetime | None
    resolution_note: str | None

    model_config = {"from_attributes": True}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def overdue(self) -> bool:
        """Still open past the 30-day answer date."""
        return self.status == PrivacyRequestStatus.OPEN and self.due_at < datetime.now(UTC)


class PrivacyRequestUpdate(BaseModel):
    status: PrivacyRequestStatus
    note: str = Field(default="", max_length=4000)
