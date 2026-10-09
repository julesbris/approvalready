"""Documents (Milestone 6).

* ``uploaded_document``: tenant-owned upload metadata (binary in object storage), scan
  status and classification. Soft-deleted; the application role cannot delete rows.
* ``evidence``: an upload offered against an evidence requirement (needs a
  ``(organisation_id, id)`` key on ``evidence_requirement`` for its composite tenant key).
* ``document_template`` / ``document_template_version``: platform reference data synced by
  the migrate step (``python -m app.cli documents sync-templates``); read-only for the
  application role, and a stored version is immutable (trigger).
* ``generated_document``: a report rendered from a template version (PDF, DOCX, HTML).
* ``pending_document_jobs()``: SECURITY DEFINER function that lists stalled scans and
  generations (ids only) across tenants, so the scheduler can re-queue them without the
  application role ever reading other tenants' rows.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


APP_ROLE = "approvalready_rw"
READ = "SELECT"
WRITE = "SELECT, INSERT, UPDATE"
CRUD = "SELECT, INSERT, UPDATE, DELETE"

# Privileges of the application role on the new tables (tests/test_rls.py keeps the map).
PRIVILEGES: dict[str, str] = {
    "document_template": READ,
    "document_template_version": READ,
    "uploaded_document": WRITE,
    "evidence": CRUD,
    "generated_document": WRITE,
}
TENANT_TABLES = ("uploaded_document", "evidence", "generated_document")

TENANT_PREDICATE = "organisation_id = nullif(current_setting('app.current_org', true), '')::uuid"

TEMPLATE_VERSION_GUARD = """
CREATE FUNCTION document_template_version_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'document template versions cannot be deleted';
    END IF;
    IF NEW.template_id IS DISTINCT FROM OLD.template_id
        OR NEW.version IS DISTINCT FROM OLD.version
        OR NEW.engine IS DISTINCT FROM OLD.engine
        OR NEW.body IS DISTINCT FROM OLD.body
        OR NEW.output_formats IS DISTINCT FROM OLD.output_formats
        OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
        OR NEW.published_at IS DISTINCT FROM OLD.published_at THEN
        RAISE EXCEPTION 'document template versions are immutable';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status
        AND NOT (OLD.status = 'PUBLISHED' AND NEW.status = 'RETIRED') THEN
        RAISE EXCEPTION 'a document template version can only go from PUBLISHED to RETIRED';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER document_template_version_immutable
    BEFORE UPDATE OR DELETE ON document_template_version
    FOR EACH ROW EXECUTE FUNCTION document_template_version_guard();
