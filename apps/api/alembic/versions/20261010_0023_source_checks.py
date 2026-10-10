"""Automatic source checks (Milestone 24): the app reads source documents from their
official addresses and keeps a snapshot when the text changes.

* ``source_document.auto_check``: include the document in the weekly check (default on).
* ``source_snapshot.capture_method``: ``MANUAL`` (pasted by staff) or ``FETCHED`` (read by
  the app). Existing snapshots were all pasted.
* ``source_check``: one row per attempt to read a document (append-only for the app role).

Revision ID: 0023
Revises: 0016
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
# Built alongside Milestones 18-23; point this at the newest of 0017-0022 on rebase.
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "approvalready_rw"


def upgrade() -> None:
    op.add_column(
        "source_document",
        sa.Column("auto_check", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column(
        "source_snapshot",
        sa.Column("capture_method", sa.Text(), server_default="MANUAL", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_source_snapshot_capture_method_valid"),
        "source_snapshot",
        "capture_method IN ('MANUAL', 'FETCHED')",
    )
    op.create_table(
        "source_check",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source_document_id", sa.UUID(), nullable=False),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("requested_by", sa.UUID(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("final_url", sa.String(length=2000), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("content_type", sa.String(length=200), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("body_sha256", sa.LargeBinary(), nullable=True),
        sa.Column("snapshot_id", sa.UUID(), nullable=True),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "trigger IN ('SCHEDULED', 'MANUAL')", name=op.f("ck_source_check_trigger_valid")
        ),
        sa.CheckConstraint(
            "outcome IN ('SAVED', 'CHANGED', 'UNCHANGED', 'FILE_SEEN', 'FILE_CHANGED', "
            "'FILE_UNCHANGED', 'FAILED')",
            name=op.f("ck_source_check_outcome_valid"),
        ),
        sa.CheckConstraint(
            "body_sha256 IS NULL OR octet_length(body_sha256) = 32",
            name=op.f("ck_source_check_body_sha256_size"),
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["app_user.id"],
            name=op.f("fk_source_check_requested_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["source_snapshot.id"],
            name=op.f("fk_source_check_snapshot_id_source_snapshot"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_document.id"],
            name=op.f("fk_source_check_source_document_id_source_document"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_check")),
    )
    op.create_index(
        "ix_source_check_document_checked", "source_check", ["source_document_id", "checked_at"]
    )
    op.execute(f"GRANT SELECT, INSERT ON source_check TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_index("ix_source_check_document_checked", table_name="source_check")
    op.drop_table("source_check")
    op.drop_constraint(op.f("ck_source_snapshot_capture_method_valid"), "source_snapshot")
    op.drop_column("source_snapshot", "capture_method")
    op.drop_column("source_document", "auto_check")
