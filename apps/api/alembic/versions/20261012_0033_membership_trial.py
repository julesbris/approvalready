"""ApprovalReady Plus: a free first month, card taken up front, charged automatically after.

* ``subscription`` gains ``trial_end`` (from Stripe), ``trial_welcome_sent_at`` and
  ``trial_reminder_sent_at`` (the emails saying the trial started and that the first charge
  is coming), so each email goes out once.
* ``trials_to_email(remind_before, max_rows)``: SECURITY DEFINER, like ``quiet_projects``.
  Trialing subscriptions, in every organisation, still owed one of those emails: ids and
  dates only. The worker binds each organisation before reading or changing anything.

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "approvalready_rw"

TRIALS_TO_EMAIL = """
CREATE FUNCTION trials_to_email(remind_before interval, max_rows integer)
RETURNS TABLE (organisation_id uuid, subscription_id uuid, trial_end timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT s.organisation_id, s.id, s.trial_end
      FROM subscription s
      JOIN organisation o ON o.id = s.organisation_id
     WHERE s.status = 'TRIALING' AND s.trial_end > now() AND o.deleted_at IS NULL
       AND (
           s.trial_welcome_sent_at IS NULL
           OR (
               s.trial_reminder_sent_at IS NULL
               AND NOT s.cancel_at_period_end
               AND s.trial_end <= now() + remind_before
           )
       )
     ORDER BY s.trial_end, s.id
     LIMIT least(greatest(max_rows, 1), 5000)
$$;
REVOKE ALL ON FUNCTION trials_to_email(interval, integer) FROM PUBLIC;
"""


def upgrade() -> None:
    for column in ("trial_end", "trial_welcome_sent_at", "trial_reminder_sent_at"):
        op.add_column("subscription", sa.Column(column, sa.DateTime(timezone=True)))
    op.create_index(
        "ix_subscription_trialing",
        "subscription",
        ["trial_end"],
        unique=False,
        postgresql_where=sa.text("status = 'TRIALING'"),
    )
    op.execute(TRIALS_TO_EMAIL)
    op.execute(f"GRANT EXECUTE ON FUNCTION trials_to_email(interval, integer) TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION trials_to_email(interval, integer)")
    op.drop_index("ix_subscription_trialing", table_name="subscription")
    for column in ("trial_reminder_sent_at", "trial_welcome_sent_at", "trial_end"):
        op.drop_column("subscription", column)
