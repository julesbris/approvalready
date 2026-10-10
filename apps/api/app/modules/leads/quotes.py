"""Quotes (Milestone 23): a partner who accepted a referral sends the customer a written
quote through the platform, and the customer accepts or declines it.

* Only a partner who claimed the lead, while the job is still in progress with them
  (accepted, contacted or quoted), can send one. Sending moves their referral to QUOTED.
* A quote never changes once sent (database trigger). A revision is a new version and the
  one waiting is superseded, so the customer always sees one current quote per partner.
* A quote waits until its valid-until date (Brisbane). After that it reads as expired and
  can't be accepted; the partner can send a new one.
* Accepting marks the partner's referral WON. The customer may also decline the other
  quotes waiting for the same job: those partners' referrals become LOST. Declining one
  quote leaves the referral QUOTED, so the partner can revise it.
* Accepting tells the partner the customer wants to go ahead. The agreement for the work is
  between them: ApprovalReady isn't a party to it and takes no payment for it.

Lock order is the lead engine's: the lead, then the match, then the quotes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, not_found
from app.modules.assessments.service import assessment_date
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.leads.models import (
    WORKING,
    GstTreatment,
    Lead,
    LeadMatch,
    LeadMatchStatus,
    LeadQuote,
    QuoteStatus,
)
from app.modules.leads.schemas import (
    CustomerQuoteOut,
    QuoteAcceptIn,
    QuotedPartnerOut,
    QuoteIn,
    QuoteLineOut,
    QuoteOut,
)
from app.modules.leads.service import Offer, _transition, ensure_customer_open, get_offer
from app.modules.marketplace.models import MarketplaceCategory
from app.modules.partners.models import PartnerOrganisation
from app.modules.projects.models import Project
from app.modules.tenancy.models import Organisation

MAX_VALID_DAYS = 180
CHOSE_ANOTHER = "The customer chose another quote."


def _conflict(code: str, message: str) -> ApiError:
    return ApiError(status.HTTP_409_CONFLICT, code, message)


def gst_amounts(total_cents: int, gst: str) -> tuple[int, int]:
    """(GST in cents, total including GST), rounded half up to the cent."""
    if gst == GstTreatment.INCLUDED:
        return (2 * total_cents + 11) // 22, total_cents
    if gst == GstTreatment.EXCLUDED:
        tax = (total_cents + 5) // 10
        return tax, total_cents + tax
    return 0, total_cents


def is_expired(quote: LeadQuote, today: date) -> bool:
    return quote.status == QuoteStatus.SENT and quote.valid_until < today


def quote_out(quote: LeadQuote, today: date) -> QuoteOut:
    return QuoteOut(**_fields(quote, today))


def _fields(quote: LeadQuote, today: date) -> dict[str, object]:
    tax, inc = gst_amounts(quote.total_cents, quote.gst)
    return {
        "id": quote.id,
        "lead_id": quote.lead_id,
        "version": quote.version,
        "status": quote.status,
        "expired": is_expired(quote, today),
        "title": quote.title,
        "scope": quote.scope,
        "line_items": [QuoteLineOut(**item) for item in quote.line_items],
        "total_cents": quote.total_cents,
        "gst": quote.gst,
        "gst_cents": tax,
        "total_inc_gst_cents": inc,
        "valid_until": quote.valid_until,
        "start_estimate": quote.start_estimate,
        "terms": quote.terms,
        "sent_at": quote.created_at,
        "responded_at": quote.responded_at,
        "response_note": quote.response_note,
    }


async def for_match(db: AsyncSession, match_id: uuid.UUID) -> list[LeadQuote]:
    return list(
        (
            await db.execute(
                select(LeadQuote)
                .where(LeadQuote.lead_match_id == match_id)
                .order_by(LeadQuote.version.desc())
            )
        ).scalars()
    )


async def _waiting(
    db: AsyncSession, *, match_id: uuid.UUID | None = None, lead_id: uuid.UUID | None = None
) -> list[LeadQuote]:
    query = select(LeadQuote).where(LeadQuote.status == QuoteStatus.SENT).with_for_update()
    if match_id is not None:
        query = query.where(LeadQuote.lead_match_id == match_id)
    if lead_id is not None:
        query = query.where(LeadQuote.lead_id == lead_id)
    return list((await db.execute(query.order_by(LeadQuote.created_at))).scalars())


def _close(
    quote: LeadQuote,
    to: QuoteStatus,
    *,
    now: datetime,
    actor_id: uuid.UUID | None,
    note: str | None,
) -> None:
    quote.status = to
    quote.responded_at = now
    quote.responded_by = actor_id
    quote.response_note = note


async def withdraw_waiting(
    db: AsyncSession, match: LeadMatch, *, actor_id: uuid.UUID | None, now: datetime, note: str
) -> None:
    """The partner recorded the job as lost: a quote still waiting is taken back."""
    for quote in await _waiting(db, match_id=match.id):
        _close(quote, QuoteStatus.WITHDRAWN, now=now, actor_id=actor_id, note=note)
    await db.flush()


# --- Partner ---------------------------------------------------------------------------


async def send(
    db: AsyncSession,
    partner: PartnerOrganisation,
    match_id: uuid.UUID,
    data: QuoteIn,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
    now: datetime,
) -> tuple[Offer, LeadQuote]:
    offer = await get_offer(db, partner, match_id, lock=True)
    if offer.claim is None:
        raise _conflict("not_claimed", "Accept this referral before sending a quote.")
    await ensure_customer_open(db, offer.lead)
    if offer.match.status not in WORKING:
        raise _conflict(
            "job_finished", "This job is marked won or lost, so you can't quote for it now."
        )
    today = assessment_date(now)
    if data.valid_until < today:
        raise ApiError(422, "invalid_valid_until", "The valid-until date has already passed.")
    if data.valid_until > today + timedelta(days=MAX_VALID_DAYS):
        raise ApiError(
            422,
            "invalid_valid_until",
            f"A quote can be valid for up to {MAX_VALID_DAYS} days.",
        )
    for previous in await _waiting(db, match_id=offer.match.id):
        _close(
            previous,
            QuoteStatus.SUPERSEDED,
            now=now,
            actor_id=actor_id,
            note="Replaced by a revised quote.",
        )
    await db.flush()
    version = (
        await db.execute(
            select(func.coalesce(func.max(LeadQuote.version), 0)).where(
                LeadQuote.lead_match_id == offer.match.id
            )
        )
    ).scalar_one() + 1
    items = [
        {"description": i.description, "amount_cents": i.amount_cents} for i in data.line_items
    ]
    quote = LeadQuote(
        lead_match_id=offer.match.id,
        lead_id=offer.lead.id,
        partner_organisation_id=partner.id,
        version=version,
        status=QuoteStatus.SENT,
        title=data.title,
        scope=data.scope,
        line_items=items,
        total_cents=sum(i["amount_cents"] for i in items),
        gst=data.gst,
        valid_until=data.valid_until,
        start_estimate=data.start_estimate,
        terms=data.terms,
        sent_by=actor_id,
        created_at=now,
    )
    db.add(quote)
    if offer.match.status != LeadMatchStatus.QUOTED:
        await _transition(
            db, offer.match, LeadMatchStatus.QUOTED, actor_id=actor_id, note="Quote sent."
        )
    await db.flush()
    await audit.record(
        db,
        "quote.sent",
        actor_user_id=actor_id,
        organisation_id=partner.organisation_id,
        target_type="lead_quote",
        target_id=quote.id,
        meta=meta,
        details={"lead_id": str(offer.lead.id), "version": version, "total": quote.total_cents},
    )
    return offer, quote


async def withdraw(
    db: AsyncSession,
    partner: PartnerOrganisation,
    match_id: uuid.UUID,
    quote_id: uuid.UUID,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
    now: datetime,
) -> Offer:
    offer = await get_offer(db, partner, match_id, lock=True)
    quote = next((q for q in await _waiting(db, match_id=offer.match.id) if q.id == quote_id), None)
    if quote is None:
        raise _conflict(
            "not_waiting", "Only a quote still waiting for the customer can be withdrawn."
        )
    _close(
        quote, QuoteStatus.WITHDRAWN, now=now, actor_id=actor_id, note="Withdrawn by the partner."
    )
    await db.flush()
    await audit.record(
        db,
        "quote.withdrawn",
        actor_user_id=actor_id,
        organisation_id=partner.organisation_id,
        target_type="lead_quote",
        target_id=quote.id,
        meta=meta,
    )
    return offer


# --- Customer --------------------------------------------------------------------------


@dataclass(frozen=True)
class CustomerQuote:
    quote: LeadQuote
    lead: Lead
    category: MarketplaceCategory
    partner: PartnerOrganisation
    organisation: Organisation

    def out(self, today: date) -> CustomerQuoteOut:
        return CustomerQuoteOut(
            **_fields(self.quote, today),
            category_key=self.category.key,
            category_label=self.category.label,
            partner=QuotedPartnerOut(
                name=self.organisation.name,
                phone=self.partner.phone,
                contact_email=self.partner.contact_email,
                website=self.partner.website,
            ),
        )


def _customer_query(project: Project):  # type: ignore[no-untyped-def]
    return (
        select(LeadQuote, Lead, MarketplaceCategory, PartnerOrganisation, Organisation)
        .join(Lead, Lead.id == LeadQuote.lead_id)
        .join(MarketplaceCategory, MarketplaceCategory.id == Lead.category_id)
        .join(PartnerOrganisation, PartnerOrganisation.id == LeadQuote.partner_organisation_id)
        .join(Organisation, Organisation.id == PartnerOrganisation.organisation_id)
        .where(Lead.organisation_id == project.organisation_id, Lead.project_id == project.id)
    )


async def for_project(db: AsyncSession, project: Project) -> list[CustomerQuote]:
    """Every current quote for the project's referrals (superseded versions left out),
    newest first."""
    rows = await db.execute(
        _customer_query(project)
        .where(LeadQuote.status != QuoteStatus.SUPERSEDED)
        .order_by(LeadQuote.created_at.desc())
    )
    return [CustomerQuote(*row) for row in rows]


async def _get_for_customer(
    db: AsyncSession, project: Project, quote_id: uuid.UUID
) -> CustomerQuote:
    row = (await db.execute(_customer_query(project).where(LeadQuote.id == quote_id))).one_or_none()
    if row is None:
        raise not_found("Quote")
    found = CustomerQuote(*row)
    # Lead, then match, then quote: the order every lead writer takes.
    await db.execute(select(Lead.id).where(Lead.id == found.lead.id).with_for_update())
    await db.execute(
        select(LeadMatch.id).where(LeadMatch.id == found.quote.lead_match_id).with_for_update()
    )
    await db.refresh(found.quote, with_for_update=True)
    return found


async def _check_waiting(found: CustomerQuote, today: date) -> None:
    if found.quote.status != QuoteStatus.SENT:
        raise _conflict("not_waiting", "This quote has already been answered or withdrawn.")
    if is_expired(found.quote, today):
        raise _conflict(
            "quote_expired",
            "This quote's valid-until date has passed. Ask the partner for a new one.",
        )


@dataclass(frozen=True)
class Answered:
    quote: LeadQuote
    accepted: bool


async def accept(
    db: AsyncSession,
    project: Project,
    quote_id: uuid.UUID,
    data: QuoteAcceptIn,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
    now: datetime,
) -> list[Answered]:
    """Accept a quote (and, when asked, decline the others waiting for the same job).
    Returns every quote answered, for the partners' notifications."""
    found = await _get_for_customer(db, project, quote_id)
    await _check_waiting(found, assessment_date(now))
    _close(found.quote, QuoteStatus.ACCEPTED, now=now, actor_id=actor_id, note=data.note)
    answered = [Answered(found.quote, True)]
    others = (
        [q for q in await _waiting(db, lead_id=found.lead.id) if q.id != found.quote.id]
        if data.decline_others
        else []
    )
    for other in others:
        _close(other, QuoteStatus.DECLINED, now=now, actor_id=actor_id, note=CHOSE_ANOTHER)
        answered.append(Answered(other, False))
    await db.flush()
    for a in answered:
        match = (
            await db.execute(
                select(LeadMatch)
                .where(LeadMatch.id == a.quote.lead_match_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        if match.status in WORKING:
            to = LeadMatchStatus.WON if a.accepted else LeadMatchStatus.LOST
            note = "The customer accepted the quote." if a.accepted else CHOSE_ANOTHER
            await _transition(db, match, to, actor_id=actor_id, note=note)
        await audit.record(
            db,
            "quote.accepted" if a.accepted else "quote.declined",
            actor_user_id=actor_id,
            organisation_id=project.organisation_id,
            target_type="lead_quote",
            target_id=a.quote.id,
            meta=meta,
        )
    await db.flush()
    return answered


async def decline(
    db: AsyncSession,
    project: Project,
    quote_id: uuid.UUID,
    note: str | None,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
    now: datetime,
) -> list[Answered]:
    found = await _get_for_customer(db, project, quote_id)
    if found.quote.status != QuoteStatus.SENT:
        raise _conflict("not_waiting", "This quote has already been answered or withdrawn.")
    _close(found.quote, QuoteStatus.DECLINED, now=now, actor_id=actor_id, note=note)
    await db.flush()
    await audit.record(
        db,
        "quote.declined",
        actor_user_id=actor_id,
        organisation_id=project.organisation_id,
        target_type="lead_quote",
        target_id=found.quote.id,
        meta=meta,
    )
    return [Answered(found.quote, False)]
