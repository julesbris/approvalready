"""The marketplace's shared taxonomy of kinds of professional and service provider.

A category is platform reference data (no tenant), synced from the reviewed file
``categories.json`` on every migrate. Rules name categories in their outcome payloads
(``referral_categories``), which is how a business type, a finding or an approval maps to
"who can help". Partners join categories in Milestone 14; leads are matched by category in
Milestone 15.
"""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

VERTICALS = "ARRAY['PLANNING','VESSEL','BUSINESS','GRANT','SELL','RENT','TRADE']::text[]"


class MarketplaceCategory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "marketplace_category"
    __table_args__ = (
        UniqueConstraint("key"),
        CheckConstraint("key ~ '^[a-z][a-z0-9_]{1,59}$'", name="key_format"),
        CheckConstraint(
            f"verticals <@ {VERTICALS} AND cardinality(verticals) > 0", name="verticals_valid"
        ),
    )

    key: Mapped[str] = mapped_column(String(60), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    verticals: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    # Partners in this category must hold a current, checked credential (Milestone 14).
    requires_credential: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Regulated advice (legal, financial): never sold as leads without staff approval.
    restricted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Removed from the file: kept for history, no longer offered to new rules.
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
