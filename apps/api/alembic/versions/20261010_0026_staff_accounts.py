"""Staff accounts page (Milestone 27).

* Permission ``platform.users.manage`` for ADMIN and SUPERADMIN: resend sign-up emails,
  send password reset links, sign people out, reset two-step sign-in, suspend and restore
  accounts from ``/admin/accounts``.
* Index on ``audit_event (target_type, target_id, seq)`` so an account's history (what was
  done to it, not just what it did) is a quick lookup.

Revision ID: 0026
Revises: 0023
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISSION = "platform.users.manage"
PERMISSION_DESCRIPTION = (
    "Resend sign-up emails, send password resets, sign out, reset two-step sign-in, "
    "suspend and restore accounts (staff)"
)
PERMISSION_ROLES = ["ADMIN", "SUPERADMIN"]


def upgrade() -> None:
    op.create_index(
        "ix_audit_event_target_seq",
        "audit_event",
        ["target_type", "target_id", "seq"],
        unique=False,
    )
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO permission (id, key, description) "
            "VALUES (gen_random_uuid(), :key, :description)"
        ),
        {"key": PERMISSION, "description": PERMISSION_DESCRIPTION},
    )
    conn.execute(
        sa.text(
            "INSERT INTO role_permission (role_id, permission_id) "
            "SELECT r.id, p.id FROM role r, permission p "
            "WHERE r.key = ANY(:roles) AND p.key = :permission"
        ),
        {"roles": PERMISSION_ROLES, "permission": PERMISSION},
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permission WHERE permission_id IN "
        "(SELECT id FROM permission WHERE key = 'platform.users.manage')"
    )
    op.execute("DELETE FROM permission WHERE key = 'platform.users.manage'")
    op.drop_index("ix_audit_event_target_seq", table_name="audit_event")
