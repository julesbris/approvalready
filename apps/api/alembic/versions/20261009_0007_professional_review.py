"""Professional review (Milestone 7).

* ``professional``, ``professional_credential``, ``professional_service``: platform tables
  (no tenant). Staff verify credentials and activate profiles.
* ``review_request`` (tenant, of the customer's organisation), ``review_comment``,
  ``finding_override`` and ``review_decision`` (tenant, append-only for the app role).
  One open review per project (partial unique index).
* ``evidence.review_note``: the reviewer's reason for accepting or rejecting a file.
* ``generated_document.review_status`` gains IN_REVIEW, CHANGES_REQUIRED, APPROVED and
  REVIEWED.
* ``review_request_organisation(id)`` and ``review_queue(professional, statuses)``: SECURITY
  DEFINER functions. The first returns only a review's organisation id, so a reviewer's
  request can bind that tenant (the assignment is then checked on the row itself). The
  second lists review summaries across tenants for staff, or for one professional.
* New permissions ``professional.verify`` and ``review.assign`` for STAFF, ADMIN and
  SUPERADMIN.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


APP_ROLE = "approvalready_rw"
WRITE = "SELECT, INSERT, UPDATE"
CRUD = "SELECT, INSERT, UPDATE, DELETE"
APPEND = "SELECT, INSERT"

# Privileges of the application role on the new tables (tests/test_rls.py keeps the map).
PRIVILEGES: dict[str, str] = {
    "professional": WRITE,
    "professional_credential": CRUD,
    "professional_service": CRUD,
    "review_request": WRITE,
    "review_comment": APPEND,
    "finding_override": APPEND,
    "review_decision": APPEND,
}
TENANT_TABLES = ("review_request", "review_comment", "finding_override", "review_decision")

TENANT_PREDICATE = "organisation_id = nullif(current_setting('app.current_org', true), '')::uuid"

# Frozen copy of the catalogue change in app/modules/tenancy/rbac.py.
NEW_PERMISSIONS = {
    "professional.verify": "Verify professionals and their credentials",
    "review.assign": "Assign professional reviews",
}
NEW_PERMISSION_ROLES = ("STAFF", "ADMIN", "SUPERADMIN")

OLD_REVIEW_STATUSES = "('NOT_REVIEWED')"
NEW_REVIEW_STATUSES = "('NOT_REVIEWED', 'IN_REVIEW', 'CHANGES_REQUIRED', 'APPROVED', 'REVIEWED')"

# Owned by the schema owner, so they read past row-level security. Ids and summaries only.
FUNCTIONS = """
CREATE FUNCTION review_request_organisation(request uuid) RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT organisation_id FROM review_request WHERE id = request
$$;
REVOKE ALL ON FUNCTION review_request_organisation(uuid) FROM PUBLIC;

