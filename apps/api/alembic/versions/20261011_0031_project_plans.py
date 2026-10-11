"""Project plans: a paid online tracker for one project, built from its checklist.

* ``project_plan``: one per project; ``PAYMENT_PENDING`` until Stripe confirms the payment
  (``payment_id``), then ``ACTIVE``. ``sections`` keeps each part's heading, fees, contacts
  and sources. Plans started while the plan isn't on sale are ``complimentary``.
* ``project_plan_item``: the steps, each with a due date, owner, status, note and files
  (``document_ids``, checked against the project's uploads when attached), and for a
  follow-up the partner to call. ``source_key`` ties a step to the checklist step it came
  from, so refreshing adds only new steps.

Both are tenant tables with forced row-level security; the application may read, add,
change and delete rows (customers remove their own steps; a plan not paid for can be
dropped). The plan's payment row is kept when a closed workspace is purged.

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "approvalready_rw"
CRUD = "SELECT, INSERT, UPDATE, DELETE"
# Privileges of the application role on the new tables (tests/test_rls.py keeps the map).
PRIVILEGES: dict[str, str] = {"project_plan": CRUD, "project_plan_item": CRUD}
TENANT_PREDICATE = "organisation_id = nullif(current_setting('app.current_org', true), '')::uuid"


def _enable_tenant_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
    )


def upgrade() -> None:
    op.create_table(
        "project_plan",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("assessment_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("payment_id", sa.UUID(), nullable=True),
        sa.Column("complimentary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sections", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "(status = 'ACTIVE') = (activated_at IS NOT NULL)",
            name=op.f("ck_project_plan_activated_when_active"),
        ),
        sa.CheckConstraint(
            "status <> 'PAYMENT_PENDING' OR payment_id IS NOT NULL",
            name=op.f("ck_project_plan_pending_has_payment"),
        ),
        sa.CheckConstraint(
            "status IN ('PAYMENT_PENDING', 'ACTIVE')", name=op.f("ck_project_plan_status_valid")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_project_plan_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "payment_id"],
            ["payment.organisation_id", "payment.id"],
            name=op.f("fk_project_plan_organisation_id_payment"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "project_id"],
            ["project.organisation_id", "project.id"],
            name=op.f("fk_project_plan_organisation_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_project_plan_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_plan")),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_project_plan_organisation_id_id")
        ),
        sa.UniqueConstraint("project_id", name=op.f("uq_project_plan_project_id")),
    )
    op.create_index(
        op.f("ix_project_plan_organisation_id"), "project_plan", ["organisation_id"], unique=False
    )
    op.create_table(
        "project_plan_item",
        sa.Column("plan_id", sa.UUID(), nullable=False),
        sa.Column("source_key", sa.String(length=200), nullable=True),
        sa.Column("section_key", sa.String(length=200), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=600), nullable=False),
        sa.Column("detail", sa.String(length=2000), nullable=True),
        sa.Column("timeframe", sa.String(length=600), nullable=True),
        sa.Column("cost", sa.String(length=600), nullable=True),
        sa.Column("link_url", sa.String(length=2000), nullable=True),
        sa.Column("link_label", sa.String(length=600), nullable=True),
        sa.Column("partner_organisation_id", sa.UUID(), nullable=True),
        sa.Column("owner", sa.String(length=120), nullable=True),
        sa.Column("assignee_user_id", sa.UUID(), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), server_default="OPEN", nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(length=2000), nullable=True),
        sa.Column(
            "document_ids",
            postgresql.ARRAY(sa.UUID()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
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
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "(status = 'OPEN') = (completed_at IS NULL)",
            name=op.f("ck_project_plan_item_completed_unless_open"),
        ),
        sa.CheckConstraint(
            "kind IN ('PREPARE', 'STEP', 'DOCUMENT', 'TASK', 'CHECK', 'FOLLOW_UP', 'CUSTOM')",
            name=op.f("ck_project_plan_item_kind_valid"),
        ),
        sa.CheckConstraint(
            "source_key IS NOT NULL OR kind IN ('FOLLOW_UP', 'CUSTOM')",
            name=op.f("ck_project_plan_item_source_for_built"),
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'DONE', 'NOT_APPLICABLE')",
            name=op.f("ck_project_plan_item_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["assignee_user_id"],
            ["app_user.id"],
            name=op.f("fk_project_plan_item_assignee_user_id_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_project_plan_item_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "plan_id"],
            ["project_plan.organisation_id", "project_plan.id"],
            name=op.f("fk_project_plan_item_organisation_id_project_plan"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_project_plan_item_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["partner_organisation_id"],
            ["partner_organisation.id"],
            name=op.f("fk_project_plan_item_partner_organisation_id_partner_organisation"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_plan_item")),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_project_plan_item_organisation_id_id")
        ),
        sa.UniqueConstraint(
            "plan_id", "source_key", name=op.f("uq_project_plan_item_plan_id_source_key")
        ),
    )
    op.create_index(
        op.f("ix_project_plan_item_organisation_id"),
        "project_plan_item",
        ["organisation_id"],
        unique=False,
    )
    op.create_index("ix_project_plan_item_plan_id", "project_plan_item", ["plan_id"], unique=False)
    for table, privileges in PRIVILEGES.items():
        _enable_tenant_rls(table)
        op.execute(f"GRANT {privileges} ON {table} TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_index("ix_project_plan_item_plan_id", table_name="project_plan_item")
    op.drop_index(op.f("ix_project_plan_item_organisation_id"), table_name="project_plan_item")
    op.drop_table("project_plan_item")
    op.drop_index(op.f("ix_project_plan_organisation_id"), table_name="project_plan")
    op.drop_table("project_plan")
