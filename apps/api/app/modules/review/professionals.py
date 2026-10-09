"""Professionals: profiles, credentials and services, and staff verification.

A professional creates their profile while their practice is the active organisation and
they hold ``review.perform`` there. Staff (``professional.verify``) check each credential
against the issuer's public register and activate the profile. Only an active professional
with a verified, unexpired credential and a service for the project's vertical can be
assigned a review (``eligibility``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, not_found
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.identity.models import AppUser
from app.modules.review.models import (
    CredentialStatus,
    Professional,
    ProfessionalCredential,
    ProfessionalService,
    ProfessionalStatus,
)
from app.modules.tenancy import service as tenancy
from app.modules.tenancy.models import Organisation, OrganisationKind
from app.modules.tenancy.rbac import Perm

MAX_CREDENTIALS = 20


def utcnow() -> datetime:
    return datetime.now(UTC)


def _conflict(code: str, message: str) -> ApiError:
    return ApiError(status.HTTP_409_CONFLICT, code, message)


@dataclass(frozen=True)
class ProfessionalView:
    professional: Professional
    practice: Organisation
    user: AppUser
    credentials: list[ProfessionalCredential]
    services: list[ProfessionalService]


def credential_current(c: ProfessionalCredential, on: date) -> bool:
    return c.status == CredentialStatus.VERIFIED and (c.expires_on is None or c.expires_on >= on)


def eligibility(view: ProfessionalView, vertical: str | None, on: date) -> list[str]:
    """Why this professional can't be assigned a review now (empty when they can)."""
    problems = []
    if view.professional.status != ProfessionalStatus.ACTIVE:
        problems.append("The profile is not active.")
    if not any(credential_current(c, on) for c in view.credentials):
        problems.append("No verified credential is current.")
    if vertical is not None and not any(s.vertical == vertical for s in view.services):
        problems.append("They don't review this kind of project.")
    return problems


async def _audit(
    db: AsyncSession,
    action: str,
    professional: Professional,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
    details: dict[str, Any] | None = None,
) -> None:
    await audit.record(
        db,
        action,
        actor_user_id=actor_id,
        organisation_id=professional.practice_id,
        target_type="professional",
        target_id=professional.id,
        meta=meta,
        details=details,
    )


async def views(db: AsyncSession, professionals: list[Professional]) -> list[ProfessionalView]:
    if not professionals:
        return []
    ids = [p.id for p in professionals]
    credentials: dict[uuid.UUID, list[ProfessionalCredential]] = {i: [] for i in ids}
    for c in (
        await db.execute(
            select(ProfessionalCredential)
            .where(ProfessionalCredential.professional_id.in_(ids))
            .order_by(ProfessionalCredential.created_at)
        )
    ).scalars():
        credentials[c.professional_id].append(c)
    services: dict[uuid.UUID, list[ProfessionalService]] = {i: [] for i in ids}
    for s in (
        await db.execute(
            select(ProfessionalService)
            .where(ProfessionalService.professional_id.in_(ids))
            .order_by(ProfessionalService.vertical)
        )
    ).scalars():
        services[s.professional_id].append(s)
    practices = {
        o.id: o
        for o in (
            await db.execute(
                select(Organisation).where(
                    Organisation.id.in_({p.practice_id for p in professionals})
                )
            )
        ).scalars()
    }
    users = {
        u.id: u
        for u in (
            await db.execute(
                select(AppUser).where(AppUser.id.in_({p.user_id for p in professionals}))
            )
        ).scalars()
    }
    return [
        ProfessionalView(
            p, practices[p.practice_id], users[p.user_id], credentials[p.id], services[p.id]
        )
        for p in professionals
    ]


async def view(db: AsyncSession, professional: Professional) -> ProfessionalView:
    return (await views(db, [professional]))[0]


# --- The professional's own profile ----------------------------------------------------


async def own_profile(
    db: AsyncSession, user_id: uuid.UUID, practice_id: uuid.UUID, *, lock: bool = False
) -> Professional | None:
    query = select(Professional).where(
        Professional.user_id == user_id, Professional.practice_id == practice_id
    )
    if lock:
        query = query.with_for_update()
    return (await db.execute(query)).scalar_one_or_none()


async def create_profile(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    practice: Organisation,
    data: dict[str, Any],
    meta: RequestMeta | None,
) -> Professional:
    if practice.kind != OrganisationKind.PROFESSIONAL_PRACTICE:
        raise _conflict("not_a_practice", "Switch to your practice to set up a reviewer profile.")
    if await own_profile(db, user_id, practice.id) is not None:
        raise _conflict("profile_exists", "You already have a profile in this practice.")
    professional = Professional(
        user_id=user_id,
        practice_id=practice.id,
        status=ProfessionalStatus.PENDING,
        created_by=user_id,
        **data,
    )
    db.add(professional)
    await db.flush()
    await _audit(
        db,
        "professional.created",
        professional,
        actor_id=user_id,
        meta=meta,
        details={"discipline": professional.discipline},
    )
    return professional


