"""Regulatory sources, versioned rules and assessments (Milestone 4).

* Sources (``source_organisation``, ``source_document``, ``source_snapshot``,
  ``source_reference``, ``source_review_event``) and rules (``rule_set``, ``rule``,
  ``rule_version`` and its outcomes, sources, test cases and fact dependencies) are global
  reference data written by staff through ``/v1/admin``. Snapshots and review events are
  append-only for the application role; nothing in them is ever deleted by the app.
* Published rule versions and everything attached to them are immutable, even for the
  owner (triggers). A published version may only be retired.
* ``assessment`` and ``assessment_finding`` are tenant-owned (row-level security, composite
  tenant foreign keys) and append-only: a re-run is a new assessment.
* New permissions ``source.manage`` and ``rule.author`` for STAFF (and so ADMIN and
  SUPERADMIN); ``source.verify`` and ``rule.publish`` already exist (0002).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "approvalready_rw"

CRUD = "SELECT, INSERT, UPDATE, DELETE"
WRITE = "SELECT, INSERT, UPDATE"
APPEND = "SELECT, INSERT"

# Privileges of the application role on the new tables (tests/test_rls.py keeps the
# reviewed map for every table). Sources, rule sets and rules are never deleted by the app;
# draft rule versions (and their parts) can be.
PRIVILEGES: dict[str, str] = {
    "source_organisation": WRITE,
    "source_document": WRITE,
    "source_snapshot": APPEND,
    "source_reference": WRITE,
    "source_review_event": APPEND,
    "rule_set": WRITE,
    "rule": WRITE,
    "rule_version": CRUD,
    "rule_outcome": CRUD,
    "rule_source": CRUD,
    "rule_test_case": CRUD,
    "rule_fact_dependency": CRUD,
    "assessment": APPEND,
    "assessment_finding": APPEND,
}

TENANT_TABLES = ("assessment", "assessment_finding")

TENANT_PREDICATE = "organisation_id = nullif(current_setting('app.current_org', true), '')::uuid"

# Frozen copy of the catalogue change in app/modules/tenancy/rbac.py.
NEW_PERMISSIONS = {
    "source.manage": "Capture and edit regulatory sources",
    "rule.author": "Draft and test rules",
}
NEW_PERMISSION_ROLES = ("STAFF", "ADMIN", "SUPERADMIN")

RULE_IMMUTABLE_SQL = """
CREATE FUNCTION rule_version_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'DRAFT' THEN
            RAISE EXCEPTION 'rule version % is % and immutable', OLD.id, OLD.status;
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.status = 'DRAFT' THEN
        RETURN NEW;
    END IF;
    -- A published version may only be retired; nothing else about it can change.
    IF OLD.status = 'PUBLISHED' AND NEW.status = 'RETIRED'
       AND (NEW.rule_id, NEW.version, NEW.condition, NEW.effective_from, NEW.effective_to,
            NEW.max_confidence, NEW.notes, NEW.content_hash, NEW.published_by,
            NEW.published_at)
           IS NOT DISTINCT FROM
           (OLD.rule_id, OLD.version, OLD.condition, OLD.effective_from, OLD.effective_to,
            OLD.max_confidence, OLD.notes, OLD.content_hash, OLD.published_by,
            OLD.published_at) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'rule version % is % and immutable', OLD.id, OLD.status;
END;
$$;

CREATE TRIGGER rule_version_immutable
    BEFORE UPDATE OR DELETE ON rule_version
    FOR EACH ROW EXECUTE FUNCTION rule_version_guard();

-- Outcomes, sources, test cases and fact dependencies belong to their version: they can
-- only change while it is a draft.
CREATE FUNCTION rule_content_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    version_status text;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        SELECT status INTO version_status FROM rule_version WHERE id = OLD.rule_version_id;
        IF version_status IS NOT NULL AND version_status <> 'DRAFT' THEN
            RAISE EXCEPTION 'rule version % is % and immutable',
                OLD.rule_version_id, version_status;
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    SELECT status INTO version_status FROM rule_version WHERE id = NEW.rule_version_id;
    IF version_status IS NOT NULL AND version_status <> 'DRAFT' THEN
        RAISE EXCEPTION 'rule version % is % and immutable', NEW.rule_version_id, version_status;
    END IF;
    RETURN NEW;
