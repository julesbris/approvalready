"""Lead engine routes.

* ``/v1/organisations/{id}/projects/{pid}/referrals...``: the customer asks to be introduced
  (``project.write``), sees who accepted and withdraws (``project.read`` to see).
* ``/v1/organisations/{id}/partner/leads...``: the partner's referrals. ``lead.read`` sees
  the public view; ``lead.claim`` accepts, declines and records outcomes. Credits: balance
  with ``lead.read``, buying with ``billing.manage``. Lead preferences: ``partner.manage``.
* ``/v1/organisations/{id}/projects/{pid}/quotes...`` (Milestone 23): the customer's quotes
  (``project.read``), accepting and declining them (``project.write``). Partners send and
  withdraw quotes under ``partner/leads/{match_id}/quotes`` with ``lead.claim``.
* ``/v1/organisations/{id}/projects/{pid}/conversations...`` (Milestone 26): the customer's
  messages with each partner who accepted (``project.read`` to read, ``project.write`` to
  write). Partners use ``partner/leads/{match_id}/messages`` (``lead.read`` to read,
  ``lead.claim`` to write).
* ``/v1/admin/leads...``: staff (``lead.manage``): leads with their matches and scores (never
  contact details), lead prices, credit adjustments and fee refunds.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import (
    DbDep,
    MetaDep,
    OrgContext,
    ResourcesDep,
    SettingsDep,
    require_org_permission,
    require_platform_permission,
)
from app.core.errors import ApiError, not_found
from app.db.tenant import bind_tenant
from app.modules.assessments.service import assessment_date
from app.modules.billing import service as billing
from app.modules.billing.models import PaymentPurpose, Price, PriceInterval, Product, ProductKind
from app.modules.billing.router import StripeDep, _require
from app.modules.billing.schemas import RedirectOut
from app.modules.leads import consent, jobs, messages, quotes, service
from app.modules.leads.models import (
    OPEN_MATCH,
    CreditLedgerEntry,
    LeadClaim,
    LeadMatchStatus,
    LeadStatus,
    MessageSender,
)
from app.modules.leads.schemas import (
    ClaimedPartnerOut,
    ConsentTextOut,
    ConversationOut,
    CreditAdjustIn,
    CreditEntryOut,
    CreditsOut,
    CreditStaffOut,
    CustomerLeadOut,
    CustomerQuoteOut,
    LeadDeclineIn,
    LeadOfferOut,
    LeadOutcomeIn,
    LeadPreferencesIn,
    LeadPreferencesOut,
    LeadPriceIn,
    LeadPriceOut,
    MessageIn,
    QuoteAcceptIn,
    QuoteDeclineIn,
    QuoteIn,
    ReferralCategoryOptionOut,
    ReferralIn,
    ReferralOptionsOut,
    ReferralOut,
    RefundIn,
    ScoreFactorOut,
    StaffLeadOut,
    StaffMatchOut,
)
from app.modules.partners import service as partners
from app.modules.partners.models import PartnerOrganisation
from app.modules.projects import service as projects
from app.modules.projects.models import Project
from app.modules.tenancy.models import OrganisationKind
from app.modules.tenancy.rbac import Perm

customer_router = APIRouter(
    prefix="/v1/organisations/{organisation_id}/projects/{project_id}/referrals",
    tags=["referrals"],
)
partner_router = APIRouter(prefix="/v1/organisations/{organisation_id}/partner", tags=["leads"])
quotes_router = APIRouter(
    prefix="/v1/organisations/{organisation_id}/projects/{project_id}/quotes", tags=["quotes"]
)
conversations_router = APIRouter(
    prefix="/v1/organisations/{organisation_id}/projects/{project_id}/conversations",
    tags=["messages"],
)
admin_router = APIRouter(prefix="/v1/admin/leads", tags=["admin: leads"])

ProjectRead = Annotated[OrgContext, Depends(require_org_permission(Perm.PROJECT_READ))]
ProjectWrite = Annotated[OrgContext, Depends(require_org_permission(Perm.PROJECT_WRITE))]
LeadRead = Annotated[OrgContext, Depends(require_org_permission(Perm.LEAD_READ))]
LeadClaimCtx = Annotated[OrgContext, Depends(require_org_permission(Perm.LEAD_CLAIM))]
OrgRead = Annotated[OrgContext, Depends(require_org_permission(Perm.ORG_READ))]
PartnerManage = Annotated[OrgContext, Depends(require_org_permission(Perm.PARTNER_MANAGE))]
BillingManage = Annotated[OrgContext, Depends(require_org_permission(Perm.BILLING_MANAGE))]
Staff = Annotated[OrgContext, Depends(require_platform_permission(Perm.LEAD_MANAGE))]


# --- Customer ----------------------------------------------------------------------------


async def _referrals(db: DbDep, project: Project) -> list[ReferralOut]:
    out = []
    for record, version, leads in await service.referrals_for_project(db, project):
        out.append(
            ReferralOut(
                id=record.id,
                project_id=record.project_id,
                assessment_id=record.assessment_id,
                consent_version=version,
                categories=list(record.categories),
                max_providers=record.max_providers,
                fields_released=list(record.fields_released),
                contact=dict(record.contact),
                suburb=record.suburb,
                lga=record.lga,
                state=record.state,
                postcode=record.postcode,
                timing=record.timing,
                summary=record.summary,
                granted_at=record.created_at,
                withdrawn_at=record.withdrawn_at,
                leads=[
                    CustomerLeadOut(
                        id=cl.lead.id,
                        category_key=cl.category.key,
                        category_label=cl.category.label,
                        status=cl.lead.status,
                        max_claims=cl.lead.max_claims,
                        claimed_count=cl.lead.claimed_count,
                        offered_count=cl.offered,
                        expires_at=cl.lead.expires_at,
                        claims=[
                            ClaimedPartnerOut(
                                name=c.organisation.name,
                                phone=c.partner.phone,
                                contact_email=c.partner.contact_email,
                                website=c.partner.website,
                                claimed_at=c.claim.created_at,
                                is_promoted=c.match.is_promoted,
                            )
                            for c in cl.claims
                        ],
                    )
                    for cl in leads
                ],
            )
        )
    return out


@customer_router.get("/options", response_model=ReferralOptionsOut)
async def referral_options(
    project_id: uuid.UUID,
    ctx: ProjectRead,
    db: DbDep,
    assessment_id: Annotated[uuid.UUID, Query()],
) -> ReferralOptionsOut:
    """What the introduction form offers: the assessment's "who can help" categories, the
    consent text to agree to, and suggested contact details and location."""
    project = await projects.get_project(db, ctx.organisation.id, project_id)
    o = await service.options(db, ctx.auth.user, project, assessment_id)
    text = await consent.current_version(db)
    return ReferralOptionsOut(
        assessment_id=o.assessment.id,
        consent=ConsentTextOut(id=text.id, version=text.version, title=text.title, body=text.body)
        if text
        else None,
        categories=[
            ReferralCategoryOptionOut(
                key=c.key, label=c.label, description=c.description, open_request=open_
            )
            for c, open_ in o.categories
        ],
        max_providers=o.max_providers,
        contact=o.contact,
        location=o.location,
    )


@customer_router.get("", response_model=list[ReferralOut])
async def list_referrals(project_id: uuid.UUID, ctx: ProjectRead, db: DbDep) -> list[ReferralOut]:
    project = await projects.get_project(db, ctx.organisation.id, project_id)
    return await _referrals(db, project)


@customer_router.post("", response_model=list[ReferralOut], status_code=201)
async def create_referral(
    project_id: uuid.UUID,
    body: ReferralIn,
    ctx: ProjectWrite,
    db: DbDep,
    meta: MetaDep,
    resources: ResourcesDep,
) -> list[ReferralOut]:
    """Agree to be introduced. Partners are matched straight after."""
    project = await projects.get_project(db, ctx.organisation.id, project_id)
    _, leads = await service.create_referral(
        db, user=ctx.auth.user, project=project, data=body, meta=meta, now=service.utcnow()
    )
    lead_ids = [lead.id for lead in leads]
    await db.commit()
    for lead_id in lead_ids:
        await resources.jobs.lead_match(lead_id)
    # Matching ran in its own session; nothing shown here changed except the offers, which
    # are counted afresh.
    await bind_tenant(db, ctx.organisation.id)
    return await _referrals(db, project)


@customer_router.post("/{consent_id}/withdraw", response_model=list[ReferralOut])
async def withdraw_referral(
    project_id: uuid.UUID, consent_id: uuid.UUID, ctx: ProjectWrite, db: DbDep, meta: MetaDep
) -> list[ReferralOut]:
    """Stop the introduction: partners who haven't accepted no longer see it."""
    project = await projects.get_project(db, ctx.organisation.id, project_id)
    record = await service.get_consent(db, ctx.organisation.id, consent_id, lock=True)
    if record.project_id != project.id:
        raise not_found("Introduction request")
    await service.withdraw(db, record, actor_id=ctx.auth.user.id, meta=meta, now=service.utcnow())
    await db.commit()
    return await _referrals(db, project)


