"""Notification preferences (Milestone 21): what each person hears about, and how.

* ``notification_preference``: one row per person and category (reminders, grant rounds,
  referrals, source reviews) with the channel: in the app and by email, in the app only,
  or off. No row means both. Unsubscribe links in emails switch a category to in-app only.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "approvalready_rw"


def upgrade() -> None:
    op.create_table(
        "notification_preference",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "category IN ('REMINDERS', 'GRANT_ROUNDS', 'REFERRALS', 'SOURCE_REVIEWS')",
            name=op.f("ck_notification_preference_category_valid"),
        ),
        sa.CheckConstraint(
            "channel IN ('ALL', 'IN_APP', 'OFF')",
            name=op.f("ck_notification_preference_channel_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_notification_preference_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "category", name=op.f("pk_notification_preference")),
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON notification_preference TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_table("notification_preference")