END;
$$;
"""

RULE_CONTENT_TABLES = ("rule_outcome", "rule_source", "rule_test_case", "rule_fact_dependency")


def _enable_tenant_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
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
        "rule_set",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("vertical", sa.Text(), nullable=False),
        sa.Column("jurisdiction", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("applies_when", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
            name=op.f("ck_rule_set_jurisdiction_format"),
        ),
        sa.CheckConstraint(
            "key ~ '^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$'", name=op.f("ck_rule_set_key_format")
        ),
        sa.CheckConstraint(
            "vertical IN ('PLANNING', 'VESSEL', 'BUSINESS', 'GRANT', 'SELL', 'RENT')",
            name=op.f("ck_rule_set_vertical_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_rule_set_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rule_set")),
        sa.UniqueConstraint("key", name=op.f("uq_rule_set_key")),
    )
    op.create_table(
        "source_organisation",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("jurisdiction", sa.String(length=64), nullable=False),
        sa.Column("website", sa.String(length=500), nullable=True),
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
            name=op.f("ck_source_organisation_jurisdiction_format"),
        ),
        sa.CheckConstraint(
            "kind IN ('LEGISLATURE', 'COUNCIL', 'STATE_AGENCY', 'CTH_AGENCY', 'REGULATOR', 'GRANT_BODY')",
            name=op.f("ck_source_organisation_kind_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_source_organisation_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_organisation")),
        sa.UniqueConstraint("name", name=op.f("uq_source_organisation_name")),
    )
    op.create_table(
        "rule",
        sa.Column("rule_set_id", sa.UUID(), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
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
            "key ~ '^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$'", name=op.f("ck_rule_key_format")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_rule_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["rule_set_id"],
            ["rule_set.id"],
            name=op.f("fk_rule_rule_set_id_rule_set"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rule")),
        sa.UniqueConstraint("rule_set_id", "key", name=op.f("uq_rule_rule_set_id_key")),
    )
    op.create_table(
        "source_document",
        sa.Column("source_organisation_id", sa.UUID(), nullable=False),
        sa.Column("jurisdiction", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("version_label", sa.String(length=100), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("licence", sa.String(length=200), nullable=True),
        sa.Column("supersedes_id", sa.UUID(), nullable=True),
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
            name=op.f("ck_source_document_jurisdiction_format"),
        ),
        sa.CheckConstraint(
            "source_type IN ('LEGISLATION', 'REGULATION', 'PLANNING_SCHEME', 'POLICY', 'GUIDELINE', 'FORM', 'FEE_SCHEDULE', 'WEBPAGE', 'GRANT_GUIDELINES')",
            name=op.f("ck_source_document_source_type_valid"),
        ),
        sa.CheckConstraint("url ~ '^https?://'", name=op.f("ck_source_document_url_format")),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from",
            name=op.f("ck_source_document_effective_range"),
        ),
        sa.CheckConstraint(
            "supersedes_id IS NULL OR supersedes_id <> id",
            name=op.f("ck_source_document_not_self_superseding"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_source_document_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_organisation_id"],
            ["source_organisation.id"],
            name=op.f("fk_source_document_source_organisation_id_source_organisation"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["source_document.id"],
            name=op.f("fk_source_document_supersedes_id_source_document"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_document")),
    )
    op.create_index(
        "ix_source_document_source_organisation_id",
        "source_document",
        ["source_organisation_id"],
        unique=False,
    )
    op.create_table(
        "rule_version",
        sa.Column("rule_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), server_default="DRAFT", nullable=False),
        sa.Column("condition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("max_confidence", sa.Text(), server_default="VERIFIED", nullable=False),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.Column("content_hash", sa.LargeBinary(), nullable=True),
        sa.Column("published_by", sa.UUID(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
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
            "(status = 'DRAFT') = (published_at IS NULL)",
            name=op.f("ck_rule_version_published_at_when_published"),
        ),
        sa.CheckConstraint(
            "max_confidence IN ('VERIFIED', 'LIKELY', 'REVIEW_REQUIRED', 'UNKNOWN')",
            name=op.f("ck_rule_version_max_confidence_valid"),
        ),
        sa.CheckConstraint(
            "status = 'DRAFT' OR (effective_from IS NOT NULL AND content_hash IS NOT NULL)",
            name=op.f("ck_rule_version_published_is_complete"),
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'PUBLISHED', 'RETIRED')", name=op.f("ck_rule_version_status_valid")
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from",
            name=op.f("ck_rule_version_effective_range"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_rule_version_version_positive")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_rule_version_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["published_by"],
            ["app_user.id"],
            name=op.f("fk_rule_version_published_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["rule_id"], ["rule.id"], name=op.f("fk_rule_version_rule_id_rule"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rule_version")),
        sa.UniqueConstraint("rule_id", "version", name=op.f("uq_rule_version_rule_id_version")),
    )
    op.create_index(
        "uq_rule_version_published",
        "rule_version",
        ["rule_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PUBLISHED'"),
    )
    op.create_table(
        "source_snapshot",
        sa.Column("source_document_id", sa.UUID(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.LargeBinary(), nullable=False),
        sa.Column("captured_by", sa.UUID(), nullable=True),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "char_length(content_text) <= 1000000",
            name=op.f("ck_source_snapshot_content_text_size"),
        ),
        sa.CheckConstraint(
            "octet_length(content_hash) = 32", name=op.f("ck_source_snapshot_content_hash_sha256")
        ),
        sa.ForeignKeyConstraint(
            ["captured_by"],
            ["app_user.id"],
            name=op.f("fk_source_snapshot_captured_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_document.id"],
            name=op.f("fk_source_snapshot_source_document_id_source_document"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_snapshot")),
    )
    op.create_index(
        "ix_source_snapshot_document_captured",
        "source_snapshot",
        ["source_document_id", "captured_at"],
        unique=False,
    )
    op.create_table(
        "rule_fact_dependency",
        sa.Column("rule_version_id", sa.UUID(), nullable=False),
        sa.Column("fact_path", sa.String(length=120), nullable=False),
        sa.ForeignKeyConstraint(
            ["rule_version_id"],
            ["rule_version.id"],
            name=op.f("fk_rule_fact_dependency_rule_version_id_rule_version"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "rule_version_id", "fact_path", name=op.f("pk_rule_fact_dependency")
        ),
    )
    op.create_index(
        "ix_rule_fact_dependency_fact_path", "rule_fact_dependency", ["fact_path"], unique=False
    )
    op.create_table(
        "rule_outcome",
        sa.Column("rule_version_id", sa.UUID(), nullable=False),
        sa.Column("on_result", sa.Text(), nullable=False),
        sa.Column("outcome_type", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("detail", sa.String(length=2000), nullable=True),
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
            "on_result IN ('MATCH', 'NO_MATCH', 'UNKNOWN')",
            name=op.f("ck_rule_outcome_on_result_valid"),
        ),
        sa.CheckConstraint(
            "outcome_type IN ('APPROVAL_REQUIRED', 'APPROVAL_LIKELY', 'NOT_REQUIRED', 'EVIDENCE_REQUIRED', 'PROFESSIONAL_REQUIRED', 'REFERRAL_CATEGORY', 'CROSS_SELL', 'WARNING', 'INFO')",
            name=op.f("ck_rule_outcome_outcome_type_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["rule_version_id"],
            ["rule_version.id"],
            name=op.f("fk_rule_outcome_rule_version_id_rule_version"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rule_outcome")),
        sa.UniqueConstraint(
            "rule_version_id", "on_result", name=op.f("uq_rule_outcome_rule_version_id_on_result")
        ),
    )
    op.create_table(
        "rule_test_case",
        sa.Column("rule_version_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("facts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expected_result", sa.Text(), nullable=False),
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
            "expected_result IN ('MATCH', 'NO_MATCH', 'UNKNOWN')",
            name=op.f("ck_rule_test_case_expected_result_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["rule_version_id"],
            ["rule_version.id"],
            name=op.f("fk_rule_test_case_rule_version_id_rule_version"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rule_test_case")),
        sa.UniqueConstraint(
            "rule_version_id", "name", name=op.f("uq_rule_test_case_rule_version_id_name")
        ),
    )
    op.create_table(
        "source_reference",
        sa.Column("source_document_id", sa.UUID(), nullable=False),
        sa.Column("section", sa.String(length=200), nullable=True),
        sa.Column("clause", sa.String(length=100), nullable=True),
        sa.Column("page", sa.String(length=20), nullable=True),
        sa.Column("extracted_text", sa.String(length=10000), nullable=False),
        sa.Column("interpretation", sa.String(length=2000), nullable=True),
        sa.Column("verification_status", sa.Text(), server_default="UNVERIFIED", nullable=False),
        sa.Column("verified_by", sa.UUID(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_snapshot_id", sa.UUID(), nullable=True),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_review_due", sa.Date(), nullable=True),
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
            "verification_status <> 'VERIFIED' OR (verified_at IS NOT NULL AND verified_by IS NOT NULL AND next_review_due IS NOT NULL)",
            name=op.f("ck_source_reference_verified_has_reviewer"),
        ),
        sa.CheckConstraint(
            "verification_status IN ('UNVERIFIED', 'VERIFIED', 'DISPUTED', 'SUPERSEDED')",
            name=op.f("ck_source_reference_verification_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_source_reference_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_document.id"],
            name=op.f("fk_source_reference_source_document_id_source_document"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["verified_by"],
            ["app_user.id"],
            name=op.f("fk_source_reference_verified_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["verified_snapshot_id"],
            ["source_snapshot.id"],
            name=op.f("fk_source_reference_verified_snapshot_id_source_snapshot"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_reference")),
    )
    op.create_index(
        "ix_source_reference_review_queue",
        "source_reference",
        ["verification_status", "next_review_due"],
        unique=False,
    )
    op.create_index(
        "ix_source_reference_source_document_id",
        "source_reference",
        ["source_document_id"],
        unique=False,
    )
    op.create_table(
        "rule_source",
        sa.Column("rule_version_id", sa.UUID(), nullable=False),
        sa.Column("source_reference_id", sa.UUID(), nullable=False),
        sa.Column("relationship", sa.Text(), nullable=False),
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
            "relationship IN ('BASIS', 'SUPPORTING', 'EXCEPTION')",
            name=op.f("ck_rule_source_relationship_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["rule_version_id"],
            ["rule_version.id"],
            name=op.f("fk_rule_source_rule_version_id_rule_version"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_reference_id"],
            ["source_reference.id"],
            name=op.f("fk_rule_source_source_reference_id_source_reference"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rule_source")),
        sa.UniqueConstraint(
            "rule_version_id",
            "source_reference_id",
            name=op.f("uq_rule_source_rule_version_id_source_reference_id"),
        ),
    )
    op.create_index(
        "ix_rule_source_source_reference_id", "rule_source", ["source_reference_id"], unique=False
    )
    op.create_table(
        "source_review_event",
        sa.Column("source_reference_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column("reviewer_id", sa.UUID(), nullable=True),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "action IN ('CREATED', 'EDITED', 'VERIFIED', 'DISPUTED', 'SUPERSEDED', 'REOPENED')",
            name=op.f("ck_source_review_event_action_valid"),
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN ('UNVERIFIED', 'VERIFIED', 'DISPUTED', 'SUPERSEDED')",
            name=op.f("ck_source_review_event_from_status_valid"),
        ),
        sa.CheckConstraint(
            "to_status IN ('UNVERIFIED', 'VERIFIED', 'DISPUTED', 'SUPERSEDED')",
            name=op.f("ck_source_review_event_to_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"],
            ["app_user.id"],
            name=op.f("fk_source_review_event_reviewer_id_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_reference_id"],
            ["source_reference.id"],
            name=op.f("fk_source_review_event_source_reference_id_source_reference"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_review_event")),
    )
    op.create_index(
        "ix_source_review_event_source_reference_id",
        "source_review_event",
        ["source_reference_id"],
        unique=False,
    )
    op.create_table(
        "assessment",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("submission_id", sa.UUID(), nullable=False),
        sa.Column("assessed_on", sa.Date(), nullable=False),
        sa.Column("engine_version", sa.String(length=40), nullable=False),
        sa.Column("facts_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("facts_hash", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("overall_confidence", sa.Text(), nullable=False),
        sa.Column("rule_sets", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "overall_confidence IN ('VERIFIED', 'LIKELY', 'REVIEW_REQUIRED', 'UNKNOWN')",
            name=op.f("ck_assessment_overall_confidence_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('COMPLETED', 'NO_APPLICABLE_RULES')",
            name=op.f("ck_assessment_status_valid"),
        ),
        sa.CheckConstraint(
            "octet_length(facts_hash) = 32", name=op.f("ck_assessment_facts_hash_sha256")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_assessment_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "project_id"],
            ["project.organisation_id", "project.id"],
            name=op.f("fk_assessment_organisation_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "submission_id"],
            ["questionnaire_submission.organisation_id", "questionnaire_submission.id"],
            name=op.f("fk_assessment_organisation_id_questionnaire_submission"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_assessment_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assessment")),
        sa.UniqueConstraint("organisation_id", "id", name=op.f("uq_assessment_organisation_id_id")),
    )
    op.create_index(
        op.f("ix_assessment_organisation_id"), "assessment", ["organisation_id"], unique=False
    )
    op.create_index(
        "ix_assessment_project_id", "assessment", ["project_id", "created_at"], unique=False
    )
    op.create_table(
        "assessment_finding",
        sa.Column("assessment_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("rule_set_id", sa.UUID(), nullable=False),
        sa.Column("rule_version_id", sa.UUID(), nullable=False),
        sa.Column("rule_key", sa.String(length=100), nullable=False),
        sa.Column("rule_title", sa.String(length=200), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("outcome_type", sa.Text(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("detail", sa.String(length=2000), nullable=True),
        sa.Column("confidence", sa.Text(), nullable=False),
        sa.Column("confidence_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("trace", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("missing_facts", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("sources", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "confidence IN ('VERIFIED', 'LIKELY', 'REVIEW_REQUIRED', 'UNKNOWN')",
            name=op.f("ck_assessment_finding_confidence_valid"),
        ),
        sa.CheckConstraint(
            "outcome_type IS NULL OR outcome_type IN ('APPROVAL_REQUIRED', 'APPROVAL_LIKELY', 'NOT_REQUIRED', 'EVIDENCE_REQUIRED', 'PROFESSIONAL_REQUIRED', 'REFERRAL_CATEGORY', 'CROSS_SELL', 'WARNING', 'INFO')",
            name=op.f("ck_assessment_finding_outcome_type_valid"),
        ),
        sa.CheckConstraint(
            "result IN ('MATCH', 'NO_MATCH', 'UNKNOWN')",
            name=op.f("ck_assessment_finding_result_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "assessment_id"],
            ["assessment.organisation_id", "assessment.id"],
            name=op.f("fk_assessment_finding_organisation_id_assessment"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_assessment_finding_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["rule_set_id"],
            ["rule_set.id"],
            name=op.f("fk_assessment_finding_rule_set_id_rule_set"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["rule_version_id"],
            ["rule_version.id"],
            name=op.f("fk_assessment_finding_rule_version_id_rule_version"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assessment_finding")),
        sa.UniqueConstraint(
            "assessment_id",
            "rule_version_id",
            name=op.f("uq_assessment_finding_assessment_id_rule_version_id"),
        ),
    )
    op.create_index(
        op.f("ix_assessment_finding_organisation_id"),
        "assessment_finding",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        "ix_assessment_finding_rule_version_id",
        "assessment_finding",
        ["rule_version_id"],
        unique=False,
    )

    for table in TENANT_TABLES:
        _enable_tenant_rls(table)
    op.execute(RULE_IMMUTABLE_SQL)
    for table in RULE_CONTENT_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE INSERT OR UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION rule_content_guard()"
        )
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
    op.drop_index("ix_assessment_finding_rule_version_id", table_name="assessment_finding")
    op.drop_index(op.f("ix_assessment_finding_organisation_id"), table_name="assessment_finding")
    op.drop_table("assessment_finding")
    op.drop_index("ix_assessment_project_id", table_name="assessment")
    op.drop_index(op.f("ix_assessment_organisation_id"), table_name="assessment")
    op.drop_table("assessment")
    op.drop_index("ix_source_review_event_source_reference_id", table_name="source_review_event")
    op.drop_table("source_review_event")
    op.drop_index("ix_rule_source_source_reference_id", table_name="rule_source")
    op.drop_table("rule_source")
    op.drop_index("ix_source_reference_source_document_id", table_name="source_reference")
    op.drop_index("ix_source_reference_review_queue", table_name="source_reference")
    op.drop_table("source_reference")
    op.drop_table("rule_test_case")
    op.drop_table("rule_outcome")
    op.drop_index("ix_rule_fact_dependency_fact_path", table_name="rule_fact_dependency")
    op.drop_table("rule_fact_dependency")
    op.drop_index("ix_source_snapshot_document_captured", table_name="source_snapshot")
    op.drop_table("source_snapshot")
    op.drop_index(
        "uq_rule_version_published",
        table_name="rule_version",
        postgresql_where=sa.text("status = 'PUBLISHED'"),
    )
    op.drop_table("rule_version")
    op.drop_index("ix_source_document_source_organisation_id", table_name="source_document")
    op.drop_table("source_document")
    op.drop_table("rule")
    op.drop_table("source_organisation")
    op.drop_table("rule_set")
    op.execute("DROP FUNCTION IF EXISTS rule_content_guard()")
    op.execute("DROP FUNCTION IF EXISTS rule_version_guard()")
