from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.modules.billing.models import SubscriptionStatus
from app.modules.entities.models import AustralianState
from app.modules.partners.models import (
    PartnerApplicationStatus,
    PartnerCategoryStatus,
    PartnerCredentialKind,
    PartnerCredentialStatus,
    PartnerStatus,
    ServiceAreaKind,
)
from app.modules.projects.models import Vertical
from app.modules.tenancy.schemas import _clean_abn

Text200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Text100 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=1000)]
CategoryKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,59}$")]

MAX_CATEGORIES = 20
MAX_SERVICE_AREAS = 50
MAX_CREDENTIALS = 20

_PHONE = re.compile(r"^\+?[0-9 ()-]{6,30}$")


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _clean_website(value: object) -> object:
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
        if not re.match(r"^https?://", value, re.IGNORECASE):
            value = f"https://{value}"
        if not re.match(r"^https?://[^\s/?#]+\.[^\s/?#]+(\S*)$", value, re.IGNORECASE):
            raise ValueError("Enter a website address such as https://example.com.au")
    return value


def _clean_phone(value: object) -> object:
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
        if not _PHONE.match(value):
            raise ValueError("Enter a phone number using digits, spaces and brackets")
    return value


class PartnerDetailsIn(_In):
    """What customers will see about the partner (website, phone, email, description)."""

    website: str | None = Field(default=None, max_length=300)
    phone: str | None = None
    contact_email: EmailStr | None = None
    description: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=20, max_length=2000)]
        | None
    ) = None

    _website = field_validator("website", mode="before")(_clean_website)
    _phone = field_validator("phone", mode="before")(_clean_phone)

    @field_validator("contact_email", mode="before")
    @classmethod
    def _blank_email(cls, value: object) -> object:
        return None if value == "" else value


class PartnerServiceAreaIn(_In):
    kind: ServiceAreaKind
    state: AustralianState
    value: str | None = Field(
        default=None,
        max_length=120,
        description="A postcode or council area name. Not needed for a whole state.",
    )

    @model_validator(mode="after")
    def _shape(self) -> PartnerServiceAreaIn:
        if self.kind == ServiceAreaKind.STATE:
            self.value = str(self.state)
            return self
        value = " ".join((self.value or "").split())
        if self.kind == ServiceAreaKind.POSTCODE and not re.fullmatch(r"[0-9]{4}", value):
            raise ValueError("A postcode has 4 digits")
        if self.kind == ServiceAreaKind.LGA and not (2 <= len(value) <= 120):
            raise ValueError("Enter the council area's name")
        self.value = value
        return self


class PartnerCredentialIn(_In):
    kind: PartnerCredentialKind
    issuer: Text200 = Field(description="Who issued it: the licensing body or the insurer.")
    number: Text100 = Field(description="Licence, accreditation or policy number.")
    cover_cents: int | None = Field(
        default=None, gt=0, le=10_000_000_000, description="Insurance: the amount of cover."
    )
    expires_on: date | None = None
    category_keys: list[CategoryKey] = Field(
        default_factory=list,
        max_length=MAX_CATEGORIES,
        description="Categories this licence or accreditation covers.",
    )


class PartnerApplicationIn(PartnerDetailsIn):
    name: Text200 = Field(description="The business name customers will see.")
    abn: str
    categories: list[CategoryKey] = Field(min_length=1, max_length=MAX_CATEGORIES)
    service_areas: list[PartnerServiceAreaIn] = Field(min_length=1, max_length=MAX_SERVICE_AREAS)
    credentials: list[PartnerCredentialIn] = Field(default_factory=list, max_length=MAX_CREDENTIALS)
    declaration: bool = Field(
        description="The applicant confirms the details are true and they may act for the business."
    )

    _abn = field_validator("abn", mode="before")(_clean_abn)

    @model_validator(mode="after")
    def _consistent(self) -> PartnerApplicationIn:
        if not self.declaration:
            raise ValueError("Confirm the details are true and that you can act for the business")
        if not self.abn:
            raise ValueError("Enter your ABN")
        if not self.description:
            raise ValueError("Describe what your business does (at least 20 characters)")
        if len(set(self.categories)) != len(self.categories):
            raise ValueError("Each category can be chosen once")
        for c in self.credentials:
            if not set(c.category_keys) <= set(self.categories):
                raise ValueError("A credential can only cover categories you have chosen")
        return self