CREATE FUNCTION review_queue(professional uuid, statuses text[])
RETURNS TABLE (
    id uuid, organisation_id uuid, status text, project_reference text, project_title text,
    vertical text, assigned_professional_id uuid, created_at timestamptz, due_on date
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT r.id, r.organisation_id, r.status, p.reference_code::text, p.title::text,
           p.vertical, r.assigned_professional_id, r.created_at, r.due_on
      FROM review_request r
      JOIN project p ON p.organisation_id = r.organisation_id AND p.id = r.project_id
     WHERE p.deleted_at IS NULL
       AND (professional IS NULL OR r.assigned_professional_id = professional)
       AND (statuses IS NULL OR r.status = ANY(statuses))
     ORDER BY r.due_on NULLS LAST, r.created_at
     LIMIT 500
$$;
REVOKE ALL ON FUNCTION review_queue(uuid, text[]) FROM PUBLIC;
"""


def _enable_tenant_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
    )


def _review_status_check(values: str) -> None:
    op.drop_constraint(
        op.f("ck_generated_document_review_status_valid"), "generated_document", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_generated_document_review_status_valid"),
        "generated_document",
        f"review_status IN {values}",
    )


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
            "WHERE r.key = ANY(:roles) AND p.key = ANY(:permissions)"
        ),
        {"roles": list(NEW_PERMISSION_ROLES), "permissions": list(NEW_PERMISSIONS)},
    )


def upgrade() -> None:
    op.create_table(
        "professional",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("practice_id", sa.UUID(), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("discipline", sa.Text(), nullable=False),
        sa.Column("bio", sa.String(length=1000), nullable=True),
        sa.Column("status", sa.Text(), server_default="PENDING", nullable=False),
        sa.Column("status_changed_by", sa.UUID(), nullable=True),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
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
            "discipline IN ('TOWN_PLANNER', 'SURVEYOR', 'BUILDING_CERTIFIER', 'BUILDING_DESIGNER', 'ENGINEER', 'MARINE_SURVEYOR', 'LAWYER', 'ACCOUNTANT', 'GRANT_WRITER', 'OTHER')",
            name=op.f("ck_professional_discipline_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'ACTIVE', 'SUSPENDED')",
            name=op.f("ck_professional_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_professional_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["practice_id"],
            ["organisation.id"],
            name=op.f("fk_professional_practice_id_organisation"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["status_changed_by"],
            ["app_user.id"],
            name=op.f("fk_professional_status_changed_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_professional_user_id_app_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_professional")),
        sa.UniqueConstraint(
            "user_id", "practice_id", name=op.f("uq_professional_user_id_practice_id")
        ),
    )
    op.create_table(
        "professional_credential",
        sa.Column("professional_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("issuer", sa.String(length=200), nullable=False),
        sa.Column("number", sa.String(length=100), nullable=False),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), server_default="UNVERIFIED", nullable=False),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("verified_by", sa.UUID(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
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
            "kind IN ('LICENCE', 'REGISTRATION', 'MEMBERSHIP', 'INSURANCE', 'QUALIFICATION')",
            name=op.f("ck_professional_credential_kind_valid"),
        ),
        sa.CheckConstraint(
            "status = 'UNVERIFIED' OR (verified_by IS NOT NULL AND verified_at IS NOT NULL)",
            name=op.f("ck_professional_credential_checked_has_checker"),
        ),
        sa.CheckConstraint(
            "status IN ('UNVERIFIED', 'VERIFIED', 'REJECTED')",
            name=op.f("ck_professional_credential_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_professional_credential_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["professional_id"],
            ["professional.id"],
            name=op.f("fk_professional_credential_professional_id_professional"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["verified_by"],
            ["app_user.id"],
            name=op.f("fk_professional_credential_verified_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_professional_credential")),
    )
    op.create_index(
        "ix_professional_credential_professional_id",
        "professional_credential",
        ["professional_id"],
        unique=False,
    )
    op.create_table(
        "professional_service",
        sa.Column("professional_id", sa.UUID(), nullable=False),
        sa.Column("vertical", sa.Text(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
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
        sa.CheckConstraint(
            "vertical IN ('PLANNING', 'VESSEL', 'BUSINESS', 'GRANT', 'SELL', 'RENT')",
            name=op.f("ck_professional_service_vertical_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["professional_id"],
            ["professional.id"],
            name=op.f("fk_professional_service_professional_id_professional"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_professional_service")),
        sa.UniqueConstraint(
            "professional_id",
            "vertical",
            name=op.f("uq_professional_service_professional_id_vertical"),
        ),
    )
    op.create_table(
        "review_request",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("assessment_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.Text(), server_default="REVIEW_REQUESTED", nullable=False),
        sa.Column("message", sa.String(length=2000), nullable=True),
        sa.Column("assigned_professional_id", sa.UUID(), nullable=True),
        sa.Column("assigned_by", sa.UUID(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('REVIEW_REQUESTED', 'ASSIGNED', 'IN_REVIEW', 'CHANGES_REQUIRED', 'APPROVED', 'COMPLETED', 'CANCELLED')",
            name=op.f("ck_review_request_status_valid"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('ASSIGNED', 'IN_REVIEW', 'CHANGES_REQUIRED', 'APPROVED', 'COMPLETED') OR assigned_professional_id IS NOT NULL",
            name=op.f("ck_review_request_assigned_has_professional"),
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by"],
            ["app_user.id"],
            name=op.f("fk_review_request_assigned_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_professional_id"],
            ["professional.id"],
            name=op.f("fk_review_request_assigned_professional_id_professional"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_review_request_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "assessment_id"],
            ["assessment.organisation_id", "assessment.id"],
            name=op.f("fk_review_request_organisation_id_assessment"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "project_id"],
            ["project.organisation_id", "project.id"],
            name=op.f("fk_review_request_organisation_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_review_request_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_request")),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_review_request_organisation_id_id")
        ),
    )
    op.create_index(
        "ix_review_request_assigned_professional_id",
        "review_request",
        ["assigned_professional_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_review_request_organisation_id"),
        "review_request",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        "ix_review_request_project_id", "review_request", ["project_id", "created_at"], unique=False
    )
    op.create_index(
        "uq_review_request_open_project",
        "review_request",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('REVIEW_REQUESTED', 'ASSIGNED', 'IN_REVIEW', 'CHANGES_REQUIRED')"
        ),
    )
    op.create_table(
        "finding_override",
        sa.Column("review_request_id", sa.UUID(), nullable=False),
        sa.Column("finding_id", sa.UUID(), nullable=False),
        sa.Column("previous_outcome_type", sa.Text(), nullable=True),
        sa.Column("previous_confidence", sa.Text(), nullable=False),
        sa.Column("new_outcome_type", sa.Text(), nullable=True),
        sa.Column("new_confidence", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(length=2000), nullable=False),
        sa.Column("source_reference_id", sa.UUID(), nullable=True),
        sa.Column("overridden_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "new_confidence IN ('VERIFIED', 'LIKELY', 'REVIEW_REQUIRED', 'UNKNOWN')",
            name=op.f("ck_finding_override_new_confidence_valid"),
        ),
        sa.CheckConstraint(
            "new_outcome_type IS NULL OR new_outcome_type IN ('APPROVAL_REQUIRED', 'APPROVAL_LIKELY', 'NOT_REQUIRED', 'EVIDENCE_REQUIRED', 'PROFESSIONAL_REQUIRED', 'REFERRAL_CATEGORY', 'CROSS_SELL', 'WARNING', 'INFO')",
            name=op.f("ck_finding_override_new_outcome_type_valid"),
        ),
        sa.CheckConstraint(
            "previous_confidence IN ('VERIFIED', 'LIKELY', 'REVIEW_REQUIRED', 'UNKNOWN')",
            name=op.f("ck_finding_override_previous_confidence_valid"),
        ),
        sa.CheckConstraint(
            "previous_outcome_type IS NULL OR previous_outcome_type IN ('APPROVAL_REQUIRED', 'APPROVAL_LIKELY', 'NOT_REQUIRED', 'EVIDENCE_REQUIRED', 'PROFESSIONAL_REQUIRED', 'REFERRAL_CATEGORY', 'CROSS_SELL', 'WARNING', 'INFO')",
            name=op.f("ck_finding_override_previous_outcome_type_valid"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(reason)) >= 10", name=op.f("ck_finding_override_reason_given")
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "finding_id"],
            ["assessment_finding.organisation_id", "assessment_finding.id"],
            name=op.f("fk_finding_override_organisation_id_assessment_finding"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "review_request_id"],
            ["review_request.organisation_id", "review_request.id"],
            name=op.f("fk_finding_override_organisation_id_review_request"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_finding_override_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["overridden_by"],
            ["app_user.id"],
            name=op.f("fk_finding_override_overridden_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_reference_id"],
            ["source_reference.id"],
            name=op.f("fk_finding_override_source_reference_id_source_reference"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_finding_override")),
    )
    op.create_index(
        "ix_finding_override_finding_id",
        "finding_override",
        ["finding_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_finding_override_organisation_id"),
        "finding_override",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        "ix_finding_override_review_request_id",
        "finding_override",
        ["review_request_id"],
        unique=False,
    )
    op.create_table(
        "review_comment",
        sa.Column("review_request_id", sa.UUID(), nullable=False),
        sa.Column("finding_id", sa.UUID(), nullable=True),
        sa.Column("author_id", sa.UUID(), nullable=True),
        sa.Column("author_role", sa.Text(), nullable=False),
        sa.Column("body", sa.String(length=4000), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "author_role IN ('CUSTOMER', 'REVIEWER')",
            name=op.f("ck_review_comment_author_role_valid"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(body)) > 0", name=op.f("ck_review_comment_body_not_blank")
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["app_user.id"],
            name=op.f("fk_review_comment_author_id_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "finding_id"],
            ["assessment_finding.organisation_id", "assessment_finding.id"],
            name=op.f("fk_review_comment_organisation_id_assessment_finding"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "review_request_id"],
            ["review_request.organisation_id", "review_request.id"],
            name=op.f("fk_review_comment_organisation_id_review_request"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_review_comment_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_comment")),
    )
    op.create_index(
        op.f("ix_review_comment_organisation_id"),
        "review_comment",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        "ix_review_comment_review_request_id",
        "review_comment",
        ["review_request_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "review_decision",
        sa.Column("review_request_id", sa.UUID(), nullable=False),
        sa.Column("assessment_id", sa.UUID(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("notes", sa.String(length=4000), nullable=True),
        sa.Column("professional_id", sa.UUID(), nullable=False),
        sa.Column("decided_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "decision IN ('CHANGES_REQUIRED', 'APPROVED', 'COMPLETED')",
            name=op.f("ck_review_decision_decision_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["app_user.id"],
            name=op.f("fk_review_decision_decided_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "assessment_id"],
            ["assessment.organisation_id", "assessment.id"],
            name=op.f("fk_review_decision_organisation_id_assessment"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "review_request_id"],
            ["review_request.organisation_id", "review_request.id"],
            name=op.f("fk_review_decision_organisation_id_review_request"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_review_decision_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["professional_id"],
            ["professional.id"],
            name=op.f("fk_review_decision_professional_id_professional"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_decision")),
    )
    op.create_index(
        op.f("ix_review_decision_organisation_id"),
        "review_decision",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        "ix_review_decision_review_request_id",
        "review_decision",
        ["review_request_id", "created_at"],
        unique=False,
    )
    op.add_column("evidence", sa.Column("review_note", sa.String(length=500), nullable=True))

    _review_status_check(NEW_REVIEW_STATUSES)
    op.execute(FUNCTIONS)
    op.execute(f"GRANT EXECUTE ON FUNCTION review_request_organisation(uuid) TO {APP_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION review_queue(uuid, text[]) TO {APP_ROLE}")
    for table in TENANT_TABLES:
        _enable_tenant_rls(table)
    for table, privileges in PRIVILEGES.items():
        op.execute(f"GRANT {privileges} ON {table} TO {APP_ROLE}")
    _seed_permissions()


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM role_permission WHERE permission_id IN "
            "(SELECT id FROM permission WHERE key = ANY(:keys))"
        ).bindparams(keys=list(NEW_PERMISSIONS))
    )
    op.execute(
        sa.text("DELETE FROM permission WHERE key = ANY(:keys)").bindparams(
            keys=list(NEW_PERMISSIONS)
        )
    )
    op.execute("DROP FUNCTION IF EXISTS review_queue(uuid, text[])")
    op.execute("DROP FUNCTION IF EXISTS review_request_organisation(uuid)")
    op.execute(
        "UPDATE generated_document SET review_status = 'NOT_REVIEWED' "
        "WHERE review_status <> 'NOT_REVIEWED'"
    )
    _review_status_check(OLD_REVIEW_STATUSES)
    op.drop_column("evidence", "review_note")
    op.drop_index("ix_review_decision_review_request_id", table_name="review_decision")
    op.drop_index(op.f("ix_review_decision_organisation_id"), table_name="review_decision")
    op.drop_table("review_decision")
    op.drop_index("ix_review_comment_review_request_id", table_name="review_comment")
    op.drop_index(op.f("ix_review_comment_organisation_id"), table_name="review_comment")
    op.drop_table("review_comment")
    op.drop_index("ix_finding_override_review_request_id", table_name="finding_override")
    op.drop_index(op.f("ix_finding_override_organisation_id"), table_name="finding_override")
    op.drop_index("ix_finding_override_finding_id", table_name="finding_override")
    op.drop_table("finding_override")
    op.drop_index(
        "uq_review_request_open_project",
        table_name="review_request",
        postgresql_where=sa.text(
            "status IN ('REVIEW_REQUESTED', 'ASSIGNED', 'IN_REVIEW', 'CHANGES_REQUIRED')"
        ),
    )
    op.drop_index("ix_review_request_project_id", table_name="review_request")
    op.drop_index(op.f("ix_review_request_organisation_id"), table_name="review_request")
    op.drop_index("ix_review_request_assigned_professional_id", table_name="review_request")
    op.drop_table("review_request")
    op.drop_table("professional_service")
    op.drop_index(
        "ix_professional_credential_professional_id", table_name="professional_credential"
    )
    op.drop_table("professional_credential")
    op.drop_table("professional")
