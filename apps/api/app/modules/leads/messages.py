"""Messages (Milestone 26): the customer and a partner who accepted their referral write to
each other about the job inside ApprovalReady.

* One conversation per referral a partner accepted (``lead_match`` with a claim). Either side
  can write while the partner is working on the job or won it; once it is lost (declined
  quote, another partner chosen, recorded as lost) the conversation stays readable only.
* Messages are never edited or deleted (database trigger). When the other side opens the
  conversation, the messages waiting for them are marked read, once.
* The other side is told (in the app and by email, as their Referrals setting allows) about
  the first message waiting for them, not every one: the next notice comes after they have
  opened the conversation.
* At most ``HOURLY_LIMIT`` messages an hour from each side of a conversation, so a partner
  can't flood a customer (or the other way round).
* A message can carry one file (a site plan, photos, a quote document). The file is stored
  under ``messages/<match>/<id>`` and checked for viruses after the request commits; neither
  side can download it until the scan says it is clean (``attachments.py``).

Lock order is the lead engine's: the lead, then the match.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, not_found
from app.db.base import uuid7
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.documents.filetypes import CheckedFile
from app.modules.documents.storage import ObjectStorage
from app.modules.leads.models import (
    WORKING,
    Lead,
    LeadClaim,
    LeadMatch,
    LeadMatchStatus,
    LeadMessage,
    LeadMessageAttachment,
    MessageSender,
)
from app.modules.leads.schemas import AttachmentOut, ConversationOut, MessageOut
from app.modules.leads.service import Offer, ensure_customer_open, get_offer
from app.modules.marketplace.models import MarketplaceCategory
from app.modules.partners.models import PartnerOrganisation
from app.modules.projects.models import Project
from app.modules.tenancy.models import Organisation

HOURLY_LIMIT = 30
# The conversation stays open for writing while the job is in progress or won.
OPEN_FOR_MESSAGES = (*WORKING, LeadMatchStatus.WON)


def can_send(match: LeadMatch) -> bool:
    return match.status in OPEN_FOR_MESSAGES


def _other(side: MessageSender) -> MessageSender:
    return MessageSender.PARTNER if side == MessageSender.CUSTOMER else MessageSender.CUSTOMER


async def thread(db: AsyncSession, match_id: uuid.UUID) -> list[LeadMessage]:
    return list(
        (
            await db.execute(
                select(LeadMessage)
                .where(LeadMessage.lead_match_id == match_id)
                .order_by(LeadMessage.created_at, LeadMessage.id)
            )
        ).scalars()
    )


async def unread_count(db: AsyncSession, match_id: uuid.UUID, viewer: MessageSender) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(LeadMessage)
            .where(
                LeadMessage.lead_match_id == match_id,
                LeadMessage.sender == _other(viewer),
                LeadMessage.read_at.is_(None),
            )
        )
    ).scalar_one()


async def attachments_for(
    db: AsyncSession, match_id: uuid.UUID
) -> dict[uuid.UUID, LeadMessageAttachment]:
    """The files sent in a conversation, by message."""
    rows = await db.execute(
        select(LeadMessageAttachment)
        .where(LeadMessageAttachment.lead_match_id == match_id)
        # A scan in another session (the worker, or inline) may have changed loaded rows.
        .execution_options(populate_existing=True)
    )
    return {a.lead_message_id: a for a in rows.scalars()}


def attachment_out(a: LeadMessageAttachment) -> AttachmentOut:
    return AttachmentOut(
        id=a.id,
        filename=a.original_filename,
        content_type=a.detected_mime,
        size_bytes=a.size_bytes,
        scan_status=a.scan_status,
    )


def message_out(
    message: LeadMessage,
    viewer: MessageSender,
    attachment: LeadMessageAttachment | None = None,
) -> MessageOut:
    return MessageOut(
        id=message.id,
        sender=MessageSender(message.sender),
        from_you=message.sender == viewer,
        body=message.body,
        sent_at=message.created_at,
        read_at=message.read_at,
        attachment=attachment_out(attachment) if attachment is not None else None,
    )


async def conversation_out(
    db: AsyncSession,
    match: LeadMatch,
    *,
    category_label: str,
    partner_name: str,
    viewer: MessageSender,
) -> ConversationOut:
    messages = await thread(db, match.id)
    files = await attachments_for(db, match.id) if messages else {}
    return ConversationOut(
        match_id=match.id,
        lead_id=match.lead_id,
        category_label=category_label,
        partner_name=partner_name,
        can_send=can_send(match),
        unread=sum(1 for m in messages if m.sender != viewer and m.read_at is None),
        messages=[message_out(m, viewer, files.get(m.id)) for m in messages],
    )


async def mark_read(
    db: AsyncSession, match_id: uuid.UUID, viewer: MessageSender, *, now: datetime
) -> int:
    """Mark what the other side sent as read. Returns how many messages were marked."""
    result = await db.execute(
        update(LeadMessage)
        .where(
            LeadMessage.lead_match_id == match_id,
            LeadMessage.sender == _other(viewer),
            LeadMessage.read_at.is_(None),
        )
        .values(read_at=now)
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


@dataclass(frozen=True)
class FileToSend:
    """A checked file (``documents.service.check_upload``) to send with a message."""

    data: bytes
    checked: CheckedFile
    storage: ObjectStorage


@dataclass(frozen=True)
class Sent:
    message: LeadMessage
    # The first message waiting for the other side: they are told about this one.
    notify: bool
    attachment: LeadMessageAttachment | None = None


def file_message(body: str | None, filename: str) -> str:
    """The text sent with a file: what the sender wrote, or a line naming the file."""
    text = (body or "").strip()
    return text or f"Sent a file: {filename}"[:4000]


async def _post(
    db: AsyncSession,
    match: LeadMatch,
    sender: MessageSender,
    body: str,
    *,
    actor_id: uuid.UUID,
    organisation_id: uuid.UUID,
    meta: RequestMeta | None,
    now: datetime,
    file: FileToSend | None = None,
) -> Sent:
    if not can_send(match):
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "conversation_closed",
            "This job is finished, so the conversation is read-only.",
        )
    recent = (
        await db.execute(
            select(func.count())
            .select_from(LeadMessage)
            .where(
                LeadMessage.lead_match_id == match.id,
                LeadMessage.sender == sender,
                LeadMessage.created_at > now - timedelta(hours=1),
            )
        )
    ).scalar_one()
    if recent >= HOURLY_LIMIT:
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "too_many_messages",
            f"You can send up to {HOURLY_LIMIT} messages an hour in a conversation. "
            "Try again later.",
        )
    waiting = (
        await db.execute(
            select(func.count())
            .select_from(LeadMessage)
            .where(
                LeadMessage.lead_match_id == match.id,
                LeadMessage.sender == sender,
                LeadMessage.read_at.is_(None),
            )
        )
    ).scalar_one()
    message = LeadMessage(
        lead_match_id=match.id,
        lead_id=match.lead_id,
        partner_organisation_id=match.partner_organisation_id,
        sender=sender,
        sender_user_id=actor_id,
        body=body,
        created_at=now,
    )
    db.add(message)
    await db.flush()
    attachment = await _attach(db, match, message, file) if file is not None else None
    # The text stays out of the audit log: it records who wrote, not what.
    await audit.record(
        db,
        "message.sent",
        actor_user_id=actor_id,
        organisation_id=organisation_id,
        target_type="lead_message",
        target_id=message.id,
        meta=meta,
        details={"lead_match_id": str(match.id), "sender": sender.value}
        | (
            {
                "attachment_id": str(attachment.id),
                "type": attachment.detected_mime,
                "size_bytes": attachment.size_bytes,
                "sha256": attachment.sha256.hex(),
            }
            if attachment is not None
            else {}
        ),
    )
    return Sent(message, notify=waiting == 0, attachment=attachment)


async def _attach(
    db: AsyncSession, match: LeadMatch, message: LeadMessage, file: FileToSend
) -> LeadMessageAttachment:
    attachment_id = uuid7()
    key = f"messages/{match.id}/{attachment_id}"
    await file.storage.put(key, file.data, file.checked.type.mime)
    attachment = LeadMessageAttachment(
        id=attachment_id,
        lead_message_id=message.id,
        lead_match_id=match.id,
        storage_key=key,
        original_filename=file.checked.filename,
        extension=file.checked.extension,
        detected_mime=file.checked.type.mime,
        size_bytes=len(file.data),
        sha256=hashlib.sha256(file.data).digest(),
    )
    db.add(attachment)
    await db.flush()
    return attachment


# --- Partner ---------------------------------------------------------------------------


async def partner_offer(
    db: AsyncSession, partner: PartnerOrganisation, match_id: uuid.UUID, *, lock: bool = False
) -> Offer:
    offer = await get_offer(db, partner, match_id, lock=lock)
    if offer.claim is None:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "not_claimed",
            "Accept this referral before messaging the customer.",
        )
    return offer


async def partner_send(
    db: AsyncSession,
    partner: PartnerOrganisation,
    match_id: uuid.UUID,
    body: str,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
    now: datetime,
    file: FileToSend | None = None,
) -> tuple[Offer, Sent]:
    offer = await partner_offer(db, partner, match_id, lock=True)
    await ensure_customer_open(db, offer.lead)
    sent = await _post(
        db,
        offer.match,
        MessageSender.PARTNER,
        body,
        actor_id=actor_id,
        organisation_id=partner.organisation_id,
        meta=meta,
        now=now,
        file=file,
    )
    return offer, sent


# --- Customer --------------------------------------------------------------------------


@dataclass(frozen=True)
class CustomerConversation:
    match: LeadMatch
    lead: Lead
    category: MarketplaceCategory
    organisation: Organisation  # the partner's

    async def out(self, db: AsyncSession) -> ConversationOut:
        return await conversation_out(
            db,
            self.match,
            category_label=self.category.label,
            partner_name=self.organisation.name,
            viewer=MessageSender.CUSTOMER,
        )


def _customer_query(project: Project):  # type: ignore[no-untyped-def]
    return (
        select(LeadMatch, Lead, MarketplaceCategory, Organisation)
        .join(Lead, Lead.id == LeadMatch.lead_id)
        .join(LeadClaim, LeadClaim.lead_match_id == LeadMatch.id)
        .join(MarketplaceCategory, MarketplaceCategory.id == Lead.category_id)
        .join(PartnerOrganisation, PartnerOrganisation.id == LeadMatch.partner_organisation_id)
        .join(Organisation, Organisation.id == PartnerOrganisation.organisation_id)
        .where(Lead.organisation_id == project.organisation_id, Lead.project_id == project.id)
    )


async def for_project(db: AsyncSession, project: Project) -> list[CustomerConversation]:
    """One conversation per partner who accepted one of the project's referrals, in the
    order they accepted."""
    rows = await db.execute(
        _customer_query(project).order_by(MarketplaceCategory.sort_order, LeadClaim.created_at)
    )
    return [CustomerConversation(*row) for row in rows]


async def get_for_customer(
    db: AsyncSession, project: Project, match_id: uuid.UUID, *, lock: bool = False
) -> CustomerConversation:
    row = (await db.execute(_customer_query(project).where(LeadMatch.id == match_id))).one_or_none()
    if row is None:
        raise not_found("Conversation")
    found = CustomerConversation(*row)
    if lock:
        await db.execute(select(Lead.id).where(Lead.id == found.lead.id).with_for_update())
        await db.refresh(found.match, with_for_update=True)
    return found


async def customer_send(
    db: AsyncSession,
    project: Project,
    match_id: uuid.UUID,
    body: str,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
    now: datetime,
    file: FileToSend | None = None,
) -> tuple[CustomerConversation, Sent]:
    found = await get_for_customer(db, project, match_id, lock=True)
    sent = await _post(
        db,
        found.match,
        MessageSender.CUSTOMER,
        body,
        actor_id=actor_id,
        organisation_id=project.organisation_id,
        meta=meta,
        now=now,
        file=file,
    )
    return found, sent