class PartnerProfileUpdate(PartnerDetailsIn):
    """Partner admins: contact details at any time; the name and ABN until approved."""

    name: Text200 | None = None
    abn: str | None = None

    _abn = field_validator("abn", mode="before")(_clean_abn)


class PartnerCategoryIn(_In):
    category_key: CategoryKey
    credential_id: uuid.UUID | None = None


class PartnerCategoryCredentialIn(_In):
    credential_id: uuid.UUID | None


class PartnerStatusIn(_In):
    status: PartnerStatus
    reason: Reason | None = Field(
        default=None, description="Needed to reject or suspend; the partner sees it."
    )


class PartnerCategoryCheckIn(_In):
    status: PartnerCategoryStatus
    notes: Note | None = Field(default=None, description="Needed to reject; the partner sees it.")


class PartnerCredentialCheckIn(_In):
    status: PartnerCredentialStatus
    notes: Note | None = Field(default=None, description="Needed to reject; the partner sees it.")


# --- Output ------------------------------------------------------------------------------


class PartnerCredentialOut(BaseModel):
    id: uuid.UUID
    kind: PartnerCredentialKind
    issuer: str
    number: str
    cover_cents: int | None
    expires_on: date | None
    status: PartnerCredentialStatus
    notes: str | None
    verified_at: datetime | None
    current: bool = Field(description="Checked and not expired today.")


class PartnerCategoryOut(BaseModel):
    id: uuid.UUID
    category_key: str
    label: str
    description: str
    verticals: list[Vertical]
    requires_credential: bool
    restricted: bool
    status: PartnerCategoryStatus
    credential_id: uuid.UUID | None
    notes: str | None
    counts: bool = Field(description="Whether it receives referrals now.")
    problems: list[str] = Field(
        description="Why it doesn't receive referrals (empty when it does)."
    )


class PartnerServiceAreaOut(BaseModel):
    id: uuid.UUID
    kind: ServiceAreaKind
    state: AustralianState
    value: str
    counts: bool = Field(description="Within the plan's number of service areas.")


class PartnerPlanLimitOut(BaseModel):
    feature: str
    description: str
    limit: int | None = Field(description="Null: unlimited (or no limit applies yet).")
    in_use: int


class PartnerPlanOut(BaseModel):
    name: str = Field(description='The plan\'s name; "Free" without a paid plan.')
    status: SubscriptionStatus | None = Field(description="The paid plan's status at Stripe.")
    current_period_end: datetime | None
    cancel_at_period_end: bool
    grace_ends_at: datetime | None = Field(
        description="Payment overdue: when the plan stops if the card isn't updated."
    )
    limits: list[PartnerPlanLimitOut]


class PartnerApplicationOut(BaseModel):
    id: uuid.UUID
    status: PartnerApplicationStatus
    submitted_at: datetime
    reviewed_at: datetime | None
    decision_notes: str | None
    submitted_payload: dict[str, Any] | None = Field(
        default=None, description="What was submitted (staff only)."
    )


class PartnerOut(BaseModel):
    id: uuid.UUID
    organisation_id: uuid.UUID
    name: str
    abn: str | None
    status: PartnerStatus
    status_reason: str | None
    status_changed_at: datetime | None
    submitted_at: datetime
    website: str | None
    phone: str | None
    contact_email: str | None
    description: str | None
    categories: list[PartnerCategoryOut]
    service_areas: list[PartnerServiceAreaOut]
    credentials: list[PartnerCredentialOut]
    applications: list[PartnerApplicationOut]
    plan: PartnerPlanOut | None = Field(description="Null when the plan can't be read here.")
    receiving_referrals: bool
    problems: list[str] = Field(description="What stops referrals reaching this partner.")
    details_locked: bool = Field(description="Name and ABN can no longer be changed here.")


class PartnerMemberOut(BaseModel):
    user_id: uuid.UUID
    display_name: str
    email: str
    roles: list[str]


class StaffPartnerOut(PartnerOut):
    members: list[PartnerMemberOut]


class PartnerSummaryOut(BaseModel):
    id: uuid.UUID
    organisation_id: uuid.UUID
    name: str
    abn: str | None
    status: PartnerStatus
    submitted_at: datetime
    categories: list[str] = Field(description="Category labels.")
    pending_categories: int
    unchecked_credentials: int
