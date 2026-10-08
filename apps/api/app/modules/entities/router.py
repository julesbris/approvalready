"""``/v1/organisations/{organisation_id}/{properties,vessels,business-profiles}``."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DbDep, MetaDep, OrgContext, require_org_permission
from app.modules.entities import service
from app.modules.entities.models import Address, BusinessProfile, Property, Vessel
from app.modules.entities.schemas import (
    AddressOut,
    BusinessCreate,
    BusinessOut,
    BusinessUpdate,
    PropertyCreate,
    PropertyOut,
    PropertyUpdate,
    VesselCreate,
    VesselOut,
    VesselUpdate,
)
from app.modules.tenancy.rbac import Perm

router = APIRouter(prefix="/v1/organisations/{organisation_id}", tags=["entities"])

Read = Annotated[OrgContext, Depends(require_org_permission(Perm.PROJECT_READ))]
Write = Annotated[OrgContext, Depends(require_org_permission(Perm.PROJECT_WRITE))]


def _address_out(address: Address | None) -> AddressOut | None:
    if address is None:
        return None
    return AddressOut(
        line1=address.line1,
        line2=address.line2,
        suburb=address.suburb,
        state=address.state,
        postcode=address.postcode,
        lga_code=address.lga_code,
    )


async def _properties_out(db: AsyncSession, props: list[Property]) -> list[PropertyOut]:
    addresses = await service.addresses(db, [p.address_id for p in props])
    relationships = await service.relationships(db, [p.id for p in props])
    out = []
    for p in props:
        address = _address_out(addresses.get(p.address_id))
        assert address is not None
        out.append(
            PropertyOut(
                id=p.id,
                address=address,
                relationships=relationships[p.id],
                lot_plan=p.lot_plan,
                title_reference=p.title_reference,
                land_area_m2=p.land_area_m2,
                created_at=p.created_at,
                updated_at=p.updated_at,
            )
        )
    return out


async def _businesses_out(db: AsyncSession, items: list[BusinessProfile]) -> list[BusinessOut]:
    addresses = await service.addresses(db, [b.address_id for b in items])
    return [
        BusinessOut(
            id=b.id,
            legal_name=b.legal_name,
            trading_name=b.trading_name,
            abn=b.abn,
            acn=b.acn,
            entity_type=b.entity_type,
            gst_registered=b.gst_registered,
            established_on=b.established_on,
            employee_band=b.employee_band,
            turnover_band=b.turnover_band,
            anzsic_code=b.anzsic_code,
            address=_address_out(addresses.get(b.address_id) if b.address_id else None),
            created_at=b.created_at,
            updated_at=b.updated_at,
        )
        for b in items
    ]


def _vessel_out(v: Vessel) -> VesselOut:
    return VesselOut.model_validate(v, from_attributes=True)


# --- Properties ------------------------------------------------------------------------


@router.get("/properties", response_model=list[PropertyOut])
async def list_properties(ctx: Read, db: DbDep) -> list[PropertyOut]:
    return await _properties_out(db, await service.list_entities(db, Property, ctx.organisation.id))


@router.post("/properties", status_code=status.HTTP_201_CREATED, response_model=PropertyOut)
async def create_property(
    body: PropertyCreate, ctx: Write, db: DbDep, meta: MetaDep
) -> PropertyOut:
    prop = await service.create_property(
        db, ctx.organisation.id, body.model_dump(), actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    return (await _properties_out(db, [prop]))[0]


@router.get("/properties/{property_id}", response_model=PropertyOut)
async def get_property(property_id: uuid.UUID, ctx: Read, db: DbDep) -> PropertyOut:
    prop = await service.get_entity(db, Property, ctx.organisation.id, property_id)
    return (await _properties_out(db, [prop]))[0]


@router.patch("/properties/{property_id}", response_model=PropertyOut)
async def update_property(
    property_id: uuid.UUID, body: PropertyUpdate, ctx: Write, db: DbDep, meta: MetaDep
) -> PropertyOut:
    prop = await service.get_entity(db, Property, ctx.organisation.id, property_id)
    await service.update_entity(
        db, prop, body.model_dump(exclude_unset=True), actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    return (await _properties_out(db, [prop]))[0]


@router.delete("/properties/{property_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_property(property_id: uuid.UUID, ctx: Write, db: DbDep, meta: MetaDep) -> None:
    prop = await service.get_entity(db, Property, ctx.organisation.id, property_id)
    await service.delete_entity(db, prop, actor_id=ctx.auth.user.id, meta=meta)
    await db.commit()


# --- Vessels ---------------------------------------------------------------------------


@router.get("/vessels", response_model=list[VesselOut])
async def list_vessels(ctx: Read, db: DbDep) -> list[VesselOut]:
    return [_vessel_out(v) for v in await service.list_entities(db, Vessel, ctx.organisation.id)]


@router.post("/vessels", status_code=status.HTTP_201_CREATED, response_model=VesselOut)
async def create_vessel(body: VesselCreate, ctx: Write, db: DbDep, meta: MetaDep) -> VesselOut:
    vessel = await service.create_entity(
        db, Vessel, ctx.organisation.id, body.model_dump(), actor_id=ctx.auth.user.id, meta=meta
    )
    await db.commit()
    assert isinstance(vessel, Vessel)
    return _vessel_out(vessel)


@router.get("/vessels/{vessel_id}", response_model=VesselOut)
async def get_vessel(vessel_id: uuid.UUID, ctx: Read, db: DbDep) -> VesselOut:
    return _vessel_out(await service.get_entity(db, Vessel, ctx.organisation.id, vessel_id))


@router.patch("/vessels/{vessel_id}", response_model=VesselOut)
async def update_vessel(
    vessel_id: uuid.UUID, body: VesselUpdate, ctx: Write, db: DbDep, meta: MetaDep
) -> VesselOut:
    vessel = await service.get_entity(db, Vessel, ctx.organisation.id, vessel_id)
    changes = {
        k: v
        for k, v in body.model_dump(exclude_unset=True).items()
        if not (k in {"name", "vessel_type"} and v is None)
    }
    await service.update_entity(db, vessel, changes, actor_id=ctx.auth.user.id, meta=meta)
    await db.commit()
    return _vessel_out(vessel)


@router.delete("/vessels/{vessel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vessel(vessel_id: uuid.UUID, ctx: Write, db: DbDep, meta: MetaDep) -> None:
    vessel = await service.get_entity(db, Vessel, ctx.organisation.id, vessel_id)
    await service.delete_entity(db, vessel, actor_id=ctx.auth.user.id, meta=meta)
    await db.commit()


# --- Business profiles -----------------------------------------------------------------


@router.get("/business-profiles", response_model=list[BusinessOut])
async def list_business_profiles(ctx: Read, db: DbDep) -> list[BusinessOut]:
    return await _businesses_out(
        db, await service.list_entities(db, BusinessProfile, ctx.organisation.id)
    )


@router.post("/business-profiles", status_code=status.HTTP_201_CREATED, response_model=BusinessOut)
async def create_business_profile(
    body: BusinessCreate, ctx: Write, db: DbDep, meta: MetaDep
) -> BusinessOut:
    profile = await service.create_entity(
        db,
        BusinessProfile,
        ctx.organisation.id,
        body.model_dump(),
        actor_id=ctx.auth.user.id,
        meta=meta,
    )
    await db.commit()
    assert isinstance(profile, BusinessProfile)
    return (await _businesses_out(db, [profile]))[0]


@router.get("/business-profiles/{profile_id}", response_model=BusinessOut)
async def get_business_profile(profile_id: uuid.UUID, ctx: Read, db: DbDep) -> BusinessOut:
    profile = await service.get_entity(db, BusinessProfile, ctx.organisation.id, profile_id)
    return (await _businesses_out(db, [profile]))[0]


@router.patch("/business-profiles/{profile_id}", response_model=BusinessOut)
async def update_business_profile(
    profile_id: uuid.UUID, body: BusinessUpdate, ctx: Write, db: DbDep, meta: MetaDep
) -> BusinessOut:
    profile = await service.get_entity(db, BusinessProfile, ctx.organisation.id, profile_id)
    changes = {
        k: v
        for k, v in body.model_dump(exclude_unset=True).items()
        if not (k in {"legal_name", "entity_type"} and v is None)
    }
    await service.update_entity(db, profile, changes, actor_id=ctx.auth.user.id, meta=meta)
    await db.commit()
    return (await _businesses_out(db, [profile]))[0]


@router.delete("/business-profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_business_profile(
    profile_id: uuid.UUID, ctx: Write, db: DbDep, meta: MetaDep
) -> None:
    profile = await service.get_entity(db, BusinessProfile, ctx.organisation.id, profile_id)
    await service.delete_entity(db, profile, actor_id=ctx.auth.user.id, meta=meta)
    await db.commit()