# --- Customer: quotes ------------------------------------------------------------------


async def _quotes(db: DbDep, project: Project) -> list[CustomerQuoteOut]:
    today = assessment_date(service.utcnow())
    return [q.out(today) for q in await quotes.for_project(db, project)]


async def _answered(
    db: DbDep,
    ctx: OrgContext,
    resources: ResourcesDep,
    settings: SettingsDep,
    answered: list[quotes.Answered],
) -> None:
    await db.commit()
    pending = await jobs.notify_quote_answered(db, [(a.quote, a.accepted) for a in answered])
    await db.commit()
    await _send(db, resources, settings, pending)
    await bind_tenant(db, ctx.organisation.id)


@quotes_router.get("", response_model=list[CustomerQuoteOut])
async def list_quotes(project_id: uuid.UUID, ctx: ProjectRead, db: DbDep) -> list[CustomerQuoteOut]:
    """Quotes partners sent for this project's introductions, newest first (earlier
    versions of a revised quote are left out)."""
    project = await projects.get_project(db, ctx.organisation.id, project_id)
    return await _quotes(db, project)


@quotes_router.post("/{quote_id}/accept", response_model=list[CustomerQuoteOut])
async def accept_quote(
    project_id: uuid.UUID,
    quote_id: uuid.UUID,
    body: QuoteAcceptIn,
    ctx: ProjectWrite,
    db: DbDep,
    meta: MetaDep,
    resources: ResourcesDep,
    settings: SettingsDep,
) -> list[CustomerQuoteOut]:
    """Tell the partner you want to go ahead. The agreement for the work is between you and
    them."""
    project = await projects.get_project(db, ctx.organisation.id, project_id)
    answered = await quotes.accept(
        db, project, quote_id, body, actor_id=ctx.auth.user.id, meta=meta, now=service.utcnow()
    )
    await _answered(db, ctx, resources, settings, answered)
    return await _quotes(db, project)


