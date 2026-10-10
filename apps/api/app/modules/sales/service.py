"""SellReady: the sale workflow, its vault and disclosure, offers and enquiries.

Callers check permissions and bind the tenant; queries still filter by organisation. Audit
events name what changed (fields, statuses, document ids), never buyers' names, contact
details, amounts or messages.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, not_found
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.documents import service as documents
from app.modules.documents.models import UploadedDocument
from app.modules.notifications import reminders
from app.modules.projects.models import Project, Vertical
from app.modules.sales.models import (
    EnquiryStatus,
    OfferStatus,
    Sale,
    SaleDocument,
    SaleEnquiry,
    SaleOffer,
    SaleStatus,
)
from app.modules.sales.schemas import DisclosureState

S = SaleStatus

# Where a sale can go next. Going back is allowed where a sale really does go back: a
# buyer walks away (under offer → listed) or a contract ends (under contract → listed).
TRANSITIONS: dict[SaleStatus, tuple[SaleStatus, ...]] = {
    S.PREPARING: (S.READY_TO_LIST, S.LISTED, S.WITHDRAWN),
    S.READY_TO_LIST: (S.PREPARING, S.LISTED, S.WITHDRAWN),
    S.LISTED: (S.READY_TO_LIST, S.UNDER_OFFER, S.UNDER_CONTRACT, S.WITHDRAWN),
    S.UNDER_OFFER: (S.LISTED, S.UNDER_CONTRACT, S.WITHDRAWN),
    S.UNDER_CONTRACT: (S.LISTED, S.SETTLED, S.WITHDRAWN),
    S.SETTLED: (),
    S.WITHDRAWN: (S.PREPARING, S.LISTED),
}

# Reminders before settlement (our nudges; the contract sets the real date).
SETTLEMENT_REMIND_DAYS = (14, 2)

OPEN_OFFER = (OfferStatus.RECEIVED, OfferStatus.COUNTERED)


def today() -> date:
    return reminders.local_today()


def _conflict(code: str, message: str) -> ApiError:
    return ApiError(status.HTTP_409_CONFLICT, code, message)


def _invalid(code: str, message: str) -> ApiError:
    return ApiError(status.HTTP_422_UNPROCESSABLE_CONTENT, code, message)


def require_sell_project(project: Project) -> None:
    if project.vertical != Vertical.SELL:
        raise _conflict("not_a_sale_project", "Sales belong to a selling project.")


async def _audit(
    db: AsyncSession,
    action: str,
    organisation_id: uuid.UUID,
    target_type: str,
    target_id: uuid.UUID,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
    **details: Any,
) -> None:
    await audit.record(
        db,
        action,
        actor_user_id=actor_id,
        organisation_id=organisation_id,
        target_type=target_type,
        target_id=target_id,
        meta=meta,
        details={k: v for k, v in details.items() if v is not None},
    )


# --- Sale ------------------------------------------------------------------------------


async def get_sale(db: AsyncSession, project: Project, *, lock: bool = False) -> Sale | None:
    require_sell_project(project)
    query = select(Sale).where(
        Sale.organisation_id == project.organisation_id, Sale.project_id == project.id
    )
    if lock:
        query = query.with_for_update()
    return (await db.execute(query)).scalar_one_or_none()


async def ensure_sale(db: AsyncSession, project: Project, actor_id: uuid.UUID) -> Sale:
    sale = await get_sale(db, project, lock=True)
    if sale is None:
        sale = Sale(
            organisation_id=project.organisation_id,
            project_id=project.id,
            created_by=actor_id,
            disclosure_document_ids=[],
        )
        db.add(sale)
        await db.flush()
    return sale


async def disclosure_ids(db: AsyncSession, sale: Sale) -> list[uuid.UUID]:
    return list(
        (
            await db.execute(
                select(SaleDocument.uploaded_document_id)
                .where(
                    SaleDocument.organisation_id == sale.organisation_id,
                    SaleDocument.sale_id == sale.id,
                    SaleDocument.in_disclosure.is_(True),
                )
                .order_by(SaleDocument.created_at)
            )
        ).scalars()
    )


def disclosure_state(sale: Sale | None, marked: list[uuid.UUID]) -> DisclosureState:
    if sale is not None and sale.disclosure_given_on is not None:
        return DisclosureState.GIVEN
    if sale is not None and sale.disclosure_not_needed_note:
        return DisclosureState.NOT_NEEDED
    return DisclosureState.PREPARING if marked else DisclosureState.NOT_STARTED


async def counts(db: AsyncSession, sale: Sale) -> tuple[int, int]:
    offers = (
        await db.execute(
            select(func.count()).where(
                SaleOffer.organisation_id == sale.organisation_id,
                SaleOffer.sale_id == sale.id,
                SaleOffer.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    enquiries = (
        await db.execute(
            select(func.count()).where(
                SaleEnquiry.organisation_id == sale.organisation_id,
                SaleEnquiry.sale_id == sale.id,
                SaleEnquiry.deleted_at.is_(None),
                SaleEnquiry.status == EnquiryStatus.NEW,
            )
        )
    ).scalar_one()
    return int(offers), int(enquiries)


def _check_transition(sale: Sale, to: SaleStatus, marked: list[uuid.UUID]) -> None:
    current = SaleStatus(sale.status)
    if to == current:
        return
    if to not in TRANSITIONS[current]:
        raise _conflict(
            "invalid_transition",
            f"A sale that is {current.lower().replace('_', ' ')} can't move to "
            f"{to.lower().replace('_', ' ')}.",
        )
    if to == S.UNDER_CONTRACT and disclosure_state(sale, marked) not in (
        DisclosureState.GIVEN,
        DisclosureState.NOT_NEEDED,
    ):
        raise _conflict(
            "disclosure_not_given",
            "Record when the disclosure documents were given to the buyer, or why none are "
            "needed, before recording a contract.",
        )


async def update_sale(
    db: AsyncSession,
    project: Project,
    changes: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> Sale:
    sale = await ensure_sale(db, project, actor_id)
    to = changes.get("status")
    if to is not None:
        _check_transition(sale, SaleStatus(to), await disclosure_ids(db, sale))
        if to == S.LISTED and sale.listed_on is None and "listed_on" not in changes:
            changes["listed_on"] = today()
        if to == S.UNDER_CONTRACT and sale.contract_on is None and "contract_on" not in changes:
            changes["contract_on"] = today()
        if to == S.SETTLED and sale.settlement_on is None and "settlement_on" not in changes:
            changes["settlement_on"] = today()
    contract_on = changes.get("contract_on", sale.contract_on)
    settlement_on = changes.get("settlement_on", sale.settlement_on)
    if contract_on and settlement_on and settlement_on < contract_on:
        raise _invalid("dates_out_of_order", "Settlement can't be before the contract date.")
    changed = [k for k, v in changes.items() if getattr(sale, k) != v]
    before = sale.status
    for key in changed:
        setattr(sale, key, changes[key])
    if changed:
        await db.flush()
        await _audit(
            db,
            "sale.updated",
            sale.organisation_id,
            "sale_project",
            sale.id,
            actor_id=actor_id,
            meta=meta,
            fields=sorted(changed),
            **({"from_status": before, "to_status": sale.status} if "status" in changed else {}),
        )
    await _sync_reminders(db, project, sale, actor_id)
    return sale


async def _sync_reminders(
    db: AsyncSession, project: Project, sale: Sale, actor_id: uuid.UUID
) -> None:
    prefix = f"sale:{sale.id}:settlement:"
    if sale.status != S.UNDER_CONTRACT:
        await reminders.cancel(db, sale.organisation_id, prefix)
        return
    when = sale.settlement_on.strftime("%-d %B %Y") if sale.settlement_on else ""
    await reminders.sync(
        db,
        sale.organisation_id,
        prefix,
        reminders.before(
            prefix,
            sale.settlement_on,
            SETTLEMENT_REMIND_DAYS,
            f"Settlement is due {when}",
            "Check with your conveyancer or solicitor that everything for settlement is ready.",
        ),
        recipient_user_id=actor_id,
        project_id=project.id,
        link_path=f"/projects/{project.id}/sale",
        actor_id=actor_id,
    )


# --- Disclosure ------------------------------------------------------------------------


async def give_disclosure(
    db: AsyncSession,
    project: Project,
    given_on: date,
    given_to: str,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> Sale:
    sale = await ensure_sale(db, project, actor_id)
    if sale.disclosure_given_on is not None:
        raise _conflict(
            "disclosure_already_given",
            "The disclosure was already given. Reopen it first to record a new one.",
        )
    if given_on > today():
        raise _invalid("in_the_future", "The date given can't be in the future.")
    marked = await disclosure_ids(db, sale)
    if not marked:
        raise _conflict(
            "no_disclosure_documents",
            "Mark at least one document in the vault as part of the disclosure first.",
        )
    for document_id in marked:
        documents.require_clean(await documents.get_document(db, sale.organisation_id, document_id))
    sale.disclosure_given_on = given_on
    sale.disclosure_given_to = given_to
    sale.disclosure_document_ids = marked
    sale.disclosure_not_needed_note = None
    await db.flush()
    await _audit(
        db,
        "sale.disclosure_given",
        sale.organisation_id,
        "sale_project",
        sale.id,
        actor_id=actor_id,
        meta=meta,
        given_on=given_on.isoformat(),
        document_ids=[str(d) for d in marked],
    )
    return sale


async def disclosure_not_needed(
    db: AsyncSession, project: Project, note: str, *, actor_id: uuid.UUID, meta: RequestMeta | None
) -> Sale:
    sale = await ensure_sale(db, project, actor_id)
    if sale.disclosure_given_on is not None:
        raise _conflict(
            "disclosure_already_given", "The disclosure was already given. Reopen it first."
        )
    sale.disclosure_not_needed_note = note
    await db.flush()
    await _audit(
        db,
        "sale.disclosure_not_needed",
        sale.organisation_id,
        "sale_project",
        sale.id,
        actor_id=actor_id,
        meta=meta,
    )
    return sale


async def reopen_disclosure(
    db: AsyncSession, project: Project, *, actor_id: uuid.UUID, meta: RequestMeta | None
) -> Sale:
    sale = await ensure_sale(db, project, actor_id)
    if sale.status in (S.UNDER_CONTRACT, S.SETTLED):
        raise _conflict(
            "sale_under_contract",
            "The sale is under contract. Talk to your conveyancer or solicitor before changing "
            "what was disclosed.",
        )
    if sale.disclosure_given_on is None and not sale.disclosure_not_needed_note:
        return sale
    sale.disclosure_given_on = None
    sale.disclosure_given_to = None
    sale.disclosure_not_needed_note = None
    sale.disclosure_document_ids = []
    await db.flush()
    await _audit(
        db,
        "sale.disclosure_reopened",
        sale.organisation_id,
        "sale_project",
        sale.id,
        actor_id=actor_id,
        meta=meta,
    )
    return sale


# --- Vault -----------------------------------------------------------------------------


async def list_documents(
    db: AsyncSession, sale: Sale
) -> list[tuple[SaleDocument, UploadedDocument]]:
    return list(
        (
            await db.execute(
                select(SaleDocument, UploadedDocument)
                .join(
                    UploadedDocument,
                    (UploadedDocument.organisation_id == SaleDocument.organisation_id)
                    & (UploadedDocument.id == SaleDocument.uploaded_document_id),
                )
                .where(
                    SaleDocument.organisation_id == sale.organisation_id,
                    SaleDocument.sale_id == sale.id,
                    UploadedDocument.deleted_at.is_(None),
                )
                .order_by(SaleDocument.category, SaleDocument.created_at)
            )
        ).tuples()
    )


async def get_document(
    db: AsyncSession, organisation_id: uuid.UUID, sale_document_id: uuid.UUID
) -> tuple[SaleDocument, Sale, Project]:
    row = (
        await db.execute(
            select(SaleDocument, Sale, Project)
            .join(
                Sale,
                (Sale.organisation_id == SaleDocument.organisation_id)
                & (Sale.id == SaleDocument.sale_id),
            )
            .join(
                Project,
                (Project.organisation_id == Sale.organisation_id) & (Project.id == Sale.project_id),
            )
            .where(
                SaleDocument.id == sale_document_id,
                SaleDocument.organisation_id == organisation_id,
                Project.deleted_at.is_(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise not_found("Vault document")
    return row[0], row[1], row[2]


def _locked_after_given(sale: Sale, document: SaleDocument | None = None) -> None:
    if sale.disclosure_given_on is not None and (document is None or document.in_disclosure):
        raise _conflict(
            "disclosure_already_given",
            "This document was part of the disclosure already given. Reopen the disclosure first.",
        )


async def add_document(
    db: AsyncSession,
    project: Project,
    data: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> SaleDocument:
    sale = await ensure_sale(db, project, actor_id)
    upload = await documents.get_document(db, project.organisation_id, data["uploaded_document_id"])
    if upload.project_id != project.id:
        raise _invalid("document_not_in_project", "Upload the file to this project first.")
    if data.get("in_disclosure"):
        _locked_after_given(sale)
    exists = (
        await db.execute(
            select(SaleDocument.id).where(
                SaleDocument.organisation_id == sale.organisation_id,
                SaleDocument.sale_id == sale.id,
                SaleDocument.uploaded_document_id == upload.id,
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise _conflict("already_in_vault", "That file is already in the vault.")
    record = SaleDocument(
        organisation_id=sale.organisation_id, sale_id=sale.id, created_by=actor_id, **data
    )
    db.add(record)
    await db.flush()
    await _audit(
        db,
        "sale.document_added",
        sale.organisation_id,
        "sale_document",
        record.id,
        actor_id=actor_id,
        meta=meta,
        category=record.category,
        in_disclosure=record.in_disclosure,
    )
    return record


async def update_document(
    db: AsyncSession,
    record: SaleDocument,
    sale: Sale,
    changes: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> SaleDocument:
    changes = {k: v for k, v in changes.items() if not (v is None and k != "title")}
    if "in_disclosure" in changes and changes["in_disclosure"] != record.in_disclosure:
        _locked_after_given(sale)
    changed = [k for k, v in changes.items() if getattr(record, k) != v]
    for key in changed:
        setattr(record, key, changes[key])
    if changed:
        await db.flush()
        await _audit(
            db,
            "sale.document_updated",
            sale.organisation_id,
            "sale_document",
            record.id,
            actor_id=actor_id,
            meta=meta,
            fields=sorted(changed),
        )
    return record


async def remove_document(
    db: AsyncSession,
    record: SaleDocument,
    sale: Sale,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> None:
    _locked_after_given(sale, record)
    await db.delete(record)
    await db.flush()
    await _audit(
        db,
        "sale.document_removed",
        sale.organisation_id,
        "sale_document",
        record.id,
        actor_id=actor_id,
        meta=meta,
    )


# --- Offers ----------------------------------------------------------------------------


async def list_offers(db: AsyncSession, sale: Sale) -> list[SaleOffer]:
    return list(
        (
            await db.execute(
                select(SaleOffer)
                .where(
                    SaleOffer.organisation_id == sale.organisation_id,
                    SaleOffer.sale_id == sale.id,
                    SaleOffer.deleted_at.is_(None),
                )
                .order_by(SaleOffer.received_on.desc(), SaleOffer.created_at.desc())
            )
        ).scalars()
    )


async def get_offer(
    db: AsyncSession, organisation_id: uuid.UUID, offer_id: uuid.UUID
) -> tuple[SaleOffer, Sale, Project]:
    row = (
        await db.execute(
            select(SaleOffer, Sale, Project)
            .join(
                Sale,
                (Sale.organisation_id == SaleOffer.organisation_id)
                & (Sale.id == SaleOffer.sale_id),
            )
            .join(
                Project,
                (Project.organisation_id == Sale.organisation_id) & (Project.id == Sale.project_id),
            )
            .where(
                SaleOffer.id == offer_id,
                SaleOffer.organisation_id == organisation_id,
                SaleOffer.deleted_at.is_(None),
                Project.deleted_at.is_(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise not_found("Offer")
    return row[0], row[1], row[2]


async def add_offer(
    db: AsyncSession,
    project: Project,
    data: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> SaleOffer:
    sale = await ensure_sale(db, project, actor_id)
    if sale.status in (S.SETTLED, S.WITHDRAWN):
        raise _conflict("sale_closed", "This sale is closed to new offers.")
    data["received_on"] = data.get("received_on") or today()
    offer = SaleOffer(
        organisation_id=sale.organisation_id, sale_id=sale.id, created_by=actor_id, **data
    )
    db.add(offer)
    await db.flush()
    await _audit(
        db,
        "sale.offer_recorded",
        sale.organisation_id,
        "sale_offer",
        offer.id,
        actor_id=actor_id,
        meta=meta,
    )
    return offer


async def update_offer(
    db: AsyncSession,
    offer: SaleOffer,
    sale: Sale,
    changes: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> SaleOffer:
    required = {"status", "amount_cents", "subject_to_finance", "subject_to_inspection"}
    changes = {k: v for k, v in changes.items() if not (v is None and k in required)}
    to = changes.get("status")
    before = offer.status
    if to == OfferStatus.ACCEPTED and to != before:
        if sale.status not in (S.LISTED, S.UNDER_OFFER, S.READY_TO_LIST, S.PREPARING):
            raise _conflict("sale_not_open", "Offers can only be accepted while the sale is open.")
        accepted = (
            await db.execute(
                select(SaleOffer.id).where(
                    SaleOffer.organisation_id == sale.organisation_id,
                    SaleOffer.sale_id == sale.id,
                    SaleOffer.status == OfferStatus.ACCEPTED,
                    SaleOffer.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if accepted is not None:
            raise _conflict(
                "offer_already_accepted",
                "Another offer is already accepted. Change that one first.",
            )
    changed = [k for k, v in changes.items() if getattr(offer, k) != v]
    for key in changed:
        setattr(offer, key, changes[key])
    if not changed:
        return offer
    await db.flush()
    await _audit(
        db,
        "sale.offer_updated",
        sale.organisation_id,
        "sale_offer",
        offer.id,
        actor_id=actor_id,
        meta=meta,
        fields=sorted(changed),
        **({"from_status": before, "to_status": offer.status} if "status" in changed else {}),
    )
    # Accepting an offer puts a listed property under offer; an accepted offer falling
    # through puts it back on the market.
    if "status" in changed:
        if offer.status == OfferStatus.ACCEPTED and sale.status == S.LISTED:
            await _set_status(db, sale, S.UNDER_OFFER, actor_id, meta)
        elif before == OfferStatus.ACCEPTED and sale.status == S.UNDER_OFFER:
            await _set_status(db, sale, S.LISTED, actor_id, meta)
    return offer


async def _set_status(
    db: AsyncSession, sale: Sale, to: SaleStatus, actor_id: uuid.UUID, meta: RequestMeta | None
) -> None:
    before = sale.status
    sale.status = to
    await db.flush()
    await _audit(
        db,
        "sale.updated",
        sale.organisation_id,
        "sale_project",
        sale.id,
        actor_id=actor_id,
        meta=meta,
        fields=["status"],
        from_status=before,
        to_status=to,
        reason="offer",
    )


# --- Enquiries -------------------------------------------------------------------------


async def list_enquiries(db: AsyncSession, sale: Sale) -> list[SaleEnquiry]:
    return list(
        (
            await db.execute(
                select(SaleEnquiry)
                .where(
                    SaleEnquiry.organisation_id == sale.organisation_id,
                    SaleEnquiry.sale_id == sale.id,
                    SaleEnquiry.deleted_at.is_(None),
                )
                .order_by(SaleEnquiry.received_on.desc(), SaleEnquiry.created_at.desc())
            )
        ).scalars()
    )


async def get_enquiry(
    db: AsyncSession, organisation_id: uuid.UUID, enquiry_id: uuid.UUID
) -> tuple[SaleEnquiry, Sale]:
    row = (
        await db.execute(
            select(SaleEnquiry, Sale)
            .join(
                Sale,
                (Sale.organisation_id == SaleEnquiry.organisation_id)
                & (Sale.id == SaleEnquiry.sale_id),
            )
            .join(
                Project,
                (Project.organisation_id == Sale.organisation_id) & (Project.id == Sale.project_id),
            )
            .where(
                SaleEnquiry.id == enquiry_id,
                SaleEnquiry.organisation_id == organisation_id,
                SaleEnquiry.deleted_at.is_(None),
                Project.deleted_at.is_(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise not_found("Enquiry")
    return row[0], row[1]


async def add_enquiry(
    db: AsyncSession,
    project: Project,
    data: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> SaleEnquiry:
    sale = await ensure_sale(db, project, actor_id)
    data["received_on"] = data.get("received_on") or today()
    enquiry = SaleEnquiry(
        organisation_id=sale.organisation_id, sale_id=sale.id, created_by=actor_id, **data
    )
    db.add(enquiry)
    await db.flush()
    await _audit(
        db,
        "sale.enquiry_recorded",
        sale.organisation_id,
        "sale_enquiry",
        enquiry.id,
        actor_id=actor_id,
        meta=meta,
    )
    return enquiry


async def update_enquiry(
    db: AsyncSession,
    enquiry: SaleEnquiry,
    changes: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> SaleEnquiry:
    changes = {k: v for k, v in changes.items() if not (k == "status" and v is None)}
    changed = [k for k, v in changes.items() if getattr(enquiry, k) != v]
    for key in changed:
        setattr(enquiry, key, changes[key])
    if changed:
        await db.flush()
        await _audit(
            db,
            "sale.enquiry_updated",
            enquiry.organisation_id,
            "sale_enquiry",
            enquiry.id,
            actor_id=actor_id,
            meta=meta,
            fields=sorted(changed),
        )
    return enquiry
