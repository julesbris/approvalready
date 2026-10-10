"""Background work for leads: matching a new lead and the periodic sweep.

* ``match_lead``: right after a customer consents (a Celery task, or inline in tests):
  find and rank eligible partners, offer the first wave, notify them.
* ``sweep`` (Celery beat, every 15 minutes): expire leads past their date, match partners
  who became eligible since, release the next wave where it is due, and notify.

Notifications to partners carry the public view only (category and area), never the
customer's details.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.email import EmailProvider
from app.db.tenant import bind_tenant
from app.modules.assessments.service import assessment_date
from app.modules.leads import matching
from app.modules.leads.models import Lead, LeadMatch, LeadStatus, ReferralConsent
from app.modules.leads.service import close_lead, utcnow
from app.modules.marketplace.models import MarketplaceCategory
from app.modules.notifications import service as notifications
from app.modules.notifications.models import NotificationKind
from app.modules.notifications.reminders import BRISBANE
from app.modules.partners.models import PartnerOrganisation
from app.modules.tenancy import service as tenancy
from app.modules.tenancy.rbac import Perm

log = logging.getLogger(__name__)

MATCH_TASK = "leads.match"
SWEEP_TASK = "leads.sweep"

Pending = dict[uuid.UUID, list[uuid.UUID]]  # organisation -> notification ids to email


def _where(lead: Lead) -> str:
    place = lead.suburb or lead.lga
    return f"{place} {lead.state} {lead.postcode}" if place else f"{lead.state} {lead.postcode}"


async def notify_offered(db: AsyncSession, matches: list[LeadMatch]) -> Pending:
    """In-app notifications (and emails, sent after commit) for each newly offered match,
    to every member of the partner who can see referrals."""
    pending: Pending = {}
    for m in matches:
        lead = await db.get(Lead, m.lead_id)
        partner = await db.get(PartnerOrganisation, m.partner_organisation_id)
        if lead is None or partner is None:
            continue
        category = await db.get(MarketplaceCategory, lead.category_id)
        label = category.label if category else "Referral"
        await bind_tenant(db, partner.organisation_id)
        for member in await tenancy.list_members(db, partner.organisation_id):
            perms = await tenancy.permissions_of_roles(db, member.role_keys)
            if Perm.LEAD_READ not in perms:
                continue
            nid = await notifications.create(
                db,
                organisation_id=partner.organisation_id,
                recipient_user_id=member.user.id,
                kind=NotificationKind.LEAD_OFFERED,
                title=f"New referral: {label} in {_where(lead)}",
                body=(
                    f"Offered until {lead.expires_at.astimezone(BRISBANE).date():%d %b %Y}. "
                    "Accept it to see the customer's contact details."
                ),
                link_path=f"/partner/leads/{m.id}",
                dedupe_key=f"lead-offer:{m.id}",
            )
            if nid is not None:
                pending.setdefault(partner.organisation_id, []).append(nid)
    return pending


async def notify_claimed(
    db: AsyncSession, lead: Lead, partner_name: str, category_label: str
) -> Pending:
    """Tell the customer who asked that a partner accepted (bind is changed here)."""
    await bind_tenant(db, lead.organisation_id)
    record = (
        await db.execute(
            select(ReferralConsent).where(ReferralConsent.id == lead.referral_consent_id)
        )
    ).scalar_one_or_none()
    if record is None:
        return {}
    nid = await notifications.create(
        db,
        organisation_id=lead.organisation_id,
        recipient_user_id=record.user_id,
        kind=NotificationKind.LEAD_CLAIMED,
        title=f"{partner_name} accepted your request for a {category_label.lower()}",
        body="They have the contact details you chose to share and may get in touch.",
        link_path=f"/projects/{lead.project_id}/referrals",
        project_id=lead.project_id,
        dedupe_key=f"lead-claim:{lead.id}:{partner_name}"[:200],
    )
    return {lead.organisation_id: [nid]} if nid else {}


async def send_pending(
    db: AsyncSession, email: EmailProvider | None, settings: Settings | None, pending: Pending
) -> None:
    if email is None or settings is None:
        return
    for organisation_id, ids in pending.items():
        await bind_tenant(db, organisation_id)
        try:
            await notifications.send_emails(db, email, settings, organisation_id, ids)
        except Exception:
            log.exception("lead notification emails failed")


def _merge(into: Pending, more: Pending) -> None:
    for k, v in more.items():
        into.setdefault(k, []).extend(v)


async def _match_and_release(db: AsyncSession, lead: Lead, now: datetime) -> list[LeadMatch]:
    await matching.match(db, lead, on=assessment_date(now), now=now)
    return await matching.release(db, lead, now=now)


async def match_lead(
    factory: async_sessionmaker[AsyncSession],
    email: EmailProvider | None,
    settings: Settings | None,
    lead_id: uuid.UUID,
) -> int:
    async with factory() as db:
        lead = (
            await db.execute(select(Lead).where(Lead.id == lead_id).with_for_update())
        ).scalar_one_or_none()
        if lead is None or lead.status != LeadStatus.OPEN:
            return 0
        offered = await _match_and_release(db, lead, utcnow())
        pending = await notify_offered(db, offered)
        await db.commit()
        await send_pending(db, email, settings, pending)
        return len(offered)


async def sweep(
    factory: async_sessionmaker[AsyncSession],
    email: EmailProvider | None,
    settings: Settings | None,
) -> int:
    """Expire, re-match and release every open lead. Returns how many offers were made."""
    now = utcnow()
    async with factory() as db:
        ids = list(
            (await db.execute(select(Lead.id).where(Lead.status == LeadStatus.OPEN))).scalars()
        )
    made = 0
    for lead_id in ids:
        async with factory() as db:
            lead = (
                await db.execute(
                    select(Lead).where(Lead.id == lead_id).with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if lead is None or lead.status != LeadStatus.OPEN:
                continue
            if now >= lead.expires_at:
                await close_lead(db, lead, LeadStatus.EXPIRED, now=now, note="The offer ended.")
                await db.commit()
                continue
            offered = await _match_and_release(db, lead, now)
            pending = await notify_offered(db, offered)
            await db.commit()
            await send_pending(db, email, settings, pending)
            made += len(offered)
    return made
