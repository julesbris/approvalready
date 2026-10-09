"""GrantReady (Milestone 10): grant programs, rounds and matches.

* ``grant_program``: platform reference data (no tenant), managed by staff. Its eligibility
  criteria are an ordinary ``GRANT`` rule set (one per program).
* ``grant_round``: a program's application rounds; status and dates cite a source
  reference (R12).
* ``grant_match``: tenant, append-only. One program's result for one assessment of a grant
  project, derived from the findings of its rule set. Forced row-level security and a
  composite tenant key to the assessment.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "approvalready_rw"

# Privileges of the application role on the new tables (tests/test_rls.py keeps the map).
PRIVILEGES: dict[str, str] = {
    "grant_program": "SELECT, INSERT, UPDATE",
    "grant_round": "SELECT, INSERT, UPDATE",
    "grant_match": "SELECT, INSERT",
}

TENANT_TABLES = ("grant_match",)

TENANT_PREDICATE = "organisation_id = nullif(current_setting('app.current_org', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "grant_program",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.String(length=2000), nullable=False),
        sa.Column("administrator_id", sa.UUID(), nullable=False),
        sa.Column("jurisdiction", sa.String(length=64), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("rule_set_id", sa.UUID(), nullable=False),
        sa.Column("funding_summary", sa.String(length=500), nullable=True),
        sa.Column("min_amount_cents", sa.BigInteger(), nullable=True),
        sa.Column("max_amount_cents", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.Text(), server_default="ACTIVE", nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
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
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "jurisdiction ~ '^(CTH|QLD|NSW|VIC|SA|WA|TAS|NT|ACT|LGA:[A-Z][A-Z0-9_]{1,59})$'",
            name=op.f("ck_grant_program_jurisdiction_format"),
        ),
        sa.CheckConstraint(
            "key ~ '^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$'",
            name=op.f("ck_grant_program_key_format"),
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'RETIRED')", name=op.f("ck_grant_program_status_valid")
        ),
        sa.CheckConstraint(
            "max_amount_cents IS NULL OR min_amount_cents IS NULL OR max_amount_cents >= min_amount_cents",
            name=op.f("ck_grant_program_amount_range"),
        ),
        sa.CheckConstraint(
            "min_amount_cents IS NULL OR min_amount_cents >= 0",
            name=op.f("ck_grant_program_min_amount"),
        ),
        sa.ForeignKeyConstraint(
            ["administrator_id"],
            ["source_organisation.id"],
            name=op.f("fk_grant_program_administrator_id_source_organisation"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_grant_program_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["rule_set_id"],
            ["rule_set.id"],
            name=op.f("fk_grant_program_rule_set_id_rule_set"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_grant_program")),
        sa.UniqueConstraint("key", name=op.f("uq_grant_program_key")),
        sa.UniqueConstraint("rule_set_id", name=op.f("uq_grant_program_rule_set_id")),
    )
    op.create_table(
        "grant_round",
        sa.Column("program_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("opens_on", sa.Date(), nullable=True),
        sa.Column("closes_on", sa.Date(), nullable=True),
        sa.Column("dates_note", sa.String(length=500), nullable=True),
        sa.Column("source_reference_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
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
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "status IN ('UPCOMING', 'OPEN', 'PAUSED', 'CLOSED')",
            name=op.f("ck_grant_round_status_valid"),
        ),
        sa.CheckConstraint(
            "closes_on IS NULL OR opens_on IS NULL OR closes_on >= opens_on",
            name=op.f("ck_grant_round_closes_after_opens"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_grant_round_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["grant_program.id"],
            name=op.f("fk_grant_round_program_id_grant_program"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_reference_id"],
            ["source_reference.id"],
            name=op.f("fk_grant_round_source_reference_id_source_reference"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_grant_round")),
        sa.UniqueConstraint("program_id", "title", name=op.f("uq_grant_round_program_id_title")),
    )
    op.create_index("ix_grant_round_program_id", "grant_round", ["program_id"], unique=False)
    op.create_table(
        "grant_match",
        sa.Column("assessment_id", sa.UUID(), nullable=False),
        sa.Column("program_id", sa.UUID(), nullable=False),
        sa.Column("round_id", sa.UUID(), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Text(), nullable=False),
        sa.Column("criteria", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("missing_facts", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "confidence IN ('VERIFIED', 'LIKELY', 'REVIEW_REQUIRED', 'UNKNOWN')",
            name=op.f("ck_grant_match_confidence_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('STRONG_MATCH', 'POSSIBLE_MATCH', 'NEEDS_INFORMATION', 'NOT_ELIGIBLE')",
            name=op.f("ck_grant_match_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "assessment_id"],
            ["assessment.organisation_id", "assessment.id"],
            name=op.f("fk_grant_match_organisation_id_assessment"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_grant_match_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["grant_program.id"],
            name=op.f("fk_grant_match_program_id_grant_program"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["round_id"],
            ["grant_round.id"],
            name=op.f("fk_grant_match_round_id_grant_round"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_grant_match")),
        sa.UniqueConstraint(
            "assessment_id", "program_id", name=op.f("uq_grant_match_assessment_id_program_id")
        ),
    )
    op.create_index("ix_grant_match_assessment_id", "grant_match", ["assessment_id"], unique=False)
    op.create_index(
        op.f("ix_grant_match_organisation_id"), "grant_match", ["organisation_id"], unique=False
    )
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
        )
    for table, privileges in PRIVILEGES.items():
        op.execute(f"GRANT {privileges} ON {table} TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_index(op.f("ix_grant_match_organisation_id"), table_name="grant_match")
    op.drop_index("ix_grant_match_assessment_id", table_name="grant_match")
    op.drop_table("grant_match")
    op.drop_index("ix_grant_round_program_id", table_name="grant_round")
    op.drop_table("grant_round")
    op.drop_table("grant_program")
