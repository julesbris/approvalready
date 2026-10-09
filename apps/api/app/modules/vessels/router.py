"""VesselReady: ``/v1/organisations/{organisation_id}/vessels/{id}/certificates``,
``/vessel-certificates/{id}`` and ``/projects/{id}/sms``."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DbDep, MetaDep, OrgContext, require_org_permission
from app.modules.entities import service as entities
from app.modules.entities.models import Vessel
from app.modules.projects import service as projects
from app.modules.projects.models import Project
from app.modules.tenancy.rbac import Perm
from app.modules.vessels import service, sms
from app.modules.vessels.models import CertificateKind, VesselCertificate
from app.modules.vessels.schemas import (
    CertificateCreate,
    CertificateOut,
    CertificateUpdate,
    SmsElementOut,
    SmsOut,
    SmsSaveIn,
    SmsSectionOut,
    SmsSourceOut,
)

router = APIRouter(prefix="/v1/organisations/{organisation_id}", tags=["vessels"])

Read = Annotated[OrgContext, Depends(require_org_permission(Perm.PROJECT_READ))]
Write = Annotated[OrgContext, Depends(require_org_permission(Perm.PROJECT_WRITE))]


def certificate_out(c: VesselCertificate) -> CertificateOut:
    return CertificateOut(
        id=c.id,
        vessel_id=c.vessel_id,
        kind=CertificateKind(c.kind),
        title=c.title,
        number=c.number,
        issuer=c.issuer,
        issued_on=c.issued_on,
        expires_on=c.expires_on,
        state=service.certificate_state(c),
        uploaded_document_id=c.uploaded_document_id,
        notes=c.notes,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


@router.get("/vessels/{vessel_id}/certificates", response_model=list[CertificateOut])
async def list_certificates(vessel_id: uuid.UUID, ctx: Read, db: DbDep) -> list[CertificateOut]:
    """The vessel's certificates, soonest expiry first."""
    vessel = await entities.get_entity(db, Vessel, ctx.organisation.id, vessel_id)
    return [certificate_out(c) for c in await service.list_certificates(db, vessel)]


@router.post(
    "/vessels/{vessel_id}/certificates",
    status_code=status.HTTP_201_CREATED,
    response_model=CertificateOut,
)
async def add_certificate(
    vessel_id: uuid.UUID, body: CertificateCreate, ctx: Write, db: DbDep, meta: MetaDep
) -> CertificateOut:
    vessel = await entities.get_entity(db, Vessel, ctx.organisation.id, vessel_id)
    certificate = await service.add_certificate(
        db, vessel, body.model_dump(), actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    return certificate_out(certificate)


@router.patch("/vessel-certificates/{certificate_id}", response_model=CertificateOut)
async def update_certificate(
    certificate_id: uuid.UUID, body: CertificateUpdate, ctx: Write, db: DbDep, meta: MetaDep
) -> CertificateOut:
    certificate = await service.get_certificate(db, ctx.organisation.id, certificate_id)
    changes = {
        k: v
        for k, v in body.model_dump(exclude_unset=True).items()
        if not (k == "kind" and v is None)
    }
    await service.update_certificate(db, certificate, changes, actor_id=ctx.auth.user.id, meta=meta)
    await db.commit()
    return certificate_out(certificate)


@router.delete("/vessel-certificates/{certificate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_certificate(
    certificate_id: uuid.UUID, ctx: Write, db: DbDep, meta: MetaDep
) -> None:
    certificate = await service.get_certificate(db, ctx.organisation.id, certificate_id)
    await service.delete_certificate(db, certificate, actor_id=ctx.auth.user.id, meta=meta)
    await db.commit()


async def _sms_out(db: AsyncSession, project: Project) -> SmsOut:
    record = await service.get_sms(db, project)
    content = record.content if record is not None else {}
    structure = sms.structure()
    offered = {s.key: s.text for s in await service.suggestions(db, project)}
    written, required, _ = sms.completeness(content)
    return SmsOut(
        project_id=project.id,
        title=structure.title,
        description=structure.description,
        disclaimer=structure.disclaimer,
        sources=[SmsSourceOut.model_validate(s.model_dump(mode="json")) for s in structure.sources],
        sections=[
            SmsSectionOut(
                key=section.key,
                title=section.title,
                elements=[
                    SmsElementOut(
                        key=e.key,
                        title=e.title,
                        guidance=e.guidance,
                        required=e.required,
                        text=content.get(e.key),
                        suggestion=None if content.get(e.key) else offered.get(e.key),
                    )
                    for e in section.elements
                ],
            )
            for section in structure.sections
        ],
        written=written,
        required=required,
        saved_at=record.updated_at if record is not None else None,
        outdated_structure=record is not None and record.structure_hash != structure.content_hash(),
    )


@router.get("/projects/{project_id}/sms", response_model=SmsOut)
async def get_sms(project_id: uuid.UUID, ctx: Read, db: DbDep) -> SmsOut:
    """The project's safety management system draft with the structure and guidance."""
    project = await projects.get_project(db, ctx.organisation.id, project_id)
    return await _sms_out(db, project)


@router.put("/projects/{project_id}/sms", response_model=SmsOut)
async def save_sms(
    project_id: uuid.UUID, body: SmsSaveIn, ctx: Write, db: DbDep, meta: MetaDep
) -> SmsOut:
    """Save some parts of the SMS; parts not sent are kept."""
    project = await projects.get_project(db, ctx.organisation.id, project_id)
    await service.save_sms(db, project, body.content, actor_id=ctx.auth.user.id, meta=meta)
    await db.commit()
    return await _sms_out(db, project)
