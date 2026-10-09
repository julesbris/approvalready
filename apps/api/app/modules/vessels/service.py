"""Vessel certificates and the safety management system builder.

Callers have checked permissions and bound the tenant; queries still filter by
``organisation_id``. Audit events record what changed (fields, element keys), never the
text itself.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, not_found
from app.modules.assessments.service import assessment_date
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.documents import service as documents
from app.modules.entities import service as entities
from app.modules.entities.models import Vessel
from app.modules.projects.models import Project, Vertical
from app.modules.vessels import sms
from app.modules.vessels.models import SafetyManagementSystem, VesselCertificate

# A certificate is flagged as expiring this many days before it does.
EXPIRING_WITHIN_DAYS = 60


class CertificateState(StrEnum):
    CURRENT = "CURRENT"
    EXPIRING = "EXPIRING"
    EXPIRED = "EXPIRED"
    NO_EXPIRY = "NO_EXPIRY"


def certificate_state(certificate: VesselCertificate, today: date | None = None) -> str:
    if certificate.expires_on is None:
        return CertificateState.NO_EXPIRY
    today = today or assessment_date()
    if certificate.expires_on < today:
        return CertificateState.EXPIRED
    if certificate.expires_on <= today + timedelta(days=EXPIRING_WITHIN_DAYS):
        return CertificateState.EXPIRING
    return CertificateState.CURRENT


# --- Certificates ----------------------------------------------------------------------


async def list_certificates(db: AsyncSession, vessel: Vessel) -> list[VesselCertificate]:
    return list(
        (
            await db.execute(
                select(VesselCertificate)
                .where(
                    VesselCertificate.organisation_id == vessel.organisation_id,
                    VesselCertificate.vessel_id == vessel.id,
                    VesselCertificate.deleted_at.is_(None),
                )
                .order_by(VesselCertificate.expires_on.asc().nulls_last(), VesselCertificate.id)
            )
        ).scalars()
    )


async def get_certificate(
    db: AsyncSession, organisation_id: uuid.UUID, certificate_id: uuid.UUID
) -> VesselCertificate:
    certificate = (
        await db.execute(
            select(VesselCertificate).where(
                VesselCertificate.id == certificate_id,
                VesselCertificate.organisation_id == organisation_id,
                VesselCertificate.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if certificate is None:
        raise not_found("Certificate")
    return certificate


async def _check_document(
    db: AsyncSession, organisation_id: uuid.UUID, document_id: uuid.UUID | None
) -> None:
    if document_id is None:
        return
    documents.require_clean(await documents.get_document(db, organisation_id, document_id))


def _check_dates(issued_on: date | None, expires_on: date | None) -> None:
    if issued_on is not None and expires_on is not None and expires_on < issued_on:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "dates_out_of_order",
            "The expiry date can't be before the issue date.",
        )


async def _audit_certificate(
    db: AsyncSession,
    action: str,
    certificate: VesselCertificate,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
    fields: list[str] | None = None,
) -> None:
    details: dict[str, Any] = {"vessel_id": str(certificate.vessel_id), "kind": certificate.kind}
    if fields is not None:
        details["fields"] = sorted(fields)
    await audit.record(
        db,
        f"vessel_certificate.{action}",
        actor_user_id=actor_id,
        organisation_id=certificate.organisation_id,
        target_type="vessel_certificate",
        target_id=certificate.id,
        meta=meta,
        details=details,
    )


async def add_certificate(
    db: AsyncSession,
    vessel: Vessel,
    data: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> VesselCertificate:
    _check_dates(data.get("issued_on"), data.get("expires_on"))
    await _check_document(db, vessel.organisation_id, data.get("uploaded_document_id"))
    certificate = VesselCertificate(
        organisation_id=vessel.organisation_id, vessel_id=vessel.id, created_by=actor_id, **data
    )
    db.add(certificate)
    await db.flush()
    await _audit_certificate(db, "added", certificate, actor_id=actor_id, meta=meta)
    return certificate


async def update_certificate(
    db: AsyncSession,
    certificate: VesselCertificate,
    changes: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> VesselCertificate:
    _check_dates(
        changes.get("issued_on", certificate.issued_on),
        changes.get("expires_on", certificate.expires_on),
    )
    if changes.get("uploaded_document_id") not in (None, certificate.uploaded_document_id):
        await _check_document(db, certificate.organisation_id, changes["uploaded_document_id"])
    changed = [k for k, v in changes.items() if getattr(certificate, k) != v]
    for key in changed:
        setattr(certificate, key, changes[key])
    if changed:
        await db.flush()
        await _audit_certificate(
            db, "updated", certificate, actor_id=actor_id, meta=meta, fields=changed
        )
    return certificate


async def delete_certificate(
    db: AsyncSession,
    certificate: VesselCertificate,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> None:
    certificate.deleted_at = datetime.now(UTC)
    await db.flush()
    await _audit_certificate(db, "deleted", certificate, actor_id=actor_id, meta=meta)


# --- Safety management system ----------------------------------------------------------


def _require_vessel_project(project: Project) -> None:
    if project.vertical != Vertical.VESSEL:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "not_a_vessel_project",
            "A safety management system belongs to a vessel project.",
        )


async def get_sms(db: AsyncSession, project: Project) -> SafetyManagementSystem | None:
    _require_vessel_project(project)
    return (
        await db.execute(
            select(SafetyManagementSystem).where(
                SafetyManagementSystem.organisation_id == project.organisation_id,
                SafetyManagementSystem.project_id == project.id,
            )
        )
    ).scalar_one_or_none()


async def save_sms(
    db: AsyncSession,
    project: Project,
    changes: dict[str, str | None],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> SafetyManagementSystem:
    """Merge ``changes`` (element key → text, or ``None`` to clear) into the project's SMS,
    creating it on first save."""
    _require_vessel_project(project)
    try:
        cleaned = sms.clean_content(changes)
    except ValueError as exc:
        raise ApiError(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_sms", str(exc)) from exc
    record = await get_sms(db, project)
    if record is None:
        record = SafetyManagementSystem(
            organisation_id=project.organisation_id,
            project_id=project.id,
            content={},
            structure_hash=sms.structure().content_hash(),
            created_by=actor_id,
        )
        db.add(record)
    content = dict(record.content)
    changed = []
    for key, text in cleaned.items():
        if content.get(key) == text:
            continue
        changed.append(key)
        if text is None:
            content.pop(key, None)
        else:
            content[key] = text
    if changed or record.id is None:
        record.content = content
        record.structure_hash = sms.structure().content_hash()
        record.updated_by = actor_id
        await db.flush()
    if changed:
        await audit.record(
            db,
            "sms.saved",
            actor_user_id=actor_id,
            organisation_id=project.organisation_id,
            target_type="safety_management_system",
            target_id=record.id,
            meta=meta,
            details={"project_id": str(project.id), "elements": sorted(changed)},
        )
    return record


def _number(value: Decimal | None) -> str:
    return format(value.normalize(), "f") if value is not None else ""


TYPE_LABELS = {
    "MOTOR": "motor vessel",
    "SAIL": "sailing vessel",
    "PERSONAL_WATERCRAFT": "personal watercraft",
    "PADDLE": "paddle craft",
    "BARGE": "barge",
    "OTHER": "vessel",
}


@dataclass(frozen=True)
class SmsSuggestion:
    key: str
    text: str


async def suggestions(db: AsyncSession, project: Project) -> list[SmsSuggestion]:
    """Starting text for elements marked ``prefill`` from the linked vessel's details, which
    the customer typed. Offered, never saved."""
    if project.vessel_id is None:
        return []
    vessel = await entities.get_entity(db, Vessel, project.organisation_id, project.vessel_id)
    parts = [f"{vessel.name} is a {TYPE_LABELS.get(vessel.vessel_type, 'vessel')}"]
    if vessel.length_m is not None:
        parts[0] += f" of {_number(vessel.length_m)} metres overall"
    parts[0] += "."
    if vessel.uvi:
        parts.append(f"Unique Vessel Identifier: {vessel.uvi}.")
    if vessel.hull_material:
        parts.append(f"Hull: {vessel.hull_material}.")
    if vessel.propulsion:
        parts.append(f"Propulsion: {vessel.propulsion.replace('_', ' ').lower()}.")
    if vessel.max_passengers is not None:
        parts.append(f"Maximum passengers: {vessel.max_passengers}.")
    if vessel.crew is not None:
        parts.append(f"Crew: {vessel.crew}.")
    if vessel.activity:
        parts.append(f"Activity: {vessel.activity}.")
    if vessel.operating_area:
        parts.append(f"Operating area: {vessel.operating_area}.")
    text = " ".join(parts)
    return [
        SmsSuggestion(e.key, text)
        for e in sms.structure().elements.values()
        if e.prefill == "vessel_description"
    ]
