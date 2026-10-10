"""The reviewed catalogue file (products, features and the limits each product lifts).

``python -m app.cli billing sync-catalogue`` runs on every migrate, as the owner (the
application role can only read these tables). Like marketplace categories, a changed entry
is updated in place and one no longer in the file is deactivated, never deleted, so past
payments keep their product. Prices are not in the file: staff add them at /admin/billing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.billing.models import Feature, Product, ProductFeature, ProductKind
from app.modules.projects.models import Vertical

CATALOGUE_FILE = Path(__file__).parent / "catalogue.json"

Key = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")]


class FeatureDef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: Key
    description: str = Field(min_length=1, max_length=300)
    default_limit: int | None = Field(ge=0)


class ProductDef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: Key
    kind: ProductKind
    vertical: Vertical | None = None
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=500)
    # Feature key -> the limit this product gives (null: unlimited).
    features: dict[str, int | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _shape(self) -> ProductDef:
        if self.kind == ProductKind.REVIEW and (
            self.vertical is None or self.key != f"review.{self.vertical.lower()}"
        ):
            raise ValueError("a review product needs a vertical and the key review.<vertical>")
        if self.kind == ProductKind.PARTNER_PLAN and (
            self.vertical is not None or not self.key.startswith("partner.")
        ):
            raise ValueError("a partner plan has no vertical and the key partner.<plan>")
        if any(v is not None and v < 0 for v in self.features.values()):
            raise ValueError("feature limits can't be negative")
        return self


class CatalogueFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: str
    features: list[FeatureDef]
    products: list[ProductDef] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> CatalogueFile:
        features = [f.key for f in self.features]
        products = [p.key for p in self.products]
        if len(features) != len(set(features)) or len(products) != len(set(products)):
            raise ValueError("each feature and product key must appear once")
        for p in self.products:
            unknown = set(p.features) - set(features)
            if unknown:
                raise ValueError(f"{p.key} names unknown features: {', '.join(sorted(unknown))}")
        return self


def load_bundled(path: Path = CATALOGUE_FILE) -> CatalogueFile:
    return CatalogueFile.model_validate(json.loads(path.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class SyncReport:
    added: list[str]
    updated: list[str]
    deactivated: list[str]

    def lines(self) -> list[str]:
        out = [f"added: {k}" for k in self.added]
        out += [f"updated: {k}" for k in self.updated]
        out += [f"deactivated: {k}" for k in self.deactivated]
        return out or ["billing catalogue unchanged"]


async def sync(db: AsyncSession, catalogue: CatalogueFile) -> SyncReport:
    added: list[str] = []
    updated: list[str] = []
    deactivated: list[str] = []

    def apply(row: Feature | Product, values: dict[str, object], key: str) -> None:
        if any(getattr(row, k) != v for k, v in values.items()):
            for k, v in values.items():
                setattr(row, k, v)
            updated.append(key)

    features = {f.key: f for f in (await db.execute(select(Feature))).scalars()}
    for fd in catalogue.features:
        feature_values: dict[str, object] = {
            "description": fd.description,
            "default_limit": fd.default_limit,
            "active": True,
        }
        if fd.key in features:
            apply(features[fd.key], feature_values, fd.key)
        else:
            features[fd.key] = Feature(key=fd.key, **feature_values)
            db.add(features[fd.key])
            added.append(fd.key)
    keep = {fd.key for fd in catalogue.features}
    for key, feature in features.items():
        if key not in keep and feature.active:
            feature.active = False
            deactivated.append(key)

    products = {p.key: p for p in (await db.execute(select(Product))).scalars()}
    for order, pd in enumerate(catalogue.products, start=1):
        product_values: dict[str, object] = {
            "kind": str(pd.kind),
            "vertical": str(pd.vertical) if pd.vertical else None,
            "name": pd.name,
            "description": pd.description,
            "active": True,
            "sort_order": order,
        }
        if pd.key in products:
            apply(products[pd.key], product_values, pd.key)
        else:
            products[pd.key] = Product(key=pd.key, **product_values)
            db.add(products[pd.key])
            added.append(pd.key)
    keep = {pd.key for pd in catalogue.products}
    for key, product in products.items():
        if key not in keep and product.active:
            product.active = False
            deactivated.append(key)
    await db.flush()

    # Limits: replace each product's rows with the file's (owner only; nothing points at them).
    names = {f.id: f.key for f in features.values()}
    for pd in catalogue.products:
        product = products[pd.key]
        current = {
            names[pf.feature_id]: pf.limit_value
            for pf in (
                await db.execute(
                    select(ProductFeature).where(ProductFeature.product_id == product.id)
                )
            ).scalars()
        }
        if current == pd.features:
            continue
        await db.execute(delete(ProductFeature).where(ProductFeature.product_id == product.id))
        for key, limit in pd.features.items():
            db.add(
                ProductFeature(
                    product_id=product.id, feature_id=features[key].id, limit_value=limit
                )
            )
        if pd.key not in added and pd.key not in updated:
            updated.append(pd.key)
    await db.flush()
    return SyncReport(added, updated, deactivated)
