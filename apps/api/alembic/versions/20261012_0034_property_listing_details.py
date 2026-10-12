"""Property details brought in from a listing link, for the free property report.

* ``property`` gains ``bedrooms``, ``bathrooms``, ``car_spaces``, ``property_type`` and
  ``listing_url`` (all optional): typed by the customer or filled from a pasted listing link.
  Existing rows keep NULLs; nothing is back-filled.

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column in ("bedrooms", "bathrooms", "car_spaces"):
        op.add_column("property", sa.Column(column, sa.Integer()))
    op.add_column("property", sa.Column("property_type", sa.String(40)))
    op.add_column("property", sa.Column("listing_url", sa.String(500)))
    op.create_check_constraint(
        op.f("ck_property_rooms_range"),
        "property",
        "(bedrooms IS NULL OR bedrooms BETWEEN 0 AND 100) AND "
        "(bathrooms IS NULL OR bathrooms BETWEEN 0 AND 100) AND "
        "(car_spaces IS NULL OR car_spaces BETWEEN 0 AND 100)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_property_rooms_range"), "property", type_="check")
    for column in ("listing_url", "property_type", "car_spaces", "bathrooms", "bedrooms"):
        op.drop_column("property", column)
