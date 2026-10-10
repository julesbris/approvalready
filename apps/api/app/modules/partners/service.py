"""Partner accounts: the application, the partner's own profile, and staff verification.

Anyone signed in can apply. Applying creates the partner organisation (the applicant
becomes its ``PARTNER_ADMIN``), the partner record (``APPLIED``), the categories (each
``PENDING``), service areas and credentials, and a snapshot of the submission. Staff with
``partner.verify`` then check the credentials against the issuers' registers, approve
categories one by one and approve (``ACTIVE``) or reject the partner. Nobody checks their
own partner account.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, not_found
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.identity.models import AppUser
from app.modules.marketplace.models import MarketplaceCategory
from app.modules.partners.models import (
    PartnerApplication,
    PartnerApplicationStatus,
    PartnerCategory,
    PartnerCategoryStatus,
    PartnerCredential,
    PartnerCredentialStatus,
    PartnerOrganisation,
    PartnerServiceArea,
    PartnerStatus,
)
from app.modules.partners.schemas import (
    MAX_CATEGORIES,
    MAX_CREDENTIALS,
    MAX_SERVICE_AREAS,
    PartnerApplicationIn,
    PartnerCredentialIn,
    PartnerServiceAreaIn,
)
from app.modules.tenancy import service as tenancy
from app.modules.tenancy.models import (
    MemberStatus,
    Organisation,
    OrganisationKind,
    OrganisationMember,
)
from app.modules.tenancy.rbac import Perm
from app.modules.tenancy.schemas import is_valid_abn

# Staff decisions allowed from each status. Resubmitting after a rejection is the partner's.
TRANSITIONS: dict[PartnerStatus, tuple[PartnerStatus, ...]] = {
    PartnerStatus.APPLIED: (
        PartnerStatus.UNDER_REVIEW,
        PartnerStatus.ACTIVE,
        PartnerStatus.REJECTED,
    ),
    PartnerStatus.UNDER_REVIEW: (PartnerStatus.ACTIVE, PartnerStatus.REJECTED),
    PartnerStatus.ACTIVE: (PartnerStatus.SUSPENDED,),
    PartnerStatus.SUSPENDED: (PartnerStatus.ACTIVE,),
    PartnerStatus.REJECTED: (),
}
OPEN_APPLICATION = (PartnerStatus.APPLIED, PartnerStatus.UNDER_REVIEW)
# Name and ABN are what staff checked: they can be changed only before the check starts.
DETAILS_EDITABLE = (PartnerStatus.APPLIED, PartnerStatus.REJECTED)


def utcnow() -> datetime:
    return datetime.now(UTC)


def _conflict(code: str, message: str) -> ApiError:
    return ApiError(status.HTTP_409_CONFLICT, code, message)


@dataclass(frozen=True)
class PartnerView:
    partner: PartnerOrganisation
    organisation: Organisation
    categories: list[tuple[PartnerCategory, MarketplaceCategory]]
    areas: list[PartnerServiceArea]
    credentials: list[PartnerCredential]
    applications: list[PartnerApplication]


async def view(db: AsyncSession, partner: PartnerOrganisation) -> PartnerView:
    organisation = await db.get(Organisation, partner.organisation_id)
    assert organisation is not None
    categories = [
        (pc, mc)
        for pc, mc in await db.execute(
            select(PartnerCategory, MarketplaceCategory)
            .join(MarketplaceCategory, MarketplaceCategory.id == PartnerCategory.category_id)
            .where(PartnerCategory.partner_organisation_id == partner.id)
            .order_by(MarketplaceCategory.sort_order, PartnerCategory.created_at)
        )
    ]
    areas = list(
        (
            await db.execute(
                select(PartnerServiceArea)
                .where(PartnerServiceArea.partner_organisation_id == partner.id)
                .order_by(PartnerServiceArea.created_at)
            )
        ).scalars()
    )
    credentials = list(
        (
            await db.execute(
                select(PartnerCredential)
                .where(PartnerCredential.partner_organisation_id == partner.id)
                .order_by(PartnerCredential.created_at)
            )
        ).scalars()
    )
    applications = list(
        (
            await db.execute(
                select(PartnerApplication)
                .where(PartnerApplication.partner_organisation_id == partner.id)
                .order_by(PartnerApplication.created_at.desc())
            )
        ).scalars()
    )
    return PartnerView(partner, organisation, categories, areas, credentials, applications)


async def _audit(
    db: AsyncSession,
    action: str,
    partner: PartnerOrganisation,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
    details: dict[str, Any] | None = None,
) -> None:
    await audit.record(
        db,
        action,
        actor_user_id=actor_id,
        organisation_id=partner.organisation_id,
        target_type="partner",
        target_id=partner.id,
        meta=meta,
        details=details,
    )


async def _categories_by_key(db: AsyncSession, keys: list[str]) -> dict[str, MarketplaceCategory]:
    found = {
        c.key: c
        for c in (
            await db.execute(
                select(MarketplaceCategory).where(
                    MarketplaceCategory.key.in_(keys), MarketplaceCategory.active.is_(True)
                )
            )
        ).scalars()
    }
    unknown = sorted(set(keys) - set(found))
    if unknown:
        raise ApiError(
            422, "unknown_category", f"We don't refer these kinds of work: {', '.join(unknown)}."
        )
    return found


def _area_key(kind: str, state: str, value: str) -> tuple[str, str, str]:
    return kind, state, value.casefold()


def _new_credential(
    partner: PartnerOrganisation, data: PartnerCredentialIn, actor_id: uuid.UUID
) -> PartnerCredential:
    return PartnerCredential(
        partner_organisation_id=partner.id,
        kind=data.kind,
        issuer=data.issuer,
        number=data.number,
        cover_cents=data.cover_cents,
        expires_on=data.expires_on,
        status=PartnerCredentialStatus.UNVERIFIED,
        created_by=actor_id,
    )


async def snapshot(db: AsyncSession, partner: PartnerOrganisation) -> dict[str, Any]:
    """What staff are asked to check, as it stands now (stored with each submission)."""
    v = await view(db, partner)
    return {
        "name": v.organisation.name,
        "abn": v.organisation.abn,
        "website": partner.website,
        "phone": partner.phone,
        "contact_email": partner.contact_email,
        "description": partner.description,
        "categories": [mc.key for _, mc in v.categories],
        "service_areas": [{"kind": a.kind, "state": a.state, "value": a.value} for a in v.areas],
        "credentials": [
            {
                "kind": c.kind,
                "issuer": c.issuer,
                "number": c.number,
                "cover_cents": c.cover_cents,
                "expires_on": c.expires_on.isoformat() if c.expires_on else None,
            }
            for c in v.credentials
        ],
    }


# --- Lookups -----------------------------------------------------------------------------


async def for_organisation(
    db: AsyncSession, organisation_id: uuid.UUID, *, lock: bool = False
) -> PartnerOrganisation:
    query = select(PartnerOrganisation).where(
        PartnerOrganisation.organisation_id == organisation_id
    )
    if lock:
        query = query.with_for_update()
    partner = (await db.execute(query)).scalar_one_or_none()
    if partner is None:
        raise not_found("Partner account")
    return partner


async def get_partner(
    db: AsyncSession, partner_id: uuid.UUID, *, lock: bool = False
) -> PartnerOrganisation:
    query = select(PartnerOrganisation).where(PartnerOrganisation.id == partner_id)
    if lock:
        query = query.with_for_update()
    partner = (await db.execute(query)).scalar_one_or_none()
    if partner is None:
        raise not_found("Partner")
    return partner


async def managers(db: AsyncSession, organisation_id: uuid.UUID) -> list[AppUser]:
    """The people who manage the partner account (they get the decision emails)."""
    out = []
    for m in await tenancy.list_members(db, organisation_id):
        perms = await tenancy.permissions_of_roles(db, m.role_keys)
        if Perm.PARTNER_MANAGE in perms:
            out.append(m.user)
    return out


# --- Applying ----------------------------------------------------------------------------


async def apply(
    db: AsyncSession, *, user: AppUser, data: PartnerApplicationIn, meta: RequestMeta | None
) -> PartnerOrganisation:
    open_application = (
        await db.execute(
            select(PartnerOrganisation.id)
            .join(
                OrganisationMember,
                OrganisationMember.organisation_id == PartnerOrganisation.organisation_id,
            )
            .where(
                OrganisationMember.user_id == user.id,
                OrganisationMember.status == MemberStatus.ACTIVE,
                PartnerOrganisation.verification_status.in_(OPEN_APPLICATION),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if open_application is not None:
        raise _conflict(
            "application_open",
            "You already have a partner application waiting for our check.",
        )
    categories = await _categories_by_key(db, data.categories)
    areas: dict[tuple[str, str, str], PartnerServiceAreaIn] = {}
    for a in data.service_areas:
        areas.setdefault(_area_key(a.kind, a.state, a.value or ""), a)

    assert data.abn is not None
    organisation = await tenancy.create_organisation(
        db,
        creator=user,
        kind=OrganisationKind.PARTNER,
        name=data.name,
        abn=data.abn,
        meta=meta,
    )
    partner = PartnerOrganisation(
        organisation_id=organisation.id,
        verification_status=PartnerStatus.APPLIED,
        website=data.website,
        phone=data.phone,
        contact_email=str(data.contact_email) if data.contact_email else None,
        description=data.description,
        submitted_at=utcnow(),
        created_by=user.id,
    )
    db.add(partner)
    await db.flush()
    covered: dict[str, uuid.UUID] = {}
    for c in data.credentials:
        credential = _new_credential(partner, c, user.id)
        db.add(credential)
        await db.flush()
        for key in c.category_keys:
            covered.setdefault(key, credential.id)
    for key in data.categories:
        db.add(
            PartnerCategory(
                partner_organisation_id=partner.id,
                category_id=categories[key].id,
                status=PartnerCategoryStatus.PENDING,
                credential_id=covered.get(key),
                created_by=user.id,
            )
        )
    for a in areas.values():
        db.add(
            PartnerServiceArea(
                partner_organisation_id=partner.id,
                kind=a.kind,
                state=a.state,
                value=a.value,
                created_by=user.id,
            )
        )
    await db.flush()
    db.add(
        PartnerApplication(
            partner_organisation_id=partner.id,
            submitted_payload=await snapshot(db, partner),
            submitted_by=user.id,
            status=PartnerApplicationStatus.SUBMITTED,
        )
    )
    await db.flush()
    await _audit(
        db,
        "partner.applied",
        partner,
        actor_id=user.id,
        meta=meta,
        details={"categories": sorted(data.categories), "service_areas": len(areas)},
    )
    return partner


async def resubmit(
    db: AsyncSession,
    partner: PartnerOrganisation,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> PartnerOrganisation:
    if partner.verification_status != PartnerStatus.REJECTED:
        raise _conflict("not_rejected", "Only an application that wasn't approved is resubmitted.")
    for pc in (
        await db.execute(
            select(PartnerCategory).where(
                PartnerCategory.partner_organisation_id == partner.id,
                PartnerCategory.status == PartnerCategoryStatus.REJECTED,
            )
        )
    ).scalars():
        pc.status = PartnerCategoryStatus.PENDING
        pc.reviewed_by = pc.reviewed_at = None
    partner.verification_status = PartnerStatus.APPLIED
    partner.status_reason = None
    partner.submitted_at = utcnow()
    await db.flush()
    db.add(
        PartnerApplication(
            partner_organisation_id=partner.id,
            submitted_payload=await snapshot(db, partner),
            submitted_by=actor_id,
            status=PartnerApplicationStatus.SUBMITTED,
        )
    )
    await db.flush()
    await _audit(db, "partner.resubmitted", partner, actor_id=actor_id, meta=meta)
    return partner


# --- The partner's own profile --------------------------------------------------------------


async def update_profile(
    db: AsyncSession,
    partner: PartnerOrganisation,
    changes: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> None:
    organisation = await db.get(Organisation, partner.organisation_id)
    assert organisation is not None
    org_changes: dict[str, object] = {k: changes.pop(k) for k in ("name", "abn") if k in changes}
    org_changes = {k: v for k, v in org_changes.items() if v is not None}
    org_changes = {k: v for k, v in org_changes.items() if getattr(organisation, k) != v}
    if org_changes and partner.verification_status not in DETAILS_EDITABLE:
        raise _conflict(
            "details_locked",
            "Your business name and ABN were checked. Contact us to change them.",
        )
    if "contact_email" in changes and changes["contact_email"] is not None:
        changes["contact_email"] = str(changes["contact_email"])
    if "description" in changes and changes["description"] is None:
        del changes["description"]  # a partner always has a description
    applied = {k: v for k, v in changes.items() if getattr(partner, k) != v}
    for key, value in applied.items():
        setattr(partner, key, value)
    await db.flush()
    if org_changes:
        await tenancy.update_organisation(
            db, organisation, actor_id=actor_id, changes=org_changes, meta=meta
        )
    if applied:
        await _audit(
            db,
            "partner.updated",
            partner,
            actor_id=actor_id,
            meta=meta,
            details={"fields": sorted(applied)},
        )


async def _own_credential(
    db: AsyncSession, partner: PartnerOrganisation, credential_id: uuid.UUID
) -> PartnerCredential:
    credential = await db.get(PartnerCredential, credential_id)
    if credential is None or credential.partner_organisation_id != partner.id:
        raise not_found("Credential")
    return credential


async def _own_category(
    db: AsyncSession, partner: PartnerOrganisation, partner_category_id: uuid.UUID
) -> tuple[PartnerCategory, MarketplaceCategory]:
    row = (
        await db.execute(
            select(PartnerCategory, MarketplaceCategory)
            .join(MarketplaceCategory, MarketplaceCategory.id == PartnerCategory.category_id)
            .where(
                PartnerCategory.id == partner_category_id,
                PartnerCategory.partner_organisation_id == partner.id,
            )
            .with_for_update(of=PartnerCategory)
        )
    ).one_or_none()
    if row is None:
        raise not_found("Category")
    return row[0], row[1]


def _recheck(pc: PartnerCategory, mc: MarketplaceCategory) -> None:
    """A category's credential changed: if the credential mattered, it is checked again."""
    if mc.requires_credential and pc.status != PartnerCategoryStatus.PENDING:
        pc.status = PartnerCategoryStatus.PENDING
        pc.reviewed_by = pc.reviewed_at = None
        pc.notes = None


