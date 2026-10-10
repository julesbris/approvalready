"""Lead engine schemas.

``LeadPublicView`` is what a partner sees before claiming: built field by field from the
lead's whitelisted columns, never from the consent or the released contact, so a column
added later can't leak. Contact details appear only in ``ClaimOut`` (the claim response and
the partner's own claimed referrals), and only the fields the customer released.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, model_validator

from app.modules.entities.models import AustralianState
from app.modules.leads.models import (
    CreditKind,
    GstTreatment,
    LeadMatchStatus,
    LeadStatus,
    QuoteStatus,
    ReleasableField,
    Timing,
)
from app.modules.partners.schemas import _clean_phone

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]
Address = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=300)]
Summary = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
CategoryKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,59}$")]
Postcode = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9]{4}$")]
Place = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Council = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Customer: asking to be introduced -------------------------------------------------


class ContactIn(_In):
    """The details the customer is willing to share. Only the released ones are kept."""

    name: Name | None = None
    email: EmailStr | None = None
    phone: str | None = None
    site_address: Address | None = None

    @model_validator(mode="before")
    @classmethod
    def _phone(cls, data: Any) -> Any:
        if isinstance(data, dict) and "phone" in data:
            data = dict(data)
            data["phone"] = _clean_phone(data["phone"])
        return data


class LocationIn(_In):
    suburb: Place | None = None
    lga: Council | None = Field(default=None, description="Council (local government) area.")
    state: AustralianState
    postcode: Postcode


class ReferralIn(_In):
    """The customer's consent to be introduced, with exactly what they agreed to."""

    assessment_id: uuid.UUID
    consent_text_version_id: uuid.UUID = Field(
        description="The consent text shown (must be the current version)."
    )
    agreed: bool = Field(description="The customer ticked the consent box.")
    categories: list[CategoryKey] = Field(min_length=1, max_length=5)
    max_providers: int = Field(ge=1, le=3)
    fields_released: list[ReleasableField] = Field(min_length=1, max_length=4)
    contact: ContactIn
    location: LocationIn
    timing: Timing
    summary: Summary | None = Field(
        default=None,
        description="Shown to matched partners before they accept: no names or contact details.",
    )

    @model_validator(mode="after")
    def _shape(self) -> ReferralIn:
        if not self.agreed:
            raise ValueError("Tick the box to agree before we introduce you.")
        if len(set(self.categories)) != len(self.categories):
            raise ValueError("Each kind of work can be chosen once.")
        if len(set(self.fields_released)) != len(self.fields_released):
            raise ValueError("Each contact detail can be chosen once.")
        missing = [f.value for f in self.fields_released if getattr(self.contact, f.value) is None]
        if missing:
            raise ValueError(f"Fill in the details you chose to share: {', '.join(missing)}.")
        return self


class ConsentTextOut(BaseModel):
    id: uuid.UUID
    version: int
    title: str
    body: str


class ReferralCategoryOptionOut(BaseModel):
    key: str
    label: str
    description: str | None
    open_request: bool = Field(description="An introduction for this is already in progress.")


class ReferralOptionsOut(BaseModel):
    assessment_id: uuid.UUID
    consent: ConsentTextOut | None = Field(description="None until introductions are set up.")
    categories: list[ReferralCategoryOptionOut]
    max_providers: int
    contact: dict[str, str | None] = Field(description="Suggested contact details (prefill).")
    location: dict[str, str | None] = Field(description="Suggested location (prefill).")


class ClaimedPartnerOut(BaseModel):
    """What the customer sees of a partner that accepted their request (the partner's own
    public business details)."""

    name: str
    phone: str | None
    contact_email: str | None
    website: str | None
    claimed_at: datetime
    is_promoted: bool = Field(description="Paid placement: shown as Sponsored.")


class CustomerLeadOut(BaseModel):
    id: uuid.UUID
    category_key: str
    category_label: str
    status: LeadStatus
    max_claims: int
    claimed_count: int
    offered_count: int
    expires_at: datetime
    claims: list[ClaimedPartnerOut]


class ReferralOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    assessment_id: uuid.UUID
    consent_version: int
    categories: list[str]
    max_providers: int
    fields_released: list[str]
    contact: dict[str, Any]
    suburb: str | None
    lga: str | None
    state: str
    postcode: str
    timing: Timing
    summary: str | None
    granted_at: datetime
    withdrawn_at: datetime | None
    leads: list[CustomerLeadOut]


# --- Partner ---------------------------------------------------------------------------


class ScoreFactorOut(BaseModel):
    factor: str
    points: int
    max: int
    why: str


class FeeOut(BaseModel):
    included: bool = Field(description="One of the plan's referrals this month (no fee).")
    fee_cents: int
    currency: str = "AUD"
    included_used: int
    included_limit: int | None = Field(description="None: unlimited.")
    balance_cents: int
    can_afford: bool
    explanation: str


class LeadPublicView(BaseModel):
    """A referral as a partner sees it before accepting. No names or contact details."""

    model_config = ConfigDict(extra="forbid")

    match_id: uuid.UUID
    lead_id: uuid.UUID
    category_key: str
    category_label: str
    vertical: str
    suburb: str | None
    lga: str | None
    state: str
    postcode: str
    timing: Timing
    summary: str | None
    requirements: list[str]
    max_claims: int
    claims_left: int
    lead_status: LeadStatus
    status: LeadMatchStatus
    offered_at: datetime
    expires_at: datetime
    score: float
    score_breakdown: list[ScoreFactorOut]


