"""Project plan API shapes."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.modules.plans.models import PlanItemStatus

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Owner = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]
SectionKey = Annotated[str, StringConstraints(min_length=1, max_length=200)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanOfferOut(BaseModel):
    on_sale: bool = Field(description="A price is set and payments are on: starting it charges.")
    price_cents: int | None
    currency: str | None
    product_name: str
    product_description: str
    included_in_membership: bool = Field(
        default=False, description="The organisation's ApprovalReady Plus includes it."
    )
    membership_on_sale: bool = Field(
        default=False, description="ApprovalReady Plus (which includes plans) can be bought."
    )


class PlanFeeOut(BaseModel):
    label: str
    amount: str
    note: str | None = None


class PlanContactOut(BaseModel):
    name: str
    phone: str | None = None
    email: str | None = None
    url: str | None = None
    hours: str | None = None
    note: str | None = None


class PlanSourceOut(BaseModel):
    title: str
    url: str


class PlanDocumentOut(BaseModel):
    id: uuid.UUID
    filename: str


class PlanPartnerOut(BaseModel):
    id: uuid.UUID
    name: str
    phone: str | None
    email: str | None
    website: str | None


class SuggestedPartnerOut(PlanPartnerOut):
    description: str | None
    why: str
    introduced: bool = Field(description="Accepted the customer's introduction request.")


class PlanHelpOut(BaseModel):
    key: str
    label: str
    description: str
    introduction_open: bool = Field(
        description="An introduction request for this kind of help is in progress."
    )
    partners: list[SuggestedPartnerOut]


class PlanStepOut(BaseModel):
    id: uuid.UUID
    section_key: str
    position: int
    kind: str
    title: str
    detail: str | None
    timeframe: str | None
    cost: str | None
    link_url: str | None
    link_label: str | None
    owner: str | None
    assignee_user_id: uuid.UUID | None
    due_on: date | None
    status: PlanItemStatus
    completed_at: datetime | None
    note: str | None
    documents: list[PlanDocumentOut]
    partner: PlanPartnerOut | None
    editable: bool = Field(description="One of the customer's own steps (rename or delete).")


class PlanSectionOut(BaseModel):
    key: str
    kind: str
    title: str
    authority: str | None = None
    summary: str | None = None
    certainty_label: str | None = None
    timeframe: str | None = None
    cost_summary: str | None = None
    fees: list[PlanFeeOut] = []
    contacts: list[PlanContactOut] = []
    watch_out: list[str] = []
    sources: list[PlanSourceOut] = []
    gaps: list[str] = []
    checked_on: date | None = None
    verified: bool = False
    help: list[PlanHelpOut] = Field(default=[], description="Who can help, with partners.")
    steps: list[PlanStepOut]
    done: int
    total: int
    starts_on: date | None
    ends_on: date | None


class PlanProgressOut(BaseModel):
    total: int
    done: int
    percent: int
    overdue: int
    due_this_week: int
    next_item_id: uuid.UUID | None
    finish_on: date | None


class ProjectPlanOut(BaseModel):
    status: Literal["NONE", "PAYMENT_PENDING", "ACTIVE"]
    offer: PlanOfferOut
    id: uuid.UUID | None = None
    assessment_id: uuid.UUID | None = None
    starts_on: date | None = None
    activated_at: datetime | None = None
    complimentary: bool = False
    progress: PlanProgressOut | None = None
    sections: list[PlanSectionOut] = []


class PlanStartOut(BaseModel):
    plan: ProjectPlanOut
    checkout_url: str | None = Field(description="Pay here; the plan starts once paid.")


class PlanCheckoutOut(BaseModel):
    url: str


class PlanStepCreate(_In):
    title: Title
    detail: Text | None = None
    section_key: SectionKey | None = Field(
        default=None, description="A part of the plan; defaults to your own steps."
    )
    due_on: date | None = None
    owner: Owner | None = None
    assignee_user_id: uuid.UUID | None = None


class PlanStepUpdate(_In):
    title: Title | None = None
    status: PlanItemStatus | None = None
    due_on: date | None = None
    owner: Owner | None = None
    assignee_user_id: uuid.UUID | None = None
    note: Text | None = None
    document_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)


class FollowUpCreate(_In):
    partner_id: uuid.UUID
    section_key: SectionKey | None = None
    due_on: date | None = Field(default=None, description="Defaults to three days from today.")
    remind: bool = Field(default=True, description="Email a reminder that morning.")
