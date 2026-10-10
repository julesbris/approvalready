"""Account security (Milestone 18): two-step sign-in.

* ``mfa_totp``: one authenticator app per user (sealed secret, confirmation, last step).
* ``mfa_recovery_code``: single-use recovery codes (SHA-256 digests).
* ``auth_session.mfa_verified_at``: when the session passed two-step sign-in.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "approvalready_rw"


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


def upgrade() -> None:
    op.add_column(
        "auth_session", sa.Column("mfa_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "mfa_totp",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("secret_sealed", sa.LargeBinary(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_step", sa.BigInteger(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_mfa_totp_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mfa_totp")),
        sa.UniqueConstraint("user_id", name=op.f("uq_mfa_totp_user_id")),
    )
    op.create_table(
        "mfa_recovery_code",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("code_hash", sa.LargeBinary(), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_mfa_recovery_code_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mfa_recovery_code")),
        sa.UniqueConstraint(
            "user_id", "code_hash", name=op.f("uq_mfa_recovery_code_user_id_code_hash")
        ),
    )
    op.create_index(
        op.f("ix_mfa_recovery_code_user_id"), "mfa_recovery_code", ["user_id"], unique=False
    )
    for table in ("mfa_totp", "mfa_recovery_code"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_index(op.f("ix_mfa_recovery_code_user_id"), table_name="mfa_recovery_code")
    op.drop_table("mfa_recovery_code")
    op.drop_table("mfa_totp")
    op.drop_column("auth_session", "mfa_verified_at")