@quotes_router.post("/{quote_id}/decline", response_model=list[CustomerQuoteOut])
async def decline_quote(
    project_id: uuid.UUID,
    quote_id: uuid.UUID,
    body: QuoteDeclineIn,
    ctx: ProjectWrite,
    db: DbDep,
    meta: MetaDep,
    resources: ResourcesDep,
    settings: SettingsDep,
) -> list[CustomerQuoteOut]:
    project = await projects.get_project(db, ctx.organisation.id, project_id)
    answered = await quotes.decline(
        db,
        project,
        quote_id,
        body.note,
        actor_id=ctx.auth.user.id,
        meta=meta,
        now=service.utcnow(),
    )
    await _answered(db, ctx, resources, settings, answered)
    return await _quotes(db, project)


# --- Customer: messages ----------------------------------------------------------------


async def _conversations(db: DbDep, project: Project) -> list[ConversationOut]:
    return [await c.out(db) for c in await messages.for_project(db, project)]


@conversations_router.get("", response_model=list[ConversationOut])
async def list_conversations(
    project_id: uuid.UUID, ctx: ProjectRead, db: DbDep
) -> list[ConversationOut]:
    """Messages with each partner who accepted one of this project's introductions."""
    project = await projects.get_project(db, ctx.organisation.id, project_id)
    return await _conversations(db, project)


