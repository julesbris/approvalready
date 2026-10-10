"""Email outbox (Milestone 20): emails are queued and sent by the worker with retries.

* ``email_outbox``: one row per email; the message is sealed (AES-GCM keyed from
  SECRET_KEY) and erased once the email is sent or given up on.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "approvalready_rw"


def upgrade() -> None:
    op.create_table(
        "email_outbox",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="PENDING", nullable=False),
        sa.Column("sealed", sa.LargeBinary(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING', 'SENT', 'FAILED')", name=op.f("ck_email_outbox_status_valid")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_outbox")),
    )
    op.create_index(
        "ix_email_outbox_due",
        "email_outbox",
        ["next_attempt_at"],
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.create_index("ix_email_outbox_created", "email_outbox", ["created_at"])
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON email_outbox TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_index("ix_email_outbox_created", table_name="email_outbox")
    op.drop_index("ix_email_outbox_due", table_name="email_outbox")
    op.drop_table("email_outbox")
