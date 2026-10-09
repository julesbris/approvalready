"""Requirements and tasks from findings (Milestone 5).

* ``rule_outcome.payload``: structured consequences of an outcome (approval, evidence,
  referral categories, task), validated by ``app/modules/rules/payload.py``. Covered by the
  existing immutability trigger once its version leaves draft.
* ``rule_set.limitations``: what a rule set does not check, shown with every assessment.
* ``assessment_finding.payload`` (copied from the outcome) and a ``(organisation_id, id)``
  key so tenant tables can reference findings with composite foreign keys.
* ``approval_requirement`` and ``evidence_requirement``: tenant-owned, append-only, derived
  from findings when an assessment runs (row-level security, composite tenant keys).
* ``task.finding_id``: the finding that suggested a rule-generated task.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "approvalready_rw"
APPEND = "SELECT, INSERT"

# Privileges of the application role on the new tables (tests/test_rls.py keeps the map).
PRIVILEGES: dict[str, str] = {
    "approval_requirement": APPEND,
    "evidence_requirement": APPEND,
}

TENANT_PREDICATE = "organisation_id = nullif(current_setting('app.current_org', true), '')::uuid"

CONFIDENCE_CHECK = "confidence IN ('VERIFIED', 'LIKELY', 'REVIEW_REQUIRED', 'UNKNOWN')"
KIND_CHECK = "kind ~ '^[A-Z][A-Z0-9_]{1,59}$'"


def _enable_tenant_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
    )


def _requirement_columns() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("assessment_id", sa.UUID(), nullable=False),
        sa.Column("finding_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=60), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
    ]


def _requirement_constraints(table: str) -> list[sa.Constraint]:
    return [
        sa.CheckConstraint(CONFIDENCE_CHECK, name=op.f(f"ck_{table}_confidence_valid")),
        sa.CheckConstraint(KIND_CHECK, name=op.f(f"ck_{table}_kind_format")),
        sa.ForeignKeyConstraint(
            ["organisation_id", "assessment_id"],
            ["assessment.organisation_id", "assessment.id"],
            name=op.f(f"fk_{table}_organisation_id_assessment"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "finding_id"],
            ["assessment_finding.organisation_id", "assessment_finding.id"],
            name=op.f(f"fk_{table}_organisation_id_assessment_finding"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f(f"fk_{table}_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
    ]


def _common_tail() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("confidence", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
    ]


def upgrade() -> None:
    op.add_column(
        "rule_outcome",
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "rule_set",
        sa.Column(
            "limitations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "assessment_finding",
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_unique_constraint(
        op.f("uq_assessment_finding_organisation_id_id"),
        "assessment_finding",
        ["organisation_id", "id"],
    )

    op.create_table(
        "approval_requirement",
        *_requirement_columns(),
        sa.Column("authority", sa.String(length=200), nullable=True),
        sa.Column("pathway", sa.String(length=200), nullable=True),
        sa.Column("certainty", sa.Text(), nullable=False),
        *_common_tail(),
        sa.CheckConstraint(
            "certainty IN ('REQUIRED', 'LIKELY_REQUIRED', 'MAY_APPLY', 'NOT_IDENTIFIED')",
            name=op.f("ck_approval_requirement_certainty_valid"),
        ),
        *_requirement_constraints("approval_requirement"),
        sa.UniqueConstraint("finding_id", name=op.f("uq_approval_requirement_finding_id")),
    )
    op.create_index(
        op.f("ix_approval_requirement_organisation_id"),
        "approval_requirement",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        "ix_approval_requirement_assessment_id",
        "approval_requirement",
        ["assessment_id"],
        unique=False,
    )

    op.create_table(
        "evidence_requirement",
        *_requirement_columns(),
        sa.Column("detail", sa.String(length=2000), nullable=True),
        *_common_tail(),
        *_requirement_constraints("evidence_requirement"),
    )
    op.create_index(
        op.f("ix_evidence_requirement_organisation_id"),
        "evidence_requirement",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        "ix_evidence_requirement_assessment_id",
        "evidence_requirement",
        ["assessment_id"],
        unique=False,
    )

    op.add_column("task", sa.Column("finding_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_task_organisation_id_assessment_finding"),
        "task",
        "assessment_finding",
        ["organisation_id", "finding_id"],
        ["organisation_id", "id"],
    )
    op.create_check_constraint(
        op.f("ck_task_finding_only_for_rule"), "task", "finding_id IS NULL OR source = 'RULE'"
    )

    for table, privileges in PRIVILEGES.items():
        _enable_tenant_rls(table)
        op.execute(f"GRANT {privileges} ON {table} TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_task_finding_only_for_rule"), "task", type_="check")
    op.drop_constraint(
        op.f("fk_task_organisation_id_assessment_finding"), "task", type_="foreignkey"
    )
    op.drop_column("task", "finding_id")
    op.drop_index("ix_evidence_requirement_assessment_id", table_name="evidence_requirement")
    op.drop_index(
        op.f("ix_evidence_requirement_organisation_id"), table_name="evidence_requirement"
    )
    op.drop_table("evidence_requirement")
    op.drop_index("ix_approval_requirement_assessment_id", table_name="approval_requirement")
    op.drop_index(
        op.f("ix_approval_requirement_organisation_id"), table_name="approval_requirement"
    )
    op.drop_table("approval_requirement")
    op.drop_constraint(
        op.f("uq_assessment_finding_organisation_id_id"), "assessment_finding", type_="unique"
    )
    op.drop_column("assessment_finding", "payload")
    op.drop_column("rule_set", "limitations")
    op.drop_column("rule_outcome", "payload")
