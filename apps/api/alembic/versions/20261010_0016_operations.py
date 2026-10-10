"""Operations (Milestone 17): backup and restore-check records, and ops alerts.

* ``backup_run``: one row per nightly backup and per restore check, written by the
  ``backup`` service as the owner. The application role reads it and records the off-site
  copy (``offsite_*`` columns only).
* Notification kind ``OPS_ALERT`` (platform admins: backups, background jobs, disk space).

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "approvalready_rw"

KINDS_OLD = ("REMINDER", "GRANT_ROUND", "SOURCES_DUE", "LEAD_OFFERED", "LEAD_CLAIMED")
KINDS_NEW = (*KINDS_OLD, "OPS_ALERT")


def _notification_kinds(kinds: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_notification_kind_valid"), "notification")
    quoted = ", ".join(f"'{k}'" for k in kinds)
    op.create_check_constraint(
        op.f("ck_notification_kind_valid"), "notification", f"kind IN ({quoted})"
    )


def upgrade() -> None:
    op.create_table(
        "backup_run",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("database_file", sa.Text(), nullable=True),
        sa.Column("database_bytes", sa.BigInteger(), nullable=True),
        sa.Column("database_sha256", sa.Text(), nullable=True),
        sa.Column("uploads_file", sa.Text(), nullable=True),
        sa.Column("uploads_bytes", sa.BigInteger(), nullable=True),
        sa.Column("uploads_sha256", sa.Text(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("offsite_status", sa.Text(), nullable=True),
        sa.Column("offsite_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("offsite_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("offsite_error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('BACKUP', 'RESTORE_CHECK')", name=op.f("ck_backup_run_kind_valid")
        ),
        sa.CheckConstraint("status IN ('OK', 'FAILED')", name=op.f("ck_backup_run_status_valid")),
        sa.CheckConstraint(
            "offsite_status IS NULL OR offsite_status IN "
            "('PENDING', 'UPLOADED', 'FAILED', 'MISSING')",
            name=op.f("ck_backup_run_offsite_status_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backup_run")),
    )
    op.create_index("ix_backup_run_kind_started", "backup_run", ["kind", "started_at"])
    _notification_kinds(KINDS_NEW)
    op.execute(f"GRANT SELECT ON backup_run TO {APP_ROLE}")
    op.execute(
        "GRANT UPDATE (offsite_status, offsite_at, offsite_attempts, offsite_error) "
        f"ON backup_run TO {APP_ROLE}"
    )


def downgrade() -> None:
    op.execute("DELETE FROM notification WHERE kind = 'OPS_ALERT'")
    _notification_kinds(KINDS_OLD)
    op.drop_index("ix_backup_run_kind_started", table_name="backup_run")
    op.drop_table("backup_run")