@conversations_router.post("/{match_id}/messages", response_model=ConversationOut, status_code=201)
async def send_customer_message(
    project_id: uuid.UUID,
    match_id: uuid.UUID,
    body: MessageIn,
    ctx: ProjectWrite,
    db: DbDep,
    meta: MetaDep,
    resources: ResourcesDep,
    settings: SettingsDep,
) -> ConversationOut:
    """Write to the partner. They are told about the first message waiting for them."""
    project = await projects.get_project(db, ctx.organisation.id, project_id)
    found, sent = await messages.customer_send(
        db, project, match_id, body.body, actor_id=ctx.auth.user.id, meta=meta, now=service.utcnow()
    )
    await db.commit()
    if sent.notify:
        pending = await jobs.notify_message(
            db,
            found.lead,
            sent.message,
            partner_name=found.organisation.name,
            category_label=found.category.label,
        )
        await db.commit()
        await _send(db, resources, settings, pending)
    await bind_tenant(db, ctx.organisation.id)
    found = await messages.get_for_customer(db, project, match_id)
    return await found.out(db)


@conversations_router.post("/{match_id}/read", response_model=ConversationOut)
async def read_customer_conversation(
    project_id: uuid.UUID, match_id: uuid.UUID, ctx: ProjectRead, db: DbDep
) -> ConversationOut:
    """Mark the partner's messages as read (opening the conversation)."""
    project = await projects.get_project(db, ctx.organisation.id, project_id)
    found = await messages.get_for_customer(db, project, match_id)
    await messages.mark_read(db, match_id, MessageSender.CUSTOMER, now=service.utcnow())
    await db.commit()
    await bind_tenant(db, ctx.organisation.id)
    return await found.out(db)


# --- Partner -----------------------------------------------------------------------------


async def _partner(ctx: OrgContext, db: DbDep, *, lock: bool = False) -> PartnerOrganisation:
    if ctx.organisation.kind != OrganisationKind.PARTNER:
        raise not_found("Partner account")
    return await partners.for_organisation(db, ctx.organisation.id, lock=lock)


async def _offer_out(
    db: DbDep, partner: PartnerOrganisation, offer: service.Offer, *, fee: bool
) -> LeadOfferOut:
    open_ = offer.match.status in OPEN_MATCH and offer.lead.status == LeadStatus.OPEN
    return LeadOfferOut(
        lead=service.public_view(offer.match, offer.lead, offer.category),
        fee=await service.fee_for(db, partner, offer.category, now=service.utcnow())
        if fee and open_
        else None,
        claim=service.claim_out(offer.match, offer.lead, offer.category, offer.claim)
        if offer.claim
        else None,
        quotes=[
            quotes.quote_out(q, assessment_date(service.utcnow()))
            for q in await quotes.for_match(db, offer.match.id)
        ]
        if offer.claim
        else [],
        unread_messages=await messages.unread_count(db, offer.match.id, MessageSender.PARTNER)
        if offer.claim
        else 0,
    )


async def _send(
    db: DbDep, resources: ResourcesDep, settings: SettingsDep, pending: jobs.Pending
) -> None:
    await jobs.send_pending(db, resources.email, settings, pending)


@partner_router.get("/leads", response_model=list[LeadOfferOut])
async def list_leads(
    ctx: LeadRead,
    db: DbDep,
    status: Annotated[list[LeadMatchStatus] | None, Query()] = None,
) -> list[LeadOfferOut]:
    """Referrals offered to this partner, newest first."""
    partner = await _partner(ctx, db)
    return [
        await _offer_out(db, partner, o, fee=True)
        for o in await service.offers(db, partner, statuses=status)
    ]