"""

# Ids only, and only of work that has been waiting a while: enough to re-queue a job, nothing
# about its content. Owned by the schema owner, so it reads past row-level security.
PENDING_JOBS_FUNCTION = """
CREATE FUNCTION pending_document_jobs(older_than interval)
RETURNS TABLE (kind text, id uuid, organisation_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT 'scan', d.id, d.organisation_id FROM uploaded_document d
     WHERE d.scan_status = 'PENDING' AND d.deleted_at IS NULL
       AND d.updated_at < now() - older_than
    UNION ALL
    SELECT 'generate', g.id, g.organisation_id FROM generated_document g
     WHERE g.status = 'PENDING' AND g.updated_at < now() - older_than
    LIMIT 500
$$;
REVOKE ALL ON FUNCTION pending_document_jobs(interval) FROM PUBLIC;
"""


def _enable_tenant_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
    )


def upgrade() -> None:
    op.create_unique_constraint(
        op.f("uq_evidence_requirement_organisation_id_id"),
        "evidence_requirement",
        ["organisation_id", "id"],
    )
    op.create_table(
        "document_template",
        sa.Column("key", sa.String(length=60), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("vertical", sa.Text(), nullable=False),
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
            "key ~ '^[A-Z][A-Z0-9_]{1,59}$'", name=op.f("ck_document_template_key_format")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_template")),
        sa.UniqueConstraint("key", name=op.f("uq_document_template_key")),
    )
    op.create_table(
        "document_template_version",
        sa.Column("template_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("engine", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("output_formats", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("content_hash", sa.LargeBinary(), nullable=False),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "engine IN ('JINJA_HTML')", name=op.f("ck_document_template_version_engine_valid")
        ),
        sa.CheckConstraint(
            "output_formats <@ ARRAY['PDF', 'DOCX', 'HTML']::text[] AND cardinality(output_formats) > 0",
            name=op.f("ck_document_template_version_output_formats_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('PUBLISHED', 'RETIRED')",
            name=op.f("ck_document_template_version_status_valid"),
        ),
        sa.CheckConstraint(
            "octet_length(content_hash) = 32",
            name=op.f("ck_document_template_version_content_hash_sha256"),
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["document_template.id"],
            name=op.f("fk_document_template_version_template_id_document_template"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_template_version")),
        sa.UniqueConstraint(
            "template_id", "version", name=op.f("uq_document_template_version_template_id_version")
        ),
    )
    op.create_index(
        "uq_document_template_version_published",
        "document_template_version",
        ["template_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PUBLISHED'"),
    )
    op.create_table(
        "uploaded_document",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("storage_key", sa.String(length=300), nullable=False),
        sa.Column("original_filename", sa.String(length=200), nullable=False),
        sa.Column("extension", sa.String(length=10), nullable=False),
        sa.Column("declared_mime", sa.String(length=200), nullable=False),
        sa.Column("detected_mime", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.LargeBinary(), nullable=False),
        sa.Column("scan_status", sa.Text(), server_default="PENDING", nullable=False),
        sa.Column("scan_engine", sa.String(length=40), nullable=True),
        sa.Column("scan_signature", sa.String(length=200), nullable=True),
        sa.Column("scan_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("classification", sa.Text(), server_default="PRIVATE", nullable=False),
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
            "classification IN ('PRIVATE', 'SHARED_WITH_REVIEWER', 'RELEASED_TO_PARTNER')",
            name=op.f("ck_uploaded_document_classification_valid"),
        ),
        sa.CheckConstraint(
            "scan_status IN ('PENDING', 'CLEAN', 'INFECTED', 'ERROR')",
            name=op.f("ck_uploaded_document_scan_status_valid"),
        ),
        sa.CheckConstraint(
            "octet_length(sha256) = 32", name=op.f("ck_uploaded_document_sha256_length")
        ),
        sa.CheckConstraint("size_bytes > 0", name=op.f("ck_uploaded_document_size_positive")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_uploaded_document_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "project_id"],
            ["project.organisation_id", "project.id"],
            name=op.f("fk_uploaded_document_organisation_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_uploaded_document_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_uploaded_document")),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_uploaded_document_organisation_id_id")
        ),
        sa.UniqueConstraint("storage_key", name=op.f("uq_uploaded_document_storage_key")),
    )
    op.create_index(
        op.f("ix_uploaded_document_organisation_id"),
        "uploaded_document",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        "ix_uploaded_document_project_id",
        "uploaded_document",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "generated_document",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("assessment_id", sa.UUID(), nullable=True),
        sa.Column("template_version_id", sa.UUID(), nullable=False),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="PENDING", nullable=False),
        sa.Column("review_status", sa.Text(), server_default="NOT_REVIEWED", nullable=False),
        sa.Column("filename", sa.String(length=200), nullable=False),
        sa.Column("storage_key", sa.String(length=300), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.LargeBinary(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
            "format IN ('PDF', 'DOCX', 'HTML')", name=op.f("ck_generated_document_format_valid")
        ),
        sa.CheckConstraint(
            "review_status IN ('NOT_REVIEWED')",
            name=op.f("ck_generated_document_review_status_valid"),
        ),
        sa.CheckConstraint(
            "status <> 'READY' OR (storage_key IS NOT NULL AND sha256 IS NOT NULL AND size_bytes IS NOT NULL)",
            name=op.f("ck_generated_document_ready_has_content"),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'READY', 'FAILED')",
            name=op.f("ck_generated_document_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_generated_document_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "assessment_id"],
            ["assessment.organisation_id", "assessment.id"],
            name=op.f("fk_generated_document_organisation_id_assessment"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "project_id"],
            ["project.organisation_id", "project.id"],
            name=op.f("fk_generated_document_organisation_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_generated_document_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["template_version_id"],
            ["document_template_version.id"],
            name=op.f("fk_generated_document_template_version_id_document_template_version"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_generated_document")),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_generated_document_organisation_id_id")
        ),
    )
    op.create_index(
        op.f("ix_generated_document_organisation_id"),
        "generated_document",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        "ix_generated_document_project_id",
        "generated_document",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "evidence",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("evidence_requirement_id", sa.UUID(), nullable=False),
        sa.Column("uploaded_document_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.Text(), server_default="SUBMITTED", nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("reviewed_by", sa.UUID(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('SUBMITTED', 'ACCEPTED', 'REJECTED')", name=op.f("ck_evidence_status_valid")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_evidence_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "evidence_requirement_id"],
            ["evidence_requirement.organisation_id", "evidence_requirement.id"],
            name=op.f("fk_evidence_organisation_id_evidence_requirement"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "project_id"],
            ["project.organisation_id", "project.id"],
            name=op.f("fk_evidence_organisation_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "uploaded_document_id"],
            ["uploaded_document.organisation_id", "uploaded_document.id"],
            name=op.f("fk_evidence_organisation_id_uploaded_document"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_evidence_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["app_user.id"],
            name=op.f("fk_evidence_reviewed_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence")),
        sa.UniqueConstraint(
            "evidence_requirement_id",
            "uploaded_document_id",
            name=op.f("uq_evidence_evidence_requirement_id_uploaded_document_id"),
        ),
    )
    op.create_index(
        op.f("ix_evidence_organisation_id"), "evidence", ["organisation_id"], unique=False
    )
    op.create_index("ix_evidence_project_id", "evidence", ["project_id"], unique=False)

    op.execute(TEMPLATE_VERSION_GUARD)
    op.execute(PENDING_JOBS_FUNCTION)
    op.execute(f"GRANT EXECUTE ON FUNCTION pending_document_jobs(interval) TO {APP_ROLE}")
    for table in TENANT_TABLES:
        _enable_tenant_rls(table)
    for table, privileges in PRIVILEGES.items():
        op.execute(f"GRANT {privileges} ON {table} TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS pending_document_jobs(interval)")
    op.drop_index("ix_evidence_project_id", table_name="evidence")
    op.drop_index(op.f("ix_evidence_organisation_id"), table_name="evidence")
    op.drop_table("evidence")
    op.drop_index("ix_generated_document_project_id", table_name="generated_document")
    op.drop_index(op.f("ix_generated_document_organisation_id"), table_name="generated_document")
    op.drop_table("generated_document")
    op.drop_index("ix_uploaded_document_project_id", table_name="uploaded_document")
    op.drop_index(op.f("ix_uploaded_document_organisation_id"), table_name="uploaded_document")
    op.drop_table("uploaded_document")
    op.drop_index(
        "uq_document_template_version_published",
        table_name="document_template_version",
        postgresql_where=sa.text("status = 'PUBLISHED'"),
    )
    op.drop_table("document_template_version")
    op.execute("DROP FUNCTION IF EXISTS document_template_version_guard()")
    op.drop_table("document_template")
    op.drop_constraint(
        op.f("uq_evidence_requirement_organisation_id_id"), "evidence_requirement", type_="unique"
    )
