"""``/v1/marketplace``: the shared category taxonomy (read-only; edited in the repository)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import AuthDep, DbDep
from app.modules.marketplace import service
from app.modules.marketplace.schemas import MarketplaceCategoryOut
from app.modules.projects.models import Vertical

router = APIRouter(prefix="/v1/marketplace", tags=["marketplace"])


@router.get("/categories", response_model=list[MarketplaceCategoryOut])
async def list_categories(
    _: AuthDep, db: DbDep, vertical: Vertical | None = None
) -> list[MarketplaceCategoryOut]:
    """Active categories, in the reviewed file's order (optionally for one vertical)."""
    return [
        MarketplaceCategoryOut.model_validate(c, from_attributes=True)
        for c in await service.list_categories(db, vertical=vertical)
    ]