async def update_profile(
    db: AsyncSession,
    professional: Professional,
    changes: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> Professional:
    applied = {k: v for k, v in changes.items() if getattr(professional, k) != v}
    if "display_name" in applied and applied["display_name"] is None:
        del applied["display_name"]
    for key, value in applied.items():
        setattr(professional, key, value)
    await db.flush()
    if applied:
        await _audit(
            db,
            "professional.updated",
            professional,
            actor_id=actor_id,
            meta=meta,
            details={"fields": sorted(applied)},
        )
    return professional


async def add_credential(
    db: AsyncSession,
    professional: Professional,
    data: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> ProfessionalCredential:
    existing = (await view(db, professional)).credentials
    if len(existing) >= MAX_CREDENTIALS:
        raise _conflict("too_many_credentials", "Remove an old credential first.")
    credential = ProfessionalCredential(
        professional_id=professional.id,
        status=CredentialStatus.UNVERIFIED,
        created_by=actor_id,
        **data,
    )
    db.add(credential)
    await db.flush()
    await _audit(
        db,
        "professional.credential_added",
        professional,
        actor_id=actor_id,
        meta=meta,
        details={"credential_id": str(credential.id), "kind": credential.kind},
    )
    return credential


async def remove_credential(
    db: AsyncSession,
    professional: Professional,
    credential_id: uuid.UUID,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> None:
    credential = await db.get(ProfessionalCredential, credential_id)
    if credential is None or credential.professional_id != professional.id:
        raise not_found("Credential")
    await db.delete(credential)
    await db.flush()
    await _audit(
        db,
        "professional.credential_removed",
        professional,
        actor_id=actor_id,
        meta=meta,
        details={"credential_id": str(credential_id), "status": credential.status},
    )


async def set_services(
    db: AsyncSession,
    professional: Professional,
    services: list[dict[str, Any]],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> list[ProfessionalService]:
    current = {s.vertical: s for s in (await view(db, professional)).services}
    wanted = {s["vertical"]: s for s in services}
    for vertical, row in current.items():
        if vertical not in wanted:
            await db.delete(row)
    for vertical, data in wanted.items():
        if vertical in current:
            current[vertical].description = data.get("description")
        else:
            db.add(
                ProfessionalService(
                    professional_id=professional.id,
                    vertical=vertical,
                    description=data.get("description"),
                )
            )
    await db.flush()
    if set(current) != set(wanted):
        await _audit(
            db,
            "professional.services_changed",
            professional,
            actor_id=actor_id,
            meta=meta,
            details={"verticals": sorted(wanted)},
        )
    return (await view(db, professional)).services


# --- Staff -----------------------------------------------------------------------------


async def list_professionals(db: AsyncSession, status_filter: str | None) -> list[Professional]:
    query = select(Professional).order_by(Professional.created_at.desc())
    if status_filter:
        query = query.where(Professional.status == status_filter)
    return list((await db.execute(query.limit(500))).scalars())


async def get_professional(
    db: AsyncSession, professional_id: uuid.UUID, *, lock: bool = False
) -> Professional:
    query = select(Professional).where(Professional.id == professional_id)
    if lock:
        query = query.with_for_update()
    professional = (await db.execute(query)).scalar_one_or_none()
    if professional is None:
        raise not_found("Professional")
    return professional


async def check_credential(
    db: AsyncSession,
    professional: Professional,
    credential_id: uuid.UUID,
    new_status: CredentialStatus,
    notes: str | None,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> ProfessionalCredential:
    credential = await db.get(ProfessionalCredential, credential_id, with_for_update=True)
    if credential is None or credential.professional_id != professional.id:
        raise not_found("Credential")
    if professional.user_id == actor_id:
        raise _conflict("own_credential", "Someone else has to check your own credentials.")
    previous = credential.status
    credential.status = new_status
    credential.notes = notes
    if new_status == CredentialStatus.UNVERIFIED:
        credential.verified_by = credential.verified_at = None
    else:
        credential.verified_by, credential.verified_at = actor_id, utcnow()
    await db.flush()
    await _audit(
        db,
        "professional.credential_checked",
        professional,
        actor_id=actor_id,
        meta=meta,
        details={"credential_id": str(credential.id), "from": previous, "to": new_status},
    )
    return credential


async def set_status(
    db: AsyncSession,
    professional: Professional,
    new_status: ProfessionalStatus,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
    on: date,
) -> Professional:
    if new_status == professional.status:
        return professional
    if professional.user_id == actor_id:
        raise _conflict("own_profile", "Someone else has to approve your own profile.")
    if new_status == ProfessionalStatus.ACTIVE:
        problems = eligibility(await view(db, professional), None, on)
        problems = [p for p in problems if p != "The profile is not active."]
        if not (await view(db, professional)).services:
            problems.append("They haven't said what they review.")
        member = await tenancy.membership(db, professional.user_id, professional.practice_id)
        if member is None or Perm.REVIEW_PERFORM not in member.permissions:
            problems.append("They are no longer a reviewer in their practice.")
        if problems:
            raise _conflict("not_ready", " ".join(problems))
    previous = professional.status
    professional.status = new_status
    professional.status_changed_by = actor_id
    professional.status_changed_at = utcnow()
    await db.flush()
    await _audit(
        db,
        "professional.status_changed",
        professional,
        actor_id=actor_id,
        meta=meta,
        details={"from": previous, "to": new_status},
    )
    return professional


async def eligible_for(db: AsyncSession, vertical: str, on: date) -> list[ProfessionalView]:
    active = list(
        (
            await db.execute(
                select(Professional)
                .join(ProfessionalService, ProfessionalService.professional_id == Professional.id)
                .where(
                    Professional.status == ProfessionalStatus.ACTIVE,
                    ProfessionalService.vertical == vertical,
                )
                .order_by(Professional.display_name)
            )
        ).scalars()
    )
    return [v for v in await views(db, active) if not eligibility(v, vertical, on)]
