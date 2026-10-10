"""Change of email address (Milestone 28).

* ``one_time_token.new_email``: the address an ``EMAIL_CHANGE`` link moves the account to.
  Only that purpose carries one (check constraint).
* Token purpose ``EMAIL_CHANGE``.

Revision ID: 0027
Revises: 0025
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PURPOSES_OLD = ("EMAIL_VERIFY", "PASSWORD_RESET")
PURPOSES_NEW = (*PURPOSES_OLD, "EMAIL_CHANGE")


def _purpose_check(purposes: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_one_time_token_purpose_valid"), "one_time_token", type_="check")
    op.create_check_constraint(
        op.f("ck_one_time_token_purpose_valid"),
        "one_time_token",
        "purpose IN (" + ", ".join(f"'{p}'" for p in purposes) + ")",
    )


def upgrade() -> None:
    op.add_column("one_time_token", sa.Column("new_email", postgresql.CITEXT(), nullable=True))
    _purpose_check(PURPOSES_NEW)
    op.create_check_constraint(
        op.f("ck_one_time_token_new_email_only_for_change"),
        "one_time_token",
        "(purpose = 'EMAIL_CHANGE') = (new_email IS NOT NULL)",
    )


def downgrade() -> None:
    op.execute("DELETE FROM one_time_token WHERE purpose = 'EMAIL_CHANGE'")
    op.drop_constraint(
        op.f("ck_one_time_token_new_email_only_for_change"), "one_time_token", type_="check"
    )
    _purpose_check(PURPOSES_OLD)
    op.drop_column("one_time_token", "new_email")
