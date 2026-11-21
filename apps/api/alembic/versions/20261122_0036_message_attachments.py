"""Files in messages: the customer and a partner can send each other a file (a site plan,
photos, a quote document) with a message.

* ``lead_message_attachment``: a platform table guarded by the API, like ``lead_message``.
  One file per message. What was sent never changes (trigger); only the virus scan's
  result is recorded, once it is known.

Revision ID: 0036
Revises: 0035
Create Date: 2026-11-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "approvalready_rw"

GUARD = """
CREATE FUNCTION lead_message_attachment_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF (to_jsonb(NEW) - ARRAY['scan_status', 'scan_engine', 'scan_signature',
                              'scan_attempts', 'scanned_at', 'storage_key'])
        IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['scan_status', 'scan_engine',
                              'scan_signature', 'scan_attempts', 'scanned_at',
                              'storage_key']) THEN
        RAISE EXCEPTION 'a sent file never changes';
    END IF;
    IF OLD.scan_status <> 'PENDING' AND NEW.scan_status IS DISTINCT FROM OLD.scan_status THEN
        RAISE EXCEPTION 'a file is scanned once';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER lead_message_attachment_immutable
    BEFORE UPDATE ON lead_message_attachment
    FOR EACH ROW EXECUTE FUNCTION lead_message_attachment_guard();
"""


def upgrade() -> None:
    op.create_table(
        "lead_message_attachment",
        sa.Column("lead_message_id", sa.UUID(), nullable=False),
        sa.Column("lead_match_id", sa.UUID(), nullable=False),
        sa.Column("storage_key", sa.String(length=300), nullable=False),
        sa.Column("original_filename", sa.String(length=200), nullable=False),
        sa.Column("extension", sa.String(length=10), nullable=False),
        sa.Column("detected_mime", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", postgresql.BYTEA(), nullable=False),
        sa.Column("scan_status", sa.Text(), server_default="PENDING", nullable=False),
        sa.Column("scan_engine", sa.String(length=40), nullable=True),
        sa.Column("scan_signature", sa.String(length=200), nullable=True),
        sa.Column("scan_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "octet_length(sha256) = 32", name=op.f("ck_lead_message_attachment_sha256_length")
        ),
        sa.CheckConstraint(
            "scan_status IN ('PENDING', 'CLEAN', 'INFECTED', 'ERROR')",
            name=op.f("ck_lead_message_attachment_scan_status_valid"),
        ),
        sa.CheckConstraint("size_bytes > 0", name=op.f("ck_lead_message_attachment_size_positive")),
        sa.ForeignKeyConstraint(
            ["lead_match_id"],
            ["lead_match.id"],
            name=op.f("fk_lead_message_attachment_lead_match_id_lead_match"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lead_message_id"],
            ["lead_message.id"],
            name=op.f("fk_lead_message_attachment_lead_message_id_lead_message"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lead_message_attachment")),
        sa.UniqueConstraint(
            "lead_message_id", name=op.f("uq_lead_message_attachment_lead_message_id")
        ),
        sa.UniqueConstraint("storage_key", name=op.f("uq_lead_message_attachment_storage_key")),
    )
    op.create_index(
        "ix_lead_message_attachment_match", "lead_message_attachment", ["lead_match_id"]
    )
    op.create_index(
        "ix_lead_message_attachment_pending",
        "lead_message_attachment",
        ["created_at"],
        postgresql_where=sa.text("scan_status = 'PENDING'"),
    )
    op.execute(GUARD)
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON lead_message_attachment TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP TRIGGER lead_message_attachment_immutable ON lead_message_attachment")
    op.drop_index("ix_lead_message_attachment_pending", table_name="lead_message_attachment")
    op.drop_index("ix_lead_message_attachment_match", table_name="lead_message_attachment")
    op.drop_table("lead_message_attachment")
    op.execute("DROP FUNCTION lead_message_attachment_guard()")