@partner_router.get("/leads/{match_id}", response_model=LeadOfferOut)
async def get_lead(match_id: uuid.UUID, ctx: LeadRead, db: DbDep) -> LeadOfferOut:
    """One referral (opening it marks it viewed)."""
    partner = await _partner(ctx, db)
    offer = await service.get_offer(db, partner, match_id)
    await service.mark_viewed(db, offer, actor_id=ctx.auth.user.id, now=service.utcnow())
    await db.commit()
    return await _offer_out(db, partner, offer, fee=True)


@partner_router.post("/leads/{match_id}/claim", response_model=LeadOfferOut)
async def claim_lead(
    match_id: uuid.UUID,
    ctx: LeadClaimCtx,
    db: DbDep,
    meta: MetaDep,
    resources: ResourcesDep,
    settings: SettingsDep,
) -> LeadOfferOut:
    """Accept a referral: any fee is charged and the customer's chosen contact details are
    released to you."""
    partner = await _partner(ctx, db)
    now = service.utcnow()
    offer = await service.claim(
        db,
        partner,
        match_id,
        actor_id=ctx.auth.user.id,
        meta=meta,
        now=now,
        on=assessment_date(now),
    )
    await db.commit()
    name = ctx.organisation.name
    pending = await jobs.notify_claimed(db, offer.lead, name, offer.category.label)
    await db.commit()
    await _send(db, resources, settings, pending)
    await bind_tenant(db, ctx.organisation.id)
    return await _offer_out(db, partner, offer, fee=False)


@partner_router.post("/leads/{match_id}/decline", response_model=LeadOfferOut)
async def decline_lead(
    match_id: uuid.UUID,
    body: LeadDeclineIn,
    ctx: LeadClaimCtx,
    db: DbDep,
    meta: MetaDep,
    resources: ResourcesDep,
    settings: SettingsDep,
) -> LeadOfferOut:
    partner = await _partner(ctx, db)
    offer, offered = await service.decline(
        db,
        partner,
        match_id,
        body.reason,
        actor_id=ctx.auth.user.id,
        meta=meta,
        now=service.utcnow(),
    )
    pending = await jobs.notify_offered(db, offered)
    await db.commit()
    await _send(db, resources, settings, pending)
    await bind_tenant(db, ctx.organisation.id)
    return await _offer_out(db, partner, offer, fee=False)


