"""Staff notes and contacting customers from Admin > Accounts.

* ``staff_note``: notes, logged calls and emails sent by staff, per account. Platform data
  (no row-level security); deleted when the person closes their account.

Revision ID: 0036
Revises: 0035
Create Date: 2026-11-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "approvalready_rw"


def upgrade() -> None:
    op.create_table(
        "staff_note",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("author_user_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("project_reference", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('NOTE', 'CALL', 'EMAIL')", name=op.f("ck_staff_note_kind_valid")
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"],
            ["app_user.id"],
            name=op.f("fk_staff_note_author_user_id_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_staff_note_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_note")),
    )
    op.create_index("ix_staff_note_user_created", "staff_note", ["user_id", "created_at"])
    op.execute(f"GRANT SELECT, INSERT, DELETE ON staff_note TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_index("ix_staff_note_user_created", table_name="staff_note")
    op.drop_table("staff_note")
