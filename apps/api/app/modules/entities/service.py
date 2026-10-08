"""Properties, vessels and business profiles of an organisation.

Callers have checked permissions and bound the tenant (row-level security); queries still
filter by ``organisation_id`` explicitly, so RLS stays a safety net rather than the only
check. Audit events record which fields changed, never their (personal) values.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, not_found
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.entities.models import (
    Address,
    BusinessProfile,
    Property,
    PropertyOwnership,
    Vessel,
)
from app.modules.entities.schemas import AddressIn
from app.modules.projects.models import Project

_TARGETS: dict[type[Any], tuple[str, str]] = {
    # model: (audit target type, project link column)
    Property: ("property", "property_id"),
    Vessel: ("vessel", "vessel_id"),
    BusinessProfile: ("business_profile", "business_profile_id"),
}


async def _audit(
    db: AsyncSession,
    action: str,
    entity: Any,
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
    fields: list[str] | None = None,
) -> None:
    target_type = _TARGETS[type(entity)][0]
    await audit.record(
        db,
        f"{target_type}.{action}",
        actor_user_id=actor_id,
        organisation_id=entity.organisation_id,
        target_type=target_type,
        target_id=entity.id,
        meta=meta,
        details={"fields": sorted(fields)} if fields is not None else None,
    )


async def list_entities[E: (Property, Vessel, BusinessProfile)](
    db: AsyncSession, model: type[E], organisation_id: uuid.UUID
) -> list[E]:
    return list(
        (
            await db.execute(
                select(model)
                .where(model.organisation_id == organisation_id, model.deleted_at.is_(None))
                .order_by(model.created_at.desc())
            )
        ).scalars()
    )


async def get_entity[E: (Property, Vessel, BusinessProfile)](
    db: AsyncSession, model: type[E], organisation_id: uuid.UUID, entity_id: uuid.UUID
) -> E:
    entity = (
        await db.execute(
            select(model).where(
                model.id == entity_id,
                model.organisation_id == organisation_id,
                model.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if entity is None:
        raise not_found(_TARGETS[model][0].replace("_", " ").capitalize())
    return entity


async def addresses(db: AsyncSession, ids: list[uuid.UUID | None]) -> dict[uuid.UUID, Address]:
    wanted = [i for i in ids if i is not None]
    if not wanted:
        return {}
    rows = (await db.execute(select(Address).where(Address.id.in_(wanted)))).scalars()
    return {a.id: a for a in rows}


async def relationships(
    db: AsyncSession, property_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    result: dict[uuid.UUID, list[str]] = {pid: [] for pid in property_ids}
    if not property_ids:
        return result
    rows = (
        await db.execute(
            select(PropertyOwnership)
            .where(PropertyOwnership.property_id.in_(property_ids))
            .order_by(PropertyOwnership.role)
        )
    ).scalars()
    for row in rows:
        result[row.property_id].append(row.role)
    return result


async def _new_address(
    db: AsyncSession, organisation_id: uuid.UUID, data: AddressIn, actor_id: uuid.UUID
) -> Address:
    address = Address(organisation_id=organisation_id, created_by=actor_id, **data.model_dump())
    db.add(address)
    await db.flush()
    return address


async def _apply_address(
    db: AsyncSession, entity: Property | BusinessProfile, data: AddressIn, actor_id: uuid.UUID
) -> bool:
    if entity.address_id is None:
        entity.address_id = (await _new_address(db, entity.organisation_id, data, actor_id)).id
        return True
    address = await db.get(Address, entity.address_id)
    assert address is not None
    changed = False
    for key, value in data.model_dump().items():
        if getattr(address, key) != value:
            setattr(address, key, value)
            changed = True
    return changed


async def create_property(
    db: AsyncSession,
    organisation_id: uuid.UUID,
    data: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> Property:
    address = await _new_address(db, organisation_id, AddressIn(**data.pop("address")), actor_id)
    role = data.pop("relationship")
    prop = Property(
        organisation_id=organisation_id, address_id=address.id, created_by=actor_id, **data
    )
    db.add(prop)
    await db.flush()
    db.add(
        PropertyOwnership(
            organisation_id=organisation_id, property_id=prop.id, role=role, created_by=actor_id
        )
    )
    await db.flush()
    await _audit(db, "created", prop, actor_id=actor_id, meta=meta)
    return prop


async def create_entity(
    db: AsyncSession,
    model: type[Vessel] | type[BusinessProfile],
    organisation_id: uuid.UUID,
    data: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> Vessel | BusinessProfile:
    address_data = data.pop("address", None)
    entity = model(organisation_id=organisation_id, created_by=actor_id, **data)
    if address_data is not None:
        address = await _new_address(db, organisation_id, AddressIn(**address_data), actor_id)
        entity.address_id = address.id  # type: ignore[union-attr]
    db.add(entity)
    await db.flush()
    await _audit(db, "created", entity, actor_id=actor_id, meta=meta)
    return entity


async def update_entity[E: (Property, Vessel, BusinessProfile)](
    db: AsyncSession,
    entity: E,
    changes: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    meta: RequestMeta | None,
) -> E:
    changed: list[str] = []
    address_data = changes.pop("address", None)
    if (
        address_data is not None
        and isinstance(entity, Property | BusinessProfile)
        and await _apply_address(db, entity, AddressIn(**address_data), actor_id)
    ):
        changed.append("address")
    for key, value in changes.items():
        if getattr(entity, key) != value:
            setattr(entity, key, value)
            changed.append(key)
    if changed:
        await db.flush()
        await _audit(db, "updated", entity, actor_id=actor_id, meta=meta, fields=changed)
    return entity


async def delete_entity[E: (Property, Vessel, BusinessProfile)](
    db: AsyncSession, entity: E, *, actor_id: uuid.UUID, meta: RequestMeta | None
) -> None:
    link = getattr(Project, _TARGETS[type(entity)][1])
    in_use = (
        await db.execute(
            select(Project.id)
            .where(
                link == entity.id,
                Project.organisation_id == entity.organisation_id,
                Project.deleted_at.is_(None),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if in_use is not None:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "in_use",
            "This is linked to a project. Remove it from the project first.",
        )
    entity.deleted_at = datetime.now(UTC)
    await db.flush()
    await _audit(db, "deleted", entity, actor_id=actor_id, meta=meta)