@partner_router.post("/leads/{match_id}/outcome", response_model=LeadOfferOut)
async def record_outcome(
    match_id: uuid.UUID, body: LeadOutcomeIn, ctx: LeadClaimCtx, db: DbDep, meta: MetaDep
) -> LeadOfferOut:
    """Record what happened after accepting: contacted, quoted, won or lost."""
    partner = await _partner(ctx, db)
    offer = await service.record_outcome(
        db, partner, match_id, body.status, body.note, actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    offer = await service.get_offer(db, partner, match_id)
    return await _offer_out(db, partner, offer, fee=False)


@partner_router.post("/leads/{match_id}/quotes", response_model=LeadOfferOut, status_code=201)
async def send_quote(
    match_id: uuid.UUID,
    body: QuoteIn,
    ctx: LeadClaimCtx,
    db: DbDep,
    meta: MetaDep,
    resources: ResourcesDep,
    settings: SettingsDep,
) -> LeadOfferOut:
    """Send the customer a written quote. A quote already waiting is replaced by this one."""
    partner = await _partner(ctx, db)
    offer, quote = await quotes.send(
        db, partner, match_id, body, actor_id=ctx.auth.user.id, meta=meta, now=service.utcnow()
    )
    await db.commit()
    pending = await jobs.notify_quote_received(db, offer.lead, ctx.organisation.name, quote)
    await db.commit()
    await _send(db, resources, settings, pending)
    await bind_tenant(db, ctx.organisation.id)
    offer = await service.get_offer(db, partner, match_id)
    return await _offer_out(db, partner, offer, fee=False)


@partner_router.post("/leads/{match_id}/quotes/{quote_id}/withdraw", response_model=LeadOfferOut)
async def withdraw_quote(
    match_id: uuid.UUID, quote_id: uuid.UUID, ctx: LeadClaimCtx, db: DbDep, meta: MetaDep
) -> LeadOfferOut:
    """Take back a quote the customer hasn't answered."""
    partner = await _partner(ctx, db)
    await quotes.withdraw(
        db,
        partner,
        match_id,
        quote_id,
        actor_id=ctx.auth.user.id,
        meta=meta,
        now=service.utcnow(),
    )
    await db.commit()
    offer = await service.get_offer(db, partner, match_id)
    return await _offer_out(db, partner, offer, fee=False)


async def _partner_conversation(
    db: DbDep, ctx: OrgContext, offer: service.Offer
) -> ConversationOut:
    return await messages.conversation_out(
        db,
        offer.match,
        category_label=offer.category.label,
        partner_name=ctx.organisation.name,
        viewer=MessageSender.PARTNER,
    )


@partner_router.get("/leads/{match_id}/messages", response_model=ConversationOut)
async def get_partner_conversation(
    match_id: uuid.UUID, ctx: LeadRead, db: DbDep
) -> ConversationOut:
    """Messages with the customer about this referral (once accepted), oldest first."""
    partner = await _partner(ctx, db)
    offer = await messages.partner_offer(db, partner, match_id)
    return await _partner_conversation(db, ctx, offer)


@partner_router.post("/leads/{match_id}/messages", response_model=ConversationOut, status_code=201)
async def send_partner_message(
    match_id: uuid.UUID,
    body: MessageIn,
    ctx: LeadClaimCtx,
    db: DbDep,
    meta: MetaDep,
    resources: ResourcesDep,
    settings: SettingsDep,
) -> ConversationOut:
    """Write to the customer. They are told about the first message waiting for them."""
    partner = await _partner(ctx, db)
    offer, sent = await messages.partner_send(
        db, partner, match_id, body.body, actor_id=ctx.auth.user.id, meta=meta, now=service.utcnow()
    )
    await db.commit()
    if sent.notify:
        pending = await jobs.notify_message(
            db,
            offer.lead,
            sent.message,
            partner_name=ctx.organisation.name,
            category_label=offer.category.label,
        )
        await db.commit()
        await _send(db, resources, settings, pending)
    await bind_tenant(db, ctx.organisation.id)
    offer = await messages.partner_offer(db, partner, match_id)
    return await _partner_conversation(db, ctx, offer)


@partner_router.post("/leads/{match_id}/messages/read", response_model=ConversationOut)
async def read_partner_conversation(
    match_id: uuid.UUID, ctx: LeadRead, db: DbDep
) -> ConversationOut:
    """Mark the customer's messages as read (opening the conversation)."""
    partner = await _partner(ctx, db)
    offer = await messages.partner_offer(db, partner, match_id)
    await messages.mark_read(db, offer.match.id, MessageSender.PARTNER, now=service.utcnow())
    await db.commit()
    await bind_tenant(db, ctx.organisation.id)
    return await _partner_conversation(db, ctx, offer)


async def _preferences(db: DbDep, partner: PartnerOrganisation) -> LeadPreferencesOut:
    from app.modules.leads.matching import working_count

    return LeadPreferencesOut(
        paused=partner.paused,
        max_open_leads=partner.max_open_leads,
        in_progress=await working_count(db, partner.id),
    )


@partner_router.get("/lead-preferences", response_model=LeadPreferencesOut)
async def get_preferences(ctx: OrgRead, db: DbDep) -> LeadPreferencesOut:
    return await _preferences(db, await _partner(ctx, db))


@partner_router.patch("/lead-preferences", response_model=LeadPreferencesOut)
async def set_preferences(
    body: LeadPreferencesIn, ctx: PartnerManage, db: DbDep, meta: MetaDep
) -> LeadPreferencesOut:
    """Pause new referrals, or cap how many accepted referrals can be in progress."""
    partner = await _partner(ctx, db, lock=True)
    await service.set_preferences(db, partner, body, actor_id=ctx.auth.user.id, meta=meta)
    await db.commit()
    return await _preferences(db, partner)


def _entry_out(e: CreditLedgerEntry) -> CreditEntryOut:
    return CreditEntryOut(
        id=e.id,
        kind=e.kind,
        delta_cents=e.delta_cents,
        balance_after_cents=e.balance_after_cents,
        note=e.note,
        reference_type=e.reference_type,
        reference_id=e.reference_id,
        created_at=e.created_at,
    )


async def _pack(db: DbDep) -> tuple[Product, Price] | None:
    row = (
        await db.execute(
            select(Product, Price)
            .join(Price, Price.product_id == Product.id)
            .where(
                Product.key == service.CREDIT_PACK_PRODUCT,
                Product.kind == ProductKind.CREDIT_PACK,
                Product.active.is_(True),
                Price.active.is_(True),
                Price.interval == PriceInterval.ONE_TIME,
            )
        )
    ).one_or_none()
    return (row[0], row[1]) if row else None


@partner_router.get("/credits", response_model=CreditsOut)
async def get_credits(ctx: LeadRead, db: DbDep) -> CreditsOut:
    """The partner's credit balance, this month's included referrals and the ledger."""
    partner = await _partner(ctx, db)
    bal, _ = await service.balance(db, ctx.organisation.id)
    pack = await _pack(db)
    return CreditsOut(
        balance_cents=bal,
        included_used=await service.included_used(db, partner.id, service.utcnow()),
        included_limit=await service.included_limit(db, ctx.organisation.id),
        pack_price_cents=pack[1].amount_cents if pack else None,
        entries=[_entry_out(e) for e in await service.ledger(db, ctx.organisation.id)],
    )


@partner_router.post("/credits/checkout", response_model=RedirectOut)
async def buy_credits(
    ctx: BillingManage, db: DbDep, settings: SettingsDep, stripe: StripeDep
) -> RedirectOut:
    """A Stripe Checkout page for a credit pack. Credit is added when Stripe confirms."""
    client = _require(stripe)
    partner = await _partner(ctx, db)
    pack = await _pack(db)
    if pack is None:
        raise ApiError(409, "not_on_sale", "Credit isn't on sale yet.")
    product, price = pack
    payment = await billing.start_payment(
        db,
        organisation_id=ctx.organisation.id,
        purpose=PaymentPurpose.PRODUCT,
        product=product,
        price=price,
        subject_type=service.CREDIT_PACK_SUBJECT,
        subject_id=partner.id,
        actor_id=ctx.auth.user.id,
    )
    base = f"{settings.partners_url.rstrip('/')}/partner/leads"
    url = await billing.checkout_for_payment(
        db,
        client,
        organisation=ctx.organisation,
        user=ctx.auth.user,
        payment=payment,
        success_url=f"{base}?credits=bought",
        cancel_url=base,
    )
    await db.commit()
    return RedirectOut(url=url)


# --- Staff -------------------------------------------------------------------------------


@admin_router.get("", response_model=list[StaffLeadOut])
async def staff_list(
    ctx: Staff, db: DbDep, status: Annotated[LeadStatus | None, Query()] = None
) -> list[StaffLeadOut]:
    """Recent leads with every match, its score and outcome (never contact details)."""
    out = []
    for lead, category in await service.staff_leads(db, status):
        matches = [
            StaffMatchOut(
                id=m.id,
                claim_id=c.id if c else None,
                partner_id=p.id,
                partner_name=o.name,
                rank=m.rank,
                score=float(m.score),
                score_breakdown=[ScoreFactorOut(**f) for f in m.score_breakdown],
                status=m.status,
                offered_at=m.offered_at,
                responded_at=m.responded_at,
                fee_cents=c.fee_cents if c else None,
                included=c.included if c else None,
                claim_refunded_at=c.refunded_at if c else None,
            )
            for m, p, o, c in await service.staff_matches(db, lead.id)
        ]
        out.append(
            StaffLeadOut(
                id=lead.id,
                created_at=lead.created_at,
                category_key=category.key,
                category_label=category.label,
                vertical=lead.vertical,
                suburb=lead.suburb,
                lga=lead.lga,
                state=lead.state,
                postcode=lead.postcode,
                status=lead.status,
                max_claims=lead.max_claims,
                claimed_count=lead.claimed_count,
                expires_at=lead.expires_at,
                matches=matches,
            )
        )
    return out


async def _prices(db: DbDep) -> list[LeadPriceOut]:
    return [
        LeadPriceOut(
            category_key=c.key,
            category_label=c.label,
            restricted=c.restricted,
            price_id=p.id if p else None,
            amount_cents=p.amount_cents if p else None,
            set_at=p.created_at if p else None,
        )
        for c, p in await service.prices(db)
    ]


@admin_router.get("/prices", response_model=list[LeadPriceOut])
async def list_prices(ctx: Staff, db: DbDep) -> list[LeadPriceOut]:
    """Lead fee per category (charged beyond a partner's included referrals)."""
    return await _prices(db)


@admin_router.put("/prices/{category_key}", response_model=list[LeadPriceOut])
async def set_price(
    category_key: str, body: LeadPriceIn, ctx: Staff, db: DbDep, meta: MetaDep
) -> list[LeadPriceOut]:
    await service.set_price(
        db,
        category_key,
        body.amount_cents,
        actor_id=ctx.auth.user.id,
        meta=meta,
        now=service.utcnow(),
    )
    await db.commit()
    return await _prices(db)


@admin_router.delete("/prices/{category_key}", response_model=list[LeadPriceOut])
async def remove_price(
    category_key: str, ctx: Staff, db: DbDep, meta: MetaDep
) -> list[LeadPriceOut]:
    await service.set_price(
        db, category_key, None, actor_id=ctx.auth.user.id, meta=meta, now=service.utcnow()
    )
    await db.commit()
    return await _prices(db)


async def _staff_credits(db: DbDep, partner: PartnerOrganisation) -> CreditStaffOut:
    await bind_tenant(db, partner.organisation_id)
    bal, _ = await service.balance(db, partner.organisation_id)
    return CreditStaffOut(
        partner_id=partner.id,
        balance_cents=bal,
        entries=[_entry_out(e) for e in await service.ledger(db, partner.organisation_id)],
    )


@admin_router.get("/partners/{partner_id}/credits", response_model=CreditStaffOut)
async def staff_credits(partner_id: uuid.UUID, ctx: Staff, db: DbDep) -> CreditStaffOut:
    return await _staff_credits(db, await partners.get_partner(db, partner_id))


@admin_router.post("/partners/{partner_id}/credits", response_model=CreditStaffOut)
async def adjust_credits(
    partner_id: uuid.UUID, body: CreditAdjustIn, ctx: Staff, db: DbDep, meta: MetaDep
) -> CreditStaffOut:
    """Give promotional credit or correct a partner's balance."""
    partner = await partners.get_partner(db, partner_id)
    await bind_tenant(db, partner.organisation_id)
    await service.adjust_credits(
        db,
        partner,
        body.kind,
        body.delta_cents,
        body.note,
        actor_id=ctx.auth.user.id,
        meta=meta,
    )
    await db.commit()
    return await _staff_credits(db, partner)


@admin_router.post("/claims/{claim_id}/refund", response_model=CreditStaffOut)
async def refund_claim(
    claim_id: uuid.UUID, body: RefundIn, ctx: Staff, db: DbDep, meta: MetaDep
) -> CreditStaffOut:
    """Give a claimed referral's fee back as credit."""
    row = (
        await db.execute(select(LeadClaim).where(LeadClaim.id == claim_id).with_for_update())
    ).scalar_one_or_none()
    if row is None:
        raise not_found("Claim")
    partner = await partners.get_partner(db, row.partner_organisation_id)
    await bind_tenant(db, partner.organisation_id)
    await service.refund_claim(
        db, row, body.note, actor_id=ctx.auth.user.id, meta=meta, now=service.utcnow()
    )
    await db.commit()
    return await _staff_credits(db, partner)
