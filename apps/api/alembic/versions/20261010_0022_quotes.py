"""Quotes (Milestone 23): partners who accepted a referral send the customer a written quote;
the customer accepts or declines it.

* ``lead_quote``: a platform table guarded by the API, like the other lead tables. What was
  quoted never changes once sent (trigger): a revision is a new version and the earlier one
  is superseded. Only the answer (status, when, by whom, a note) is recorded later, once,
  and quotes are never deleted.
* Notification kinds ``QUOTE_RECEIVED`` (customer) and ``QUOTE_ANSWERED`` (partner).

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "approvalready_rw"

KINDS_OLD = ("REMINDER", "GRANT_ROUND", "SOURCES_DUE", "LEAD_OFFERED", "LEAD_CLAIMED", "OPS_ALERT")
KINDS_NEW = (*KINDS_OLD, "QUOTE_RECEIVED", "QUOTE_ANSWERED")

QUOTE_GUARD = """
CREATE FUNCTION lead_quote_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'a quote cannot be deleted';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['status', 'responded_at', 'responded_by', 'response_note'])
        IS DISTINCT FROM
        (to_jsonb(OLD) - ARRAY['status', 'responded_at', 'responded_by', 'response_note']) THEN
        RAISE EXCEPTION 'a sent quote never changes; send a new version';
    END IF;
    IF OLD.status <> 'SENT' AND to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD) THEN
        RAISE EXCEPTION 'a quote is answered once';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER lead_quote_immutable
    BEFORE UPDATE OR DELETE ON lead_quote
    FOR EACH ROW EXECUTE FUNCTION lead_quote_guard();
"""


def _notification_kinds(kinds: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_notification_kind_valid"), "notification")
    quoted = ", ".join(f"'{k}'" for k in kinds)
    op.create_check_constraint(
        op.f("ck_notification_kind_valid"), "notification", f"kind IN ({quoted})"
    )


def upgrade() -> None:
    op.create_table(
        "lead_quote",
        sa.Column("lead_match_id", sa.UUID(), nullable=False),
        sa.Column("lead_id", sa.UUID(), nullable=False),
        sa.Column("partner_organisation_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), server_default="SENT", nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("line_items", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("total_cents", sa.BigInteger(), nullable=False),
        sa.Column("gst", sa.Text(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=False),
        sa.Column("start_estimate", sa.String(length=200), nullable=True),
        sa.Column("terms", sa.Text(), nullable=True),
        sa.Column("sent_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_by", sa.UUID(), nullable=True),
        sa.Column("response_note", sa.String(length=500), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "gst IN ('INCLUDED', 'EXCLUDED', 'NOT_REGISTERED')",
            name=op.f("ck_lead_quote_gst_valid"),
        ),
        sa.CheckConstraint(
            "status = 'SENT' OR responded_at IS NOT NULL",
            name=op.f("ck_lead_quote_answered_has_time"),
        ),
        sa.CheckConstraint(
            "status IN ('SENT', 'SUPERSEDED', 'WITHDRAWN', 'ACCEPTED', 'DECLINED')",
            name=op.f("ck_lead_quote_status_valid"),
        ),
        sa.CheckConstraint("total_cents >= 0", name=op.f("ck_lead_quote_total_not_negative")),
        sa.CheckConstraint("version > 0", name=op.f("ck_lead_quote_version_positive")),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["lead.id"], name=op.f("fk_lead_quote_lead_id_lead"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["lead_match_id"],
            ["lead_match.id"],
            name=op.f("fk_lead_quote_lead_match_id_lead_match"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["partner_organisation_id"],
            ["partner_organisation.id"],
            name=op.f("fk_lead_quote_partner_organisation_id_partner_organisation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["responded_by"],
            ["app_user.id"],
            name=op.f("fk_lead_quote_responded_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["sent_by"],
            ["app_user.id"],
            name=op.f("fk_lead_quote_sent_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lead_quote")),
        sa.UniqueConstraint(
            "lead_match_id", "version", name=op.f("uq_lead_quote_lead_match_id_version")
        ),
    )
    op.create_index("ix_lead_quote_lead", "lead_quote", ["lead_id", "created_at"], unique=False)
    op.create_index(
        "uq_lead_quote_sent_match",
        "lead_quote",
        ["lead_match_id"],
        unique=True,
        postgresql_where=sa.text("status = 'SENT'"),
    )
    op.execute(QUOTE_GUARD)
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON lead_quote TO {APP_ROLE}")
    _notification_kinds(KINDS_NEW)


def downgrade() -> None:
    op.execute("DELETE FROM notification WHERE kind IN ('QUOTE_RECEIVED', 'QUOTE_ANSWERED')")
    _notification_kinds(KINDS_OLD)
    op.drop_index(
        "uq_lead_quote_sent_match",
        table_name="lead_quote",
        postgresql_where=sa.text("status = 'SENT'"),
    )
    op.drop_index("ix_lead_quote_lead", table_name="lead_quote")
    op.drop_table("lead_quote")
    op.execute("DROP FUNCTION lead_quote_guard()")
