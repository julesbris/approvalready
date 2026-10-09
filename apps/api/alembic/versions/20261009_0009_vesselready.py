"""VesselReady (Milestone 9): vessel certificates, the safety management system builder and
project checklists.

* ``vessel_certificate``: certificates a customer holds for a vessel (survey, operation,
  exemption, state registration), with an optional copy from their uploads. Soft-deleted.
* ``safety_management_system``: one draft SMS per vessel project, the customer's text per
  element of the reviewed structure (``app/modules/vessels/sms_structure.json``).
* ``project_checklist`` / ``checklist_item``: a reviewed checklist definition
  (``app/modules/checklists/definitions/``) copied into a project, added by an assessment
  finding that names it or by the customer; items are ticked off or marked not applicable.

All four are tenant tables with forced row-level security and composite tenant keys.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


APP_ROLE = "approvalready_rw"
WRITE = "SELECT, INSERT, UPDATE"
CRUD = "SELECT, INSERT, UPDATE, DELETE"

# Privileges of the application role on the new tables (tests/test_rls.py keeps the map).
PRIVILEGES: dict[str, str] = {
    "vessel_certificate": WRITE,
    "safety_management_system": WRITE,
    "project_checklist": CRUD,
    "checklist_item": CRUD,
}

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
        "safety_management_system",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("structure_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=True),
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
            "jsonb_typeof(content) = 'object'",
            name=op.f("ck_safety_management_system_content_object"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_safety_management_system_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "project_id"],
            ["project.organisation_id", "project.id"],
            name=op.f("fk_safety_management_system_organisation_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_safety_management_system_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["app_user.id"],
            name=op.f("fk_safety_management_system_updated_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_safety_management_system")),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_safety_management_system_organisation_id_id")
        ),
        sa.UniqueConstraint("project_id", name=op.f("uq_safety_management_system_project_id")),
    )
    op.create_index(
        op.f("ix_safety_management_system_organisation_id"),
        "safety_management_system",
        ["organisation_id"],
        unique=False,
    )
    op.create_table(
        "vessel_certificate",
        sa.Column("vessel_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("number", sa.String(length=60), nullable=True),
        sa.Column("issuer", sa.String(length=200), nullable=True),
        sa.Column("issued_on", sa.Date(), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("uploaded_document_id", sa.UUID(), nullable=True),
        sa.Column("notes", sa.String(length=1000), nullable=True),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('CERTIFICATE_OF_SURVEY', 'CERTIFICATE_OF_OPERATION', 'EXEMPTION', 'STATE_REGISTRATION', 'OTHER')",
            name=op.f("ck_vessel_certificate_kind_valid"),
        ),
        sa.CheckConstraint(
            "expires_on IS NULL OR issued_on IS NULL OR expires_on >= issued_on",
            name=op.f("ck_vessel_certificate_expires_after_issue"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_vessel_certificate_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "uploaded_document_id"],
            ["uploaded_document.organisation_id", "uploaded_document.id"],
            name=op.f("fk_vessel_certificate_organisation_id_uploaded_document"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "vessel_id"],
            ["vessel.organisation_id", "vessel.id"],
            name=op.f("fk_vessel_certificate_organisation_id_vessel"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_vessel_certificate_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vessel_certificate")),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_vessel_certificate_organisation_id_id")
        ),
    )
    op.create_index(
        op.f("ix_vessel_certificate_organisation_id"),
        "vessel_certificate",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        "ix_vessel_certificate_vessel_id", "vessel_certificate", ["vessel_id"], unique=False
    )
    op.create_table(
        "project_checklist",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("checklist_key", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=False),
        sa.Column("sources", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("definition_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("finding_id", sa.UUID(), nullable=True),
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
            "finding_id IS NULL OR origin = 'RULE'",
            name=op.f("ck_project_checklist_finding_only_for_rule"),
        ),
        sa.CheckConstraint(
            "origin IN ('RULE', 'USER')", name=op.f("ck_project_checklist_origin_valid")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_project_checklist_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "finding_id"],
            ["assessment_finding.organisation_id", "assessment_finding.id"],
            name=op.f("fk_project_checklist_organisation_id_assessment_finding"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "project_id"],
            ["project.organisation_id", "project.id"],
            name=op.f("fk_project_checklist_organisation_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_project_checklist_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_checklist")),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_project_checklist_organisation_id_id")
        ),
        sa.UniqueConstraint(
            "project_id",
            "checklist_key",
            name=op.f("uq_project_checklist_project_id_checklist_key"),
        ),
    )
    op.create_index(
        op.f("ix_project_checklist_organisation_id"),
        "project_checklist",
        ["organisation_id"],
        unique=False,
    )
    op.create_table(
        "checklist_item",
        sa.Column("checklist_id", sa.UUID(), nullable=False),
        sa.Column("item_key", sa.String(length=60), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("detail", sa.String(length=1000), nullable=True),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("status", sa.Text(), server_default="OPEN", nullable=False),
        sa.Column("note", sa.String(length=1000), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by", sa.UUID(), nullable=True),
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
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "(status = 'OPEN') = (completed_at IS NULL)",
            name=op.f("ck_checklist_item_completed_unless_open"),
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'DONE', 'NOT_APPLICABLE')",
            name=op.f("ck_checklist_item_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["completed_by"],
            ["app_user.id"],
            name=op.f("fk_checklist_item_completed_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "checklist_id"],
            ["project_checklist.organisation_id", "project_checklist.id"],
            name=op.f("fk_checklist_item_organisation_id_project_checklist"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_checklist_item_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_checklist_item")),
        sa.UniqueConstraint(
            "checklist_id", "item_key", name=op.f("uq_checklist_item_checklist_id_item_key")
        ),
    )
    op.create_index(
        "ix_checklist_item_checklist_id", "checklist_item", ["checklist_id"], unique=False
    )
    op.create_index(
        op.f("ix_checklist_item_organisation_id"),
        "checklist_item",
        ["organisation_id"],
        unique=False,
    )
    for table, privileges in PRIVILEGES.items():
        _enable_tenant_rls(table)
        op.execute(f"GRANT {privileges} ON {table} TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_index(op.f("ix_checklist_item_organisation_id"), table_name="checklist_item")
    op.drop_index("ix_checklist_item_checklist_id", table_name="checklist_item")
    op.drop_table("checklist_item")
    op.drop_index(op.f("ix_project_checklist_organisation_id"), table_name="project_checklist")
    op.drop_table("project_checklist")
    op.drop_index("ix_vessel_certificate_vessel_id", table_name="vessel_certificate")
    op.drop_index(op.f("ix_vessel_certificate_organisation_id"), table_name="vessel_certificate")
    op.drop_table("vessel_certificate")
    op.drop_index(
        op.f("ix_safety_management_system_organisation_id"), table_name="safety_management_system"
    )
    op.drop_table("safety_management_system")