class ClaimOut(BaseModel):
    """A referral the partner accepted: what they were given and what it cost."""

    match_id: uuid.UUID
    lead: LeadPublicView
    claimed_at: datetime
    fee_cents: int
    included: bool
    refunded_at: datetime | None
    released_fields: list[str]
    contact: dict[str, Any]


# --- Quotes (Milestone 23) --------------------------------------------------------------

LineText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
QuoteTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]
Scope = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=4000)]
Terms = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class QuoteLineIn(_In):
    description: LineText
    amount_cents: int = Field(ge=0, le=100_000_000)


class QuoteIn(_In):
    """A written quote for the job. Sending a new one replaces the one waiting."""

    title: QuoteTitle
    scope: Scope = Field(description="What the work includes (and what it doesn't).")
    line_items: list[QuoteLineIn] = Field(min_length=1, max_length=20)
    gst: GstTreatment = Field(
        description="INCLUDED: the amounts include GST. EXCLUDED: GST is added on top. "
        "NOT_REGISTERED: no GST applies."
    )
    valid_until: date
    start_estimate: LineText | None = Field(default=None, description="When work could start.")
    terms: Terms | None = Field(default=None, description="Deposit, payment and other terms.")


class QuoteLineOut(BaseModel):
    description: str
    amount_cents: int


class QuoteOut(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID
    version: int
    status: QuoteStatus
    expired: bool = Field(description="Still waiting, but its valid-until date has passed.")
    title: str
    scope: str
    line_items: list[QuoteLineOut]
    total_cents: int = Field(description="The sum of the line items, as entered.")
    gst: GstTreatment
    gst_cents: int
    total_inc_gst_cents: int = Field(description="What the customer would pay, with any GST.")
    valid_until: date
    start_estimate: str | None
    terms: str | None
    sent_at: datetime
    responded_at: datetime | None
    response_note: str | None


class QuotedPartnerOut(BaseModel):
    name: str
    phone: str | None
    contact_email: str | None
    website: str | None


class CustomerQuoteOut(QuoteOut):
    """A quote as the customer sees it, with the partner's public business details."""

    category_key: str
    category_label: str
    partner: QuotedPartnerOut


class QuoteAcceptIn(_In):
    decline_others: bool = Field(
        default=False,
        description="Also decline the other quotes waiting for this job and tell those partners.",
    )
    note: Note | None = None


class QuoteDeclineIn(_In):
    note: Note | None = Field(default=None, description="Shown to the partner.")


class LeadOfferOut(BaseModel):
    lead: LeadPublicView
    fee: FeeOut | None = Field(description="What accepting would cost (open offers only).")
    claim: ClaimOut | None
    quotes: list[QuoteOut] = Field(
        default_factory=list, description="Quotes this partner sent for it, newest first."
    )


class LeadDeclineIn(_In):
    reason: Note | None = None


class LeadOutcomeIn(_In):
    status: LeadMatchStatus = Field(description="CONTACTED, QUOTED, WON or LOST.")
    note: Note | None = None


class LeadPreferencesIn(_In):
    paused: bool | None = None
    max_open_leads: int | None = Field(default=None, ge=1, le=500)
    clear_max_open_leads: bool = Field(
        default=False, description="Remove the limit on referrals in progress."
    )


class LeadPreferencesOut(BaseModel):
    paused: bool
    max_open_leads: int | None
    in_progress: int


class CreditEntryOut(BaseModel):
    id: uuid.UUID
    kind: CreditKind
    delta_cents: int
    balance_after_cents: int
    note: str | None
    reference_type: str | None
    reference_id: uuid.UUID | None
    created_at: datetime


class CreditsOut(BaseModel):
    balance_cents: int
    currency: str = "AUD"
    included_used: int
    included_limit: int | None
    pack_price_cents: int | None = Field(description="Price of a credit pack, if on sale.")
    entries: list[CreditEntryOut]


# --- Staff -----------------------------------------------------------------------------


class LeadPriceIn(_In):
    amount_cents: int = Field(gt=0, le=1_000_000)


class LeadPriceOut(BaseModel):
    category_key: str
    category_label: str
    restricted: bool
    price_id: uuid.UUID | None
    amount_cents: int | None
    set_at: datetime | None


class CreditAdjustIn(_In):
    kind: CreditKind = Field(description="PROMO or ADJUSTMENT.")
    delta_cents: int = Field(ge=-1_000_000, le=1_000_000)
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=300)]


class StaffMatchOut(BaseModel):
    id: uuid.UUID
    claim_id: uuid.UUID | None
    partner_id: uuid.UUID
    partner_name: str
    rank: int
    score: float
    score_breakdown: list[ScoreFactorOut]
    status: LeadMatchStatus
    offered_at: datetime | None
    responded_at: datetime | None
    fee_cents: int | None
    included: bool | None
    claim_refunded_at: datetime | None


class StaffLeadOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    category_key: str
    category_label: str
    vertical: str
    suburb: str | None
    lga: str | None
    state: str
    postcode: str
    status: LeadStatus
    max_claims: int
    claimed_count: int
    expires_at: datetime
    matches: list[StaffMatchOut]


class RefundIn(_In):
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=300)]


class CreditStaffOut(BaseModel):
    partner_id: uuid.UUID
    balance_cents: int
    entries: list[CreditEntryOut]
