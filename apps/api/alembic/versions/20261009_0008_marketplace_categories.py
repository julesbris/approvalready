"""BusinessReady (Milestone 8): marketplace categories.

* ``marketplace_category``: platform reference data (no tenant), the shared taxonomy of
  kinds of professional that rule outcomes name in ``referral_categories``. Rows come from
  the reviewed file ``app/modules/marketplace/categories.json``, synced on every migrate
  (``python -m app.cli marketplace sync-categories``) by the owner; the application role
  can only read them.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "approvalready_rw"

# Privileges of the application role on the new table (tests/test_rls.py keeps the map).
PRIVILEGES: dict[str, str] = {"marketplace_category": "SELECT"}


def upgrade() -> None:
    op.create_table(
        "marketplace_category",
        sa.Column("key", sa.String(length=60), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("verticals", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("requires_credential", sa.Boolean(), nullable=False),
        sa.Column("restricted", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "key ~ '^[a-z][a-z0-9_]{1,59}$'", name=op.f("ck_marketplace_category_key_format")
        ),
        sa.CheckConstraint(
            "verticals <@ ARRAY['PLANNING','VESSEL','BUSINESS','GRANT','SELL','RENT']::text[] "
            "AND cardinality(verticals) > 0",
            name=op.f("ck_marketplace_category_verticals_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_marketplace_category")),
        sa.UniqueConstraint("key", name=op.f("uq_marketplace_category_key")),
    )
    for table, privileges in PRIVILEGES.items():
        op.execute(f"GRANT {privileges} ON {table} TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("marketplace_category")
