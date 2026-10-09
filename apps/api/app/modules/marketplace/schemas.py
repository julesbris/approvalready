from __future__ import annotations

from pydantic import BaseModel, Field

from app.modules.projects.models import Vertical


class MarketplaceCategoryOut(BaseModel):
    key: str
    label: str
    description: str
    verticals: list[Vertical]
    requires_credential: bool = Field(description="Providers need a checked credential.")
    restricted: bool = Field(description="Regulated advice; never released as a lead unchecked.")