async def add_category(
    db: AsyncSession,
    partner: PartnerOrganisation,
    key: str,
    credential_id: uuid.UUID | None,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> None:
    category = (await _categories_by_key(db, [key]))[key]
    existing = (await view(db, partner)).categories
    if any(mc.id == category.id for _, mc in existing):
        raise _conflict("category_exists", "You have already chosen this category.")
    if len(existing) >= MAX_CATEGORIES:
        raise _conflict("too_many_categories", f"A partner can choose up to {MAX_CATEGORIES}.")
    if credential_id is not None:
        await _own_credential(db, partner, credential_id)
    db.add(
        PartnerCategory(
            partner_organisation_id=partner.id,
            category_id=category.id,
            status=PartnerCategoryStatus.PENDING,
            credential_id=credential_id,
            created_by=actor_id,
        )
    )
    await db.flush()
    await _audit(
        db,
        "partner.category_added",
        partner,
        actor_id=actor_id,
        meta=meta,
        details={"category": key},
    )


async def set_category_credential(
    db: AsyncSession,
    partner: PartnerOrganisation,
    partner_category_id: uuid.UUID,
    credential_id: uuid.UUID | None,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> None:
    pc, mc = await _own_category(db, partner, partner_category_id)
    if credential_id is not None:
        await _own_credential(db, partner, credential_id)
    if pc.credential_id == credential_id:
        return
    pc.credential_id = credential_id
    _recheck(pc, mc)
    await db.flush()
    await _audit(
        db,
        "partner.category_credential_changed",
        partner,
        actor_id=actor_id,
        meta=meta,
        details={
            "category": mc.key,
            "credential_id": str(credential_id) if credential_id else None,
        },
    )


async def remove_category(
    db: AsyncSession,
    partner: PartnerOrganisation,
    partner_category_id: uuid.UUID,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> None:
    pc, mc = await _own_category(db, partner, partner_category_id)
    await db.delete(pc)
    await db.flush()
    await _audit(
        db,
        "partner.category_removed",
        partner,
        actor_id=actor_id,
        meta=meta,
        details={"category": mc.key, "status": pc.status},
    )


async def add_service_area(
    db: AsyncSession,
    partner: PartnerOrganisation,
    data: PartnerServiceAreaIn,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> None:
    existing = (await view(db, partner)).areas
    key = _area_key(data.kind, data.state, data.value or "")
    if any(_area_key(a.kind, a.state, a.value) == key for a in existing):
        raise _conflict("area_exists", "You have already added this service area.")
    if len(existing) >= MAX_SERVICE_AREAS:
        raise _conflict("too_many_areas", f"A partner can add up to {MAX_SERVICE_AREAS} areas.")
    db.add(
        PartnerServiceArea(
            partner_organisation_id=partner.id,
            kind=data.kind,
            state=data.state,
            value=data.value,
            created_by=actor_id,
        )
    )
    await db.flush()
    await _audit(
        db,
        "partner.service_area_added",
        partner,
        actor_id=actor_id,
        meta=meta,
        details={"kind": str(data.kind), "state": str(data.state), "value": data.value},
    )


async def remove_service_area(
    db: AsyncSession,
    partner: PartnerOrganisation,
    area_id: uuid.UUID,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> None:
    area = await db.get(PartnerServiceArea, area_id)
    if area is None or area.partner_organisation_id != partner.id:
        raise not_found("Service area")
    await db.delete(area)
    await db.flush()
    await _audit(
        db,
        "partner.service_area_removed",
        partner,
        actor_id=actor_id,
        meta=meta,
        details={"kind": area.kind, "state": area.state, "value": area.value},
    )


async def add_credential(
    db: AsyncSession,
    partner: PartnerOrganisation,
    data: PartnerCredentialIn,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> None:
    v = await view(db, partner)
    if len(v.credentials) >= MAX_CREDENTIALS:
        raise _conflict("too_many_credentials", "Remove an old credential first.")
    chosen = {mc.key: (pc, mc) for pc, mc in v.categories}
    unknown = sorted(set(data.category_keys) - set(chosen))
    if unknown:
        raise ApiError(
            422, "unknown_category", "A credential can only cover categories you have chosen."
        )
    credential = _new_credential(partner, data, actor_id)
    db.add(credential)
    await db.flush()
    for key in data.category_keys:
        pc, mc = chosen[key]
        pc.credential_id = credential.id
        _recheck(pc, mc)
    await db.flush()
    await _audit(
        db,
        "partner.credential_added",
        partner,
        actor_id=actor_id,
        meta=meta,
        details={
            "credential_id": str(credential.id),
            "kind": str(data.kind),
            "categories": sorted(data.category_keys),
        },
    )


async def remove_credential(
    db: AsyncSession,
    partner: PartnerOrganisation,
    credential_id: uuid.UUID,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> None:
    credential = await _own_credential(db, partner, credential_id)
    await db.delete(credential)  # categories that named it lose it (ON DELETE SET NULL)
    await db.flush()
    await _audit(
        db,
        "partner.credential_removed",
        partner,
        actor_id=actor_id,
        meta=meta,
        details={"credential_id": str(credential_id), "status": credential.status},
    )


# --- Staff -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Summary:
    partner: PartnerOrganisation
    organisation: Organisation
    categories: list[str]
    pending_categories: int
    unchecked_credentials: int


async def list_partners(db: AsyncSession, status_filter: str | None) -> list[Summary]:
    query = (
        select(PartnerOrganisation, Organisation)
        .join(Organisation, Organisation.id == PartnerOrganisation.organisation_id)
        .order_by(PartnerOrganisation.submitted_at.desc())
        .limit(500)
    )
    if status_filter:
        query = query.where(PartnerOrganisation.verification_status == status_filter)
    rows = list(await db.execute(query))
    ids = [p.id for p, _ in rows]
    labels: dict[uuid.UUID, list[str]] = {i: [] for i in ids}
    pending: dict[uuid.UUID, int] = dict.fromkeys(ids, 0)
    for pc, mc in await db.execute(
        select(PartnerCategory, MarketplaceCategory)
        .join(MarketplaceCategory, MarketplaceCategory.id == PartnerCategory.category_id)
        .where(PartnerCategory.partner_organisation_id.in_(ids))
        .order_by(MarketplaceCategory.sort_order)
    ):
        labels[pc.partner_organisation_id].append(mc.label)
        if pc.status == PartnerCategoryStatus.PENDING:
            pending[pc.partner_organisation_id] += 1
    unchecked: dict[uuid.UUID, int] = dict.fromkeys(ids, 0)
    for pid, count in await db.execute(
        select(PartnerCredential.partner_organisation_id, func.count())
        .where(
            PartnerCredential.partner_organisation_id.in_(ids),
            PartnerCredential.status == PartnerCredentialStatus.UNVERIFIED,
        )
        .group_by(PartnerCredential.partner_organisation_id)
    ):
        unchecked[pid] = int(count)
    return [Summary(p, o, labels[p.id], pending[p.id], unchecked[p.id]) for p, o in rows]


async def _not_own(db: AsyncSession, partner: PartnerOrganisation, actor_id: uuid.UUID) -> None:
    if await tenancy.membership(db, actor_id, partner.organisation_id) is not None:
        raise _conflict("own_partner", "Someone else has to check a partner account you belong to.")


async def set_status(
    db: AsyncSession,
    partner: PartnerOrganisation,
    new_status: PartnerStatus,
    reason: str | None,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> None:
    current = PartnerStatus(partner.verification_status)
    if new_status == current:
        return
    if new_status not in TRANSITIONS[current]:
        raise _conflict(
            "bad_transition",
            f"A partner that is {current.lower().replace('_', ' ')} can't be moved to "
            f"{new_status.lower().replace('_', ' ')}.",
        )
    await _not_own(db, partner, actor_id)
    if new_status in (PartnerStatus.REJECTED, PartnerStatus.SUSPENDED) and not reason:
        raise ApiError(422, "reason_required", "Say why: the partner will see it.")
    if new_status == PartnerStatus.ACTIVE:
        v = await view(db, partner)
        problems = []
        if not v.organisation.abn or not is_valid_abn(v.organisation.abn):
            problems.append("The ABN is missing or not valid.")
        if not any(pc.status == PartnerCategoryStatus.APPROVED for pc, _ in v.categories):
            problems.append("Approve at least one category first.")
        if not v.areas:
            problems.append("The partner has no service area.")
        if problems:
            raise _conflict("not_ready", " ".join(problems))
    partner.verification_status = new_status
    partner.status_reason = reason if new_status != PartnerStatus.ACTIVE else None
    partner.status_changed_by = actor_id
    partner.status_changed_at = utcnow()
    if current in OPEN_APPLICATION and new_status in (PartnerStatus.ACTIVE, PartnerStatus.REJECTED):
        application = (
            await db.execute(
                select(PartnerApplication)
                .where(
                    PartnerApplication.partner_organisation_id == partner.id,
                    PartnerApplication.status == PartnerApplicationStatus.SUBMITTED,
                )
                .order_by(PartnerApplication.created_at.desc())
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if application is not None:
            application.status = (
                PartnerApplicationStatus.APPROVED
                if new_status == PartnerStatus.ACTIVE
                else PartnerApplicationStatus.REJECTED
            )
            application.reviewed_by = actor_id
            application.reviewed_at = utcnow()
            application.decision_notes = reason
    await db.flush()
    await _audit(
        db,
        "partner.status_changed",
        partner,
        actor_id=actor_id,
        meta=meta,
        details={"from": str(current), "to": str(new_status)},
    )


async def check_category(
    db: AsyncSession,
    partner: PartnerOrganisation,
    partner_category_id: uuid.UUID,
    new_status: PartnerCategoryStatus,
    notes: str | None,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
    on: date,
) -> None:
    from app.modules.partners.entitlements import credential_current

    await _not_own(db, partner, actor_id)
    pc, mc = await _own_category(db, partner, partner_category_id)
    if new_status == PartnerCategoryStatus.REJECTED and not notes:
        raise ApiError(422, "notes_required", "Say why: the partner will see it.")
    if new_status == PartnerCategoryStatus.APPROVED:
        if not mc.active:
            raise _conflict("category_inactive", "We no longer refer this kind of work.")
        if mc.requires_credential:
            credential = (
                await db.get(PartnerCredential, pc.credential_id) if pc.credential_id else None
            )
            if credential is None or not credential_current(credential, on):
                raise _conflict(
                    "credential_needed",
                    f"{mc.label} needs a licence or accreditation that has been checked and "
                    "hasn't expired. Check the partner's credential first.",
                )
    previous = pc.status
    pc.status = new_status
    pc.notes = notes
    if new_status == PartnerCategoryStatus.PENDING:
        pc.reviewed_by = pc.reviewed_at = None
    else:
        pc.reviewed_by, pc.reviewed_at = actor_id, utcnow()
    await db.flush()
    await _audit(
        db,
        "partner.category_checked",
        partner,
        actor_id=actor_id,
        meta=meta,
        details={"category": mc.key, "from": previous, "to": str(new_status)},
    )


async def check_credential(
    db: AsyncSession,
    partner: PartnerOrganisation,
    credential_id: uuid.UUID,
    new_status: PartnerCredentialStatus,
    notes: str | None,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
    on: date,
) -> None:
    await _not_own(db, partner, actor_id)
    credential = await db.get(PartnerCredential, credential_id, with_for_update=True)
    if credential is None or credential.partner_organisation_id != partner.id:
        raise not_found("Credential")
    if new_status == PartnerCredentialStatus.REJECTED and not notes:
        raise ApiError(422, "notes_required", "Say why: the partner will see it.")
    if (
        new_status == PartnerCredentialStatus.VERIFIED
        and credential.expires_on is not None
        and credential.expires_on < on
    ):
        raise _conflict("credential_expired", "This credential has expired.")
    previous = credential.status
    credential.status = new_status
    credential.notes = notes
    if new_status == PartnerCredentialStatus.UNVERIFIED:
        credential.verified_by = credential.verified_at = None
    else:
        credential.verified_by, credential.verified_at = actor_id, utcnow()
    await db.flush()
    await _audit(
        db,
        "partner.credential_checked",
        partner,
        actor_id=actor_id,
        meta=meta,
        details={"credential_id": str(credential.id), "from": previous, "to": str(new_status)},
    )
