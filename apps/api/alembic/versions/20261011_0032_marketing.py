"""Marketing: the guides email list and guide posts to Facebook, Instagram and the list.

* ``newsletter_subscriber``: people on the guides email list (platform data, no RLS).
* ``marketing_post``: one guide on one channel, scheduled or sent (platform data, no RLS).
* ``marketing_autopost``: the single row of auto-post settings, added switched off.
* Permission ``marketing.manage`` (ADMIN, SUPERADMIN).

Revision ID: 0032
Revises: 0030
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0032"
# 0031 is taken by the checklist reports and project plans branch: whichever of the two
# merges second points this at the other.
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "approvalready_rw"

NEW_PERMISSIONS = {
    "marketing.manage": "Post guides to Facebook, Instagram and the email list (staff)",
}
PERMISSION_ROLES = {
    "marketing.manage": ("ADMIN", "SUPERADMIN"),
}


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def _seed_permissions() -> None:
    conn = op.get_bind()
    for key, description in NEW_PERMISSIONS.items():
        conn.execute(
            sa.text(
                "INSERT INTO permission (id, key, description) "
                "VALUES (gen_random_uuid(), :key, :description)"
            ),
            {"key": key, "description": description},
        )
        conn.execute(
            sa.text(
                "INSERT INTO role_permission (role_id, permission_id) "
                "SELECT r.id, p.id FROM role r, permission p "
                "WHERE r.key = ANY(:roles) AND p.key = :permission"
            ),
            {"roles": list(PERMISSION_ROLES[key]), "permission": key},
        )


def upgrade() -> None:
    op.create_table(
        "newsletter_subscriber",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("confirm_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("subscribed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unsubscribed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "email = lower(email)", name=op.f("ck_newsletter_subscriber_email_lowercase")
        ),
        sa.CheckConstraint(
            "source IN ('FORM', 'ACCOUNT')", name=op.f("ck_newsletter_subscriber_source_valid")
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'SUBSCRIBED', 'UNSUBSCRIBED')",
            name=op.f("ck_newsletter_subscriber_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_newsletter_subscriber_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_newsletter_subscriber")),
    )
    op.create_index(
        "uq_newsletter_subscriber_email", "newsletter_subscriber", ["email"], unique=True
    )
    op.create_index(
        "uq_newsletter_subscriber_user_id",
        "newsletter_subscriber",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "ix_newsletter_subscriber_status", "newsletter_subscriber", ["status", "id"], unique=False
    )

    op.create_table(
        "marketing_post",
        sa.Column("guide_ref", sa.String(length=120), nullable=False),
        sa.Column("guide_title", sa.String(length=300), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), server_default="MANUAL", nullable=False),
        sa.Column("auto_day", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), server_default="SCHEDULED", nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("link_url", sa.String(length=2000), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.String(length=1000), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_id", sa.String(length=200), nullable=True),
        sa.Column("external_url", sa.String(length=2000), nullable=True),
        sa.Column("sent_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_subscriber_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        *_timestamps(),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "(origin = 'AUTO') = (auto_day IS NOT NULL)",
            name=op.f("ck_marketing_post_auto_has_day"),
        ),
        sa.CheckConstraint(
            "channel <> 'EMAIL' OR subject IS NOT NULL",
            name=op.f("ck_marketing_post_email_has_subject"),
        ),
        sa.CheckConstraint(
            "channel IN ('FACEBOOK', 'INSTAGRAM', 'EMAIL')",
            name=op.f("ck_marketing_post_channel_valid"),
        ),
        sa.CheckConstraint(
            "origin IN ('MANUAL', 'AUTO')", name=op.f("ck_marketing_post_origin_valid")
        ),
        sa.CheckConstraint(
            "status IN ('SCHEDULED', 'PUBLISHING', 'POSTED', 'FAILED', 'CANCELLED')",
            name=op.f("ck_marketing_post_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_marketing_post_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_marketing_post")),
    )
    op.create_index(
        "ix_marketing_post_due",
        "marketing_post",
        ["scheduled_for"],
        unique=False,
        postgresql_where=sa.text("status = 'SCHEDULED'"),
    )
    op.create_index("ix_marketing_post_created", "marketing_post", ["created_at"], unique=False)
    op.create_index(
        "ix_marketing_post_guide", "marketing_post", ["guide_ref", "posted_at"], unique=False
    )
    op.create_index(
        "uq_marketing_post_auto_day", "marketing_post", ["channel", "auto_day"], unique=True
    )

    op.create_table(
        "marketing_autopost",
        sa.Column("id", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("channels", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column(
            "weekdays", postgresql.ARRAY(sa.SmallInteger()), server_default="{2,5}", nullable=False
        ),
        sa.Column("post_at", sa.Time(), server_default="09:00", nullable=False),
        sa.Column("skip_guides", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.CheckConstraint("id = 1", name=op.f("ck_marketing_autopost_single_row")),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["app_user.id"],
            name=op.f("fk_marketing_autopost_updated_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_marketing_autopost")),
    )
    op.execute("INSERT INTO marketing_autopost (id) VALUES (1)")

    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON newsletter_subscriber TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON marketing_post TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON marketing_autopost TO {APP_ROLE}")
    _seed_permissions()


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permission WHERE permission_id IN "
        "(SELECT id FROM permission WHERE key = 'marketing.manage')"
    )
    op.execute("DELETE FROM permission WHERE key = 'marketing.manage'")
    op.drop_table("marketing_autopost")
    op.drop_index("uq_marketing_post_auto_day", table_name="marketing_post")
    op.drop_index("ix_marketing_post_guide", table_name="marketing_post")
    op.drop_index("ix_marketing_post_created", table_name="marketing_post")
    op.drop_index(
        "ix_marketing_post_due",
        table_name="marketing_post",
        postgresql_where=sa.text("status = 'SCHEDULED'"),
    )
    op.drop_table("marketing_post")
    op.drop_index("ix_newsletter_subscriber_status", table_name="newsletter_subscriber")
    op.drop_index(
        "uq_newsletter_subscriber_user_id",
        table_name="newsletter_subscriber",
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.drop_index("uq_newsletter_subscriber_email", table_name="newsletter_subscriber")
    op.drop_table("newsletter_subscriber")
