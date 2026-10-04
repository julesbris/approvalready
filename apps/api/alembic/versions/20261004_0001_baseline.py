"""Baseline: database extensions only. Domain tables arrive from Milestone 2.

Revision ID: 0001
Revises:
Create Date: 2026-10-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgcrypto: digest()/gen_random_bytes() for audit hash chains and token hashing in SQL.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    # citext: case-insensitive unique email addresses.
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS citext")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
