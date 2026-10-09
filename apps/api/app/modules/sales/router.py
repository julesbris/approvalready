"""SellReady: ``/v1/organisations/{organisation_id}/projects/{id}/sale`` (the sale, its
disclosure, vault, offers and enquiries), ``/sale-documents/{id}``, ``/sale-offers/{id}``
and ``/sale-enquiries/{id}``."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DbDep, MetaDep, OrgContext, require_org_permission
from app.modules.documents.models import UploadedDocument
from app.modules.projects import service as projects
from app.modules.projects.models import Project
from app.modules.sales import service
from app.modules.sales.models import (
    Sale,
    SaleDocument,
    SaleEnquiry,
    SaleOffer,
    SaleStatus,
    VaultCategory,
)
from app.modules.sales.schemas import (
    DisclosureGive,
    DisclosureNotNeeded,
    DisclosureOut,
    EnquiryCreate,
    EnquiryOut,
    EnquiryUpdate,
    OfferCreate,
    OfferOut,
    OfferUpdate,
    SaleDocumentCreate,
    SaleDocumentOut,
    SaleDocumentUpdate,
    SaleOut,
    SaleUpdate,
)
from app.modules.tenancy.rbac import Perm

router = APIRouter(prefix="/v1/organisations/{organisation_id}", tags=["sales"])

Read = Annotated[OrgContext, Depends(require_org_permission(Perm.PROJECT_READ))]
Write = Annotated[OrgContext, Depends(require_org_permission(Perm.PROJECT_WRITE))]


async def _project(db: AsyncSession, ctx: OrgContext, project_id: uuid.UUID) -> Project:
    project = await projects.get_project(db, ctx.organisation.id, project_id)
    service.require_sell_project(project)
    return project


async def sale_out(db: AsyncSession, project: Project, sale: Sale | None) -> SaleOut:
    marked = await service.disclosure_ids(db, sale) if sale is not None else []
    offers, enquiries = await service.counts(db, sale) if sale is not None else (0, 0)
    current = SaleStatus(sale.status) if sale is not None else SaleStatus.PREPARING
    given = list(sale.disclosure_document_ids) if sale is not None else []
    return SaleOut(
        id=sale.id if sale else None,
        project_id=project.id,
        status=current,
        next_statuses=list(service.TRANSITIONS[current]),
        asking_price_cents=sale.asking_price_cents if sale else None,
        price_guide=sale.price_guide if sale else None,
        listed_on=sale.listed_on if sale else None,
        contract_on=sale.contract_on if sale else None,
        settlement_on=sale.settlement_on if sale else None,
        notes=sale.notes if sale else None,
        disclosure=DisclosureOut(
            state=service.disclosure_state(sale, marked),
            given_on=sale.disclosure_given_on if sale else None,
            given_to=sale.disclosure_given_to if sale else None,
            not_needed_note=sale.disclosure_not_needed_note if sale else None,
            document_ids=marked,
            changed_since_given=bool(
                sale and sale.disclosure_given_on and set(given) != set(marked)
            ),
        ),
        offers=offers,
        open_enquiries=enquiries,
        updated_at=sale.updated_at if sale else None,
    )


def document_out(record: SaleDocument, upload: UploadedDocument) -> SaleDocumentOut:
    return SaleDocumentOut(
        id=record.id,
        uploaded_document_id=record.uploaded_document_id,
        category=VaultCategory(record.category),
        title=record.title,
        in_disclosure=record.in_disclosure,
        filename=upload.original_filename,
        size_bytes=upload.size_bytes,
        scan_status=upload.scan_status,
        created_at=record.created_at,
    )


def offer_out(o: SaleOffer) -> OfferOut:
    return OfferOut.model_validate(o, from_attributes=True)


def enquiry_out(e: SaleEnquiry) -> EnquiryOut:
    return EnquiryOut.model_validate(e, from_attributes=True)


# --- Sale and disclosure ---------------------------------------------------------------


@router.get("/projects/{project_id}/sale", response_model=SaleOut)
async def get_sale(project_id: uuid.UUID, ctx: Read, db: DbDep) -> SaleOut:
    project = await _project(db, ctx, project_id)
    return await sale_out(db, project, await service.get_sale(db, project))


@router.patch("/projects/{project_id}/sale", response_model=SaleOut)
async def update_sale(
    project_id: uuid.UUID, body: SaleUpdate, ctx: Write, db: DbDep, meta: MetaDep
) -> SaleOut:
    """Change the sale's details or move it to another status (``next_statuses``)."""
    project = await _project(db, ctx, project_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("status") is None:
        changes.pop("status", None)
    sale = await service.update_sale(db, project, changes, actor_id=ctx.auth.user.id, meta=meta)
    await db.commit()
    return await sale_out(db, project, sale)


@router.post("/projects/{project_id}/sale/disclosure", response_model=SaleOut)
async def give_disclosure(
    project_id: uuid.UUID, body: DisclosureGive, ctx: Write, db: DbDep, meta: MetaDep
) -> SaleOut:
    """Record that the documents marked for disclosure were given to a buyer."""
    project = await _project(db, ctx, project_id)
    sale = await service.give_disclosure(
        db, project, body.given_on, body.given_to, actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    return await sale_out(db, project, sale)


@router.post("/projects/{project_id}/sale/disclosure/not-needed", response_model=SaleOut)
async def disclosure_not_needed(
    project_id: uuid.UUID, body: DisclosureNotNeeded, ctx: Write, db: DbDep, meta: MetaDep
) -> SaleOut:
    project = await _project(db, ctx, project_id)
    sale = await service.disclosure_not_needed(
        db, project, body.note, actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    return await sale_out(db, project, sale)


@router.delete("/projects/{project_id}/sale/disclosure", response_model=SaleOut)
async def reopen_disclosure(project_id: uuid.UUID, ctx: Write, db: DbDep, meta: MetaDep) -> SaleOut:
    """Undo "given" or "not needed" so the disclosure can be changed (not once under
    contract)."""
    project = await _project(db, ctx, project_id)
    sale = await service.reopen_disclosure(db, project, actor_id=ctx.auth.user.id, meta=meta)
    await db.commit()
    return await sale_out(db, project, sale)


# --- Vault -----------------------------------------------------------------------------


@router.get("/projects/{project_id}/sale/documents", response_model=list[SaleDocumentOut])
async def list_documents(project_id: uuid.UUID, ctx: Read, db: DbDep) -> list[SaleDocumentOut]:
    project = await _project(db, ctx, project_id)
    sale = await service.get_sale(db, project)
    if sale is None:
        return []
    return [document_out(r, u) for r, u in await service.list_documents(db, sale)]


@router.post(
    "/projects/{project_id}/sale/documents",
    status_code=status.HTTP_201_CREATED,
    response_model=SaleDocumentOut,
)
async def add_document(
    project_id: uuid.UUID, body: SaleDocumentCreate, ctx: Write, db: DbDep, meta: MetaDep
) -> SaleDocumentOut:
    """File one of the project's uploads in the vault."""
    project = await _project(db, ctx, project_id)
    record = await service.add_document(
        db, project, body.model_dump(), actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    upload = await db.get(UploadedDocument, record.uploaded_document_id)
    assert upload is not None
    return document_out(record, upload)


@router.patch("/sale-documents/{document_id}", response_model=SaleDocumentOut)
async def update_document(
    document_id: uuid.UUID, body: SaleDocumentUpdate, ctx: Write, db: DbDep, meta: MetaDep
) -> SaleDocumentOut:
    record, sale, _ = await service.get_document(db, ctx.organisation.id, document_id)
    await service.update_document(
        db, record, sale, body.model_dump(exclude_unset=True), actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    upload = await db.get(UploadedDocument, record.uploaded_document_id)
    assert upload is not None
    return document_out(record, upload)


@router.delete("/sale-documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_document(document_id: uuid.UUID, ctx: Write, db: DbDep, meta: MetaDep) -> None:
    """Take a file out of the vault (the upload itself stays in the project's documents)."""
    record, sale, _ = await service.get_document(db, ctx.organisation.id, document_id)
    await service.remove_document(db, record, sale, actor_id=ctx.auth.user.id, meta=meta)
    await db.commit()


# --- Offers ----------------------------------------------------------------------------


@router.get("/projects/{project_id}/sale/offers", response_model=list[OfferOut])
async def list_offers(project_id: uuid.UUID, ctx: Read, db: DbDep) -> list[OfferOut]:
    project = await _project(db, ctx, project_id)
    sale = await service.get_sale(db, project)
    return [offer_out(o) for o in await service.list_offers(db, sale)] if sale else []


@router.post(
    "/projects/{project_id}/sale/offers",
    status_code=status.HTTP_201_CREATED,
    response_model=OfferOut,
)
async def add_offer(
    project_id: uuid.UUID, body: OfferCreate, ctx: Write, db: DbDep, meta: MetaDep
) -> OfferOut:
    project = await _project(db, ctx, project_id)
    offer = await service.add_offer(
        db, project, body.model_dump(), actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    return offer_out(offer)


@router.patch("/sale-offers/{offer_id}", response_model=OfferOut)
async def update_offer(
    offer_id: uuid.UUID, body: OfferUpdate, ctx: Write, db: DbDep, meta: MetaDep
) -> OfferOut:
    """Change an offer; accepting one puts a listed sale under offer."""
    offer, sale, _ = await service.get_offer(db, ctx.organisation.id, offer_id)
    await service.update_offer(
        db, offer, sale, body.model_dump(exclude_unset=True), actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    return offer_out(offer)


# --- Enquiries -------------------------------------------------------------------------


@router.get("/projects/{project_id}/sale/enquiries", response_model=list[EnquiryOut])
async def list_enquiries(project_id: uuid.UUID, ctx: Read, db: DbDep) -> list[EnquiryOut]:
    project = await _project(db, ctx, project_id)
    sale = await service.get_sale(db, project)
    return [enquiry_out(e) for e in await service.list_enquiries(db, sale)] if sale else []


@router.post(
    "/projects/{project_id}/sale/enquiries",
    status_code=status.HTTP_201_CREATED,
    response_model=EnquiryOut,
)
async def add_enquiry(
    project_id: uuid.UUID, body: EnquiryCreate, ctx: Write, db: DbDep, meta: MetaDep
) -> EnquiryOut:
    project = await _project(db, ctx, project_id)
    enquiry = await service.add_enquiry(
        db, project, body.model_dump(), actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    return enquiry_out(enquiry)


@router.patch("/sale-enquiries/{enquiry_id}", response_model=EnquiryOut)
async def update_enquiry(
    enquiry_id: uuid.UUID, body: EnquiryUpdate, ctx: Write, db: DbDep, meta: MetaDep
) -> EnquiryOut:
    enquiry, _ = await service.get_enquiry(db, ctx.organisation.id, enquiry_id)
    await service.update_enquiry(
        db, enquiry, body.model_dump(exclude_unset=True), actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    return enquiry_out(enquiry)
