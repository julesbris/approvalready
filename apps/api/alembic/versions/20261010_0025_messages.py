"""Messages (Milestone 26): the customer and a partner who accepted their referral write to
each other about the job.

* ``lead_message``: a platform table guarded by the API, like the other lead tables.
  Messages are never edited or deleted (trigger); only ``read_at`` is set, once, when the
  other side opens the conversation (and ``sender_user_id`` may become NULL when a user row
  is removed).
* Notification kind ``MESSAGE_RECEIVED`` (both sides).

Revision ID: 0025
Revises: 0023
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "approvalready_rw"

KINDS_OLD = (
    "REMINDER",
    "GRANT_ROUND",
    "SOURCES_DUE",
    "LEAD_OFFERED",
    "LEAD_CLAIMED",
    "OPS_ALERT",
    "QUOTE_RECEIVED",
    "QUOTE_ANSWERED",
)
KINDS_NEW = (*KINDS_OLD, "MESSAGE_RECEIVED")

MESSAGE_GUARD = """
CREATE FUNCTION lead_message_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'a message cannot be deleted';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['read_at', 'sender_user_id'])
        IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['read_at', 'sender_user_id']) THEN
        RAISE EXCEPTION 'a sent message never changes';
    END IF;
    IF OLD.read_at IS NOT NULL AND NEW.read_at IS DISTINCT FROM OLD.read_at THEN
        RAISE EXCEPTION 'a message is marked read once';
    END IF;
    IF NEW.sender_user_id IS DISTINCT FROM OLD.sender_user_id
        AND NEW.sender_user_id IS NOT NULL THEN
        RAISE EXCEPTION 'the sender of a message never changes';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER lead_message_immutable
    BEFORE UPDATE OR DELETE ON lead_message
    FOR EACH ROW EXECUTE FUNCTION lead_message_guard();
"""


def _notification_kinds(kinds: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_notification_kind_valid"), "notification")
    quoted = ", ".join(f"'{k}'" for k in kinds)
    op.create_check_constraint(
        op.f("ck_notification_kind_valid"), "notification", f"kind IN ({quoted})"
    )


def upgrade() -> None:
    op.create_table(
        "lead_message",
        sa.Column("lead_match_id", sa.UUID(), nullable=False),
        sa.Column("lead_id", sa.UUID(), nullable=False),
        sa.Column("partner_organisation_id", sa.UUID(), nullable=False),
        sa.Column("sender", sa.Text(), nullable=False),
        sa.Column("sender_user_id", sa.UUID(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "char_length(btrim(body)) > 0", name=op.f("ck_lead_message_body_not_blank")
        ),
        sa.CheckConstraint("char_length(body) <= 4000", name=op.f("ck_lead_message_body_length")),
        sa.CheckConstraint(
            "sender IN ('CUSTOMER', 'PARTNER')", name=op.f("ck_lead_message_sender_valid")
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["lead.id"], name=op.f("fk_lead_message_lead_id_lead"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["lead_match_id"],
            ["lead_match.id"],
            name=op.f("fk_lead_message_lead_match_id_lead_match"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["partner_organisation_id"],
            ["partner_organisation.id"],
            name=op.f("fk_lead_message_partner_organisation_id_partner_organisation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sender_user_id"],
            ["app_user.id"],
            name=op.f("fk_lead_message_sender_user_id_app_user"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lead_message")),
    )
    op.create_index(
        "ix_lead_message_match", "lead_message", ["lead_match_id", "created_at"], unique=False
    )
    op.execute(MESSAGE_GUARD)
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON lead_message TO {APP_ROLE}")
    _notification_kinds(KINDS_NEW)


def downgrade() -> None:
    op.execute("DELETE FROM notification WHERE kind = 'MESSAGE_RECEIVED'")
    _notification_kinds(KINDS_OLD)
    op.drop_index("ix_lead_message_match", table_name="lead_message")
    op.drop_table("lead_message")
    op.execute("DROP FUNCTION lead_message_guard()")
