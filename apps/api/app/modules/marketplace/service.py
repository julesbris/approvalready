"""Marketplace categories: the reviewed file, syncing it, and reading it.

``python -m app.cli marketplace sync-categories`` runs on every migrate (as the owner: the
application role can only read the table). A new entry is inserted, a changed one updated in
place (a label or description is not versioned data: rules store only the key), and an
entry no longer in the file is deactivated, never deleted, so old findings keep a label.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.marketplace.models import MarketplaceCategory
from app.modules.projects.models import Vertical

CATEGORIES_FILE = Path(__file__).parent / "categories.json"

Key = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,59}$")]


class CategoryDef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: Key
    label: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=500)
    verticals: list[Vertical] = Field(min_length=1)
    requires_credential: bool
    restricted: bool


class CategoriesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: str
    categories: list[CategoryDef] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> CategoriesFile:
        keys = [c.key for c in self.categories]
        if len(keys) != len(set(keys)):
            raise ValueError("each category key must appear once")
        return self


def load_bundled(path: Path = CATEGORIES_FILE) -> list[CategoryDef]:
    return CategoriesFile.model_validate(json.loads(path.read_text(encoding="utf-8"))).categories


@dataclass(frozen=True)
class SyncReport:
    added: list[str]
    updated: list[str]
    deactivated: list[str]

    def lines(self) -> list[str]:
        out = [f"added: {k}" for k in self.added]
        out += [f"updated: {k}" for k in self.updated]
        out += [f"deactivated: {k}" for k in self.deactivated]
        return out or ["marketplace categories unchanged"]


async def sync(db: AsyncSession, definitions: list[CategoryDef]) -> SyncReport:
    existing = {c.key: c for c in (await db.execute(select(MarketplaceCategory))).scalars()}
    added: list[str] = []
    updated: list[str] = []
    for order, d in enumerate(definitions, start=1):
        values = {
            "label": d.label,
            "description": d.description,
            "verticals": [str(v) for v in d.verticals],
            "requires_credential": d.requires_credential,
            "restricted": d.restricted,
            "active": True,
            "sort_order": order,
        }
        row = existing.get(d.key)
        if row is None:
            db.add(MarketplaceCategory(key=d.key, **values))
            added.append(d.key)
            continue
        if any(getattr(row, k) != v for k, v in values.items()):
            for k, v in values.items():
                setattr(row, k, v)
            updated.append(d.key)
    keep = {d.key for d in definitions}
    deactivated = []
    for key, row in existing.items():
        if key not in keep and row.active:
            row.active = False
            deactivated.append(key)
    await db.flush()
    return SyncReport(added, updated, deactivated)


async def list_categories(
    db: AsyncSession, *, vertical: str | None = None, include_inactive: bool = False
) -> list[MarketplaceCategory]:
    query = select(MarketplaceCategory).order_by(MarketplaceCategory.sort_order)
    if not include_inactive:
        query = query.where(MarketplaceCategory.active.is_(True))
    if vertical is not None:
        query = query.where(MarketplaceCategory.verticals.contains([vertical]))
    return list((await db.execute(query)).scalars())


async def by_keys(db: AsyncSession, keys: Iterable[str]) -> dict[str, MarketplaceCategory]:
    wanted = set(keys)
    if not wanted:
        return {}
    rows = await db.execute(select(MarketplaceCategory).where(MarketplaceCategory.key.in_(wanted)))
    return {c.key: c for c in rows.scalars()}


async def unknown_keys(db: AsyncSession, keys: Iterable[str]) -> list[str]:
    """Keys that are not active categories, in the order given (for error messages)."""
    keys = list(keys)
    found = await by_keys(db, keys)
    return [k for k in keys if k not in found or not found[k].active]


def fallback_label(key: str) -> str:
    words = key.replace("_", " ")
    return words[:1].upper() + words[1:]


async def labels(db: AsyncSession, keys: Iterable[str]) -> dict[str, str]:
    keys = list(keys)
    found = await by_keys(db, keys)
    return {k: found[k].label if k in found else fallback_label(k) for k in keys}
