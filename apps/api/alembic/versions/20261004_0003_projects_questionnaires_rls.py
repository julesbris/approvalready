"""Customer entities, projects, questionnaires; application DB role and row-level security
(Milestone 3).

* ``approvalready_rw``: NOLOGIN group role holding the application's table privileges. The
  login role the API connects as (``DATABASE_URL``) is created by
  ``python -m app.cli provision-db-role`` and made a member. It owns nothing, is not a
  superuser and has no BYPASSRLS, so row-level security applies to it. Group roles are
  cluster objects: downgrade revokes this database's privileges but keeps the role.
* Least privilege: reference data (roles, permissions, questionnaire definitions) is
  read-only for the app; append-only tables (``audit_event``, ``project_status_event``)
  are insert/select only. ``tests/test_rls.py`` pins the full privilege map.
* Row-level security on every tenant-owned table (``organisation_id`` column): rows are
  visible and writable only when ``organisation_id`` equals the transaction-local setting
  ``app.current_org`` (see ``app/db/tenant.py``). FORCE applies it to a non-superuser
  owner too.
* Published questionnaire versions are immutable (triggers).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "approvalready_rw"

CRUD = "SELECT, INSERT, UPDATE, DELETE"
APPEND = "SELECT, INSERT"
READ = "SELECT"

# Privileges of the application role, per table. tests/test_rls.py asserts the database
# matches its own copy of this map, so a new table needs a deliberate decision.
PRIVILEGES: dict[str, str] = {
    # Milestone 2
    "app_user": CRUD,
    "password_credential": CRUD,
    "auth_identity": CRUD,
    "auth_session": CRUD,
    "one_time_token": CRUD,
    "organisation": CRUD,
    "organisation_member": CRUD,
    "organisation_invitation": CRUD,
    "member_role": CRUD,
    "role": READ,
    "permission": READ,
    "role_permission": READ,
    "audit_event": APPEND,
    # Milestone 3
    "address": CRUD,
    "property": CRUD,
    "property_ownership": CRUD,
    "vessel": CRUD,
    "business_profile": CRUD,
    "project": CRUD,
    "project_status_event": APPEND,
    "task": CRUD,
    "reminder": CRUD,
    "questionnaire": READ,
    "questionnaire_version": READ,
    "question": READ,
    "question_version": READ,
    "question_option": READ,
    "questionnaire_submission": CRUD,
    "question_response": CRUD,
}

TENANT_TABLES = (
    "address",
    "property",
    "property_ownership",
    "vessel",
    "business_profile",
    "project",
    "project_status_event",
    "task",
    "reminder",
    "questionnaire_submission",
    "question_response",
)

TENANT_PREDICATE = "organisation_id = nullif(current_setting('app.current_org', true), '')::uuid"

CREATE_APP_ROLE_SQL = f"""
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
        CREATE ROLE {APP_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
    END IF;
END
$$;
"""

QUESTIONNAIRE_IMMUTABLE_SQL = """
CREATE FUNCTION questionnaire_version_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'DRAFT' THEN
            RAISE EXCEPTION 'questionnaire version % is % and immutable', OLD.id, OLD.status;
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.status = 'DRAFT' THEN
        RETURN NEW;
    END IF;
    -- A published version may only be retired; nothing else about it can change.
    IF OLD.status = 'PUBLISHED' AND NEW.status = 'RETIRED'
       AND (NEW.questionnaire_id, NEW.version, NEW.title, NEW.description, NEW.content_hash,
            NEW.published_at)
           IS NOT DISTINCT FROM
           (OLD.questionnaire_id, OLD.version, OLD.title, OLD.description, OLD.content_hash,
            OLD.published_at) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'questionnaire version % is % and immutable', OLD.id, OLD.status;
END;
$$;

CREATE TRIGGER questionnaire_version_immutable
    BEFORE UPDATE OR DELETE ON questionnaire_version
    FOR EACH ROW EXECUTE FUNCTION questionnaire_version_guard();

CREATE FUNCTION questionnaire_content_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    version_id uuid;
    version_status text;
BEGIN
    IF TG_TABLE_NAME = 'question_version' THEN
        version_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.questionnaire_version_id
                           ELSE NEW.questionnaire_version_id END;
    ELSE
        SELECT qv.questionnaire_version_id INTO version_id
        FROM question_version qv
        WHERE qv.id = CASE WHEN TG_OP = 'DELETE' THEN OLD.question_version_id
                           ELSE NEW.question_version_id END;
    END IF;
    SELECT status INTO version_status FROM questionnaire_version WHERE id = version_id;
    IF version_status IS NOT NULL AND version_status <> 'DRAFT' THEN
        RAISE EXCEPTION 'questionnaire version % is % and immutable', version_id, version_status;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER question_version_immutable
    BEFORE INSERT OR UPDATE OR DELETE ON question_version
    FOR EACH ROW EXECUTE FUNCTION questionnaire_content_guard();

CREATE TRIGGER question_option_immutable
    BEFORE INSERT OR UPDATE OR DELETE ON question_option
    FOR EACH ROW EXECUTE FUNCTION questionnaire_content_guard();
"""


def _enable_tenant_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
    )


def _grant_app_privileges() -> None:
    op.execute(CREATE_APP_ROLE_SQL)
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    for table, privileges in PRIVILEGES.items():
        op.execute(f"GRANT {privileges} ON {table} TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")


def upgrade() -> None:
    op.create_table(
        "question",
        sa.Column("key", sa.String(length=120), nullable=False),
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
            "key ~ '^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$'", name=op.f("ck_question_key_format")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_question")),
        sa.UniqueConstraint("key", name=op.f("uq_question_key")),
    )
    op.create_table(
        "questionnaire",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("vertical", sa.Text(), nullable=False),
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
        sa.CheckConstraint(
            "key ~ '^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$'",
            name=op.f("ck_questionnaire_key_format"),
        ),
        sa.CheckConstraint(
            "vertical IN ('PLANNING', 'VESSEL', 'BUSINESS', 'GRANT', 'SELL', 'RENT')",
            name=op.f("ck_questionnaire_vertical_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_questionnaire")),
        sa.UniqueConstraint("key", name=op.f("uq_questionnaire_key")),
    )
    op.create_table(
        "questionnaire_version",
        sa.Column("questionnaire_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), server_default="DRAFT", nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("content_hash", sa.LargeBinary(), nullable=False),
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
            name=op.f("ck_questionnaire_version_published_at_when_published"),
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'PUBLISHED', 'RETIRED')",
            name=op.f("ck_questionnaire_version_status_valid"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_questionnaire_version_version_positive")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_questionnaire_version_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["questionnaire_id"],
            ["questionnaire.id"],
            name=op.f("fk_questionnaire_version_questionnaire_id_questionnaire"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_questionnaire_version")),
        sa.UniqueConstraint(
            "questionnaire_id",
            "version",
            name=op.f("uq_questionnaire_version_questionnaire_id_version"),
        ),
    )
    op.create_index(
        "uq_questionnaire_version_published",
        "questionnaire_version",
        ["questionnaire_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PUBLISHED'"),
    )
    op.create_table(
        "address",
        sa.Column("line1", sa.String(length=200), nullable=False),
        sa.Column("line2", sa.String(length=200), nullable=True),
        sa.Column("suburb", sa.String(length=100), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("postcode", sa.String(length=4), nullable=False),
        sa.Column("lga_code", sa.String(length=20), nullable=True),
        sa.Column("gnaf_pid", sa.String(length=30), nullable=True),
        sa.Column("latitude", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("longitude", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("source", sa.Text(), server_default="USER", nullable=False),
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
        sa.CheckConstraint("postcode ~ '^[0-9]{4}$'", name=op.f("ck_address_postcode_format")),
        sa.CheckConstraint("source IN ('USER', 'PROVIDER')", name=op.f("ck_address_source_valid")),
        sa.CheckConstraint(
            "state IN ('NSW', 'VIC', 'QLD', 'SA', 'WA', 'TAS', 'NT', 'ACT')",
            name=op.f("ck_address_state_valid"),
        ),
        sa.CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90",
            name=op.f("ck_address_latitude_range"),
        ),
        sa.CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180",
            name=op.f("ck_address_longitude_range"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_address_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_address_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_address")),
        sa.UniqueConstraint("organisation_id", "id", name=op.f("uq_address_organisation_id_id")),
    )
    op.create_index(
        op.f("ix_address_organisation_id"), "address", ["organisation_id"], unique=False
    )
    op.create_table(
        "question_version",
        sa.Column("questionnaire_version_id", sa.UUID(), nullable=False),
        sa.Column("question_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(length=120), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("label", sa.String(length=300), nullable=False),
        sa.Column("help_text", sa.String(length=1000), nullable=True),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column(
            "validation",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("visible_when", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
            "type IN ('TEXT', 'TEXTAREA', 'NUMBER', 'DECIMAL', 'CURRENCY', 'BOOLEAN', 'SELECT', 'MULTISELECT', 'DATE', 'ADDRESS', 'FILE', 'OBJECT')",
            name=op.f("ck_question_version_type_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["question.id"],
            name=op.f("fk_question_version_question_id_question"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["questionnaire_version_id"],
            ["questionnaire_version.id"],
            name=op.f("fk_question_version_questionnaire_version_id_questionnaire_version"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_question_version")),
        sa.UniqueConstraint(
            "questionnaire_version_id",
            "ordinal",
            name=op.f("uq_question_version_questionnaire_version_id_ordinal"),
        ),
        sa.UniqueConstraint(
            "questionnaire_version_id",
            "question_id",
            name=op.f("uq_question_version_questionnaire_version_id_question_id"),
        ),
    )
    op.create_table(
        "vessel",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("vessel_type", sa.Text(), nullable=False),
        sa.Column("length_m", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("hull_material", sa.String(length=60), nullable=True),
        sa.Column("propulsion", sa.Text(), nullable=True),
        sa.Column("max_passengers", sa.Integer(), nullable=True),
        sa.Column("crew", sa.Integer(), nullable=True),
        sa.Column("operating_area", sa.String(length=200), nullable=True),
        sa.Column("activity", sa.String(length=200), nullable=True),
        sa.Column("uvi", sa.String(length=20), nullable=True),
        sa.Column("hin", sa.String(length=20), nullable=True),
        sa.Column("state_rego", sa.String(length=20), nullable=True),
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
            "propulsion IS NULL OR propulsion IN ('INBOARD', 'OUTBOARD', 'STERNDRIVE', 'JET', 'SAIL', 'SAIL_AUXILIARY', 'MANUAL', 'OTHER')",
            name=op.f("ck_vessel_propulsion_valid"),
        ),
        sa.CheckConstraint(
            "vessel_type IN ('MOTOR', 'SAIL', 'PERSONAL_WATERCRAFT', 'PADDLE', 'BARGE', 'OTHER')",
            name=op.f("ck_vessel_vessel_type_valid"),
        ),
        sa.CheckConstraint("crew IS NULL OR crew >= 0", name=op.f("ck_vessel_crew")),
        sa.CheckConstraint(
            "length_m IS NULL OR (length_m > 0 AND length_m <= 500)", name=op.f("ck_vessel_length")
        ),
        sa.CheckConstraint(
            "max_passengers IS NULL OR max_passengers >= 0", name=op.f("ck_vessel_passengers")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_vessel_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_vessel_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vessel")),
        sa.UniqueConstraint("organisation_id", "id", name=op.f("uq_vessel_organisation_id_id")),
    )
    op.create_index(op.f("ix_vessel_organisation_id"), "vessel", ["organisation_id"], unique=False)
    op.create_table(
        "business_profile",
        sa.Column("legal_name", sa.String(length=200), nullable=False),
        sa.Column("trading_name", sa.String(length=200), nullable=True),
        sa.Column("abn", sa.String(length=11), nullable=True),
        sa.Column("acn", sa.String(length=9), nullable=True),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("gst_registered", sa.Boolean(), nullable=True),
        sa.Column("established_on", sa.Date(), nullable=True),
        sa.Column("employee_band", sa.Text(), nullable=True),
        sa.Column("turnover_band", sa.Text(), nullable=True),
        sa.Column("anzsic_code", sa.String(length=4), nullable=True),
        sa.Column("address_id", sa.UUID(), nullable=True),
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
            "abn IS NULL OR abn ~ '^[0-9]{11}$'", name=op.f("ck_business_profile_abn_format")
        ),
        sa.CheckConstraint(
            "acn IS NULL OR acn ~ '^[0-9]{9}$'", name=op.f("ck_business_profile_acn_format")
        ),
        sa.CheckConstraint(
            "anzsic_code IS NULL OR anzsic_code ~ '^[0-9]{1,4}$'",
            name=op.f("ck_business_profile_anzsic"),
        ),
        sa.CheckConstraint(
            "employee_band IS NULL OR employee_band IN ('NONE', '1_4', '5_19', '20_199', '200_PLUS')",
            name=op.f("ck_business_profile_employee_band_valid"),
        ),
        sa.CheckConstraint(
            "entity_type IN ('SOLE_TRADER', 'PARTNERSHIP', 'COMPANY', 'TRUST', 'INCORPORATED_ASSOCIATION', 'COOPERATIVE', 'OTHER')",
            name=op.f("ck_business_profile_entity_type_valid"),
        ),
        sa.CheckConstraint(
            "turnover_band IS NULL OR turnover_band IN ('UNDER_75K', '75K_2M', '2M_10M', '10M_50M', 'OVER_50M')",
            name=op.f("ck_business_profile_turnover_band_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_business_profile_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "address_id"],
            ["address.organisation_id", "address.id"],
            name=op.f("fk_business_profile_organisation_id_address"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_business_profile_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_business_profile")),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_business_profile_organisation_id_id")
        ),
    )
    op.create_index(
        op.f("ix_business_profile_organisation_id"),
        "business_profile",
        ["organisation_id"],
        unique=False,
    )
    op.create_table(
        "property",
        sa.Column("address_id", sa.UUID(), nullable=False),
        sa.Column("lot_plan", sa.String(length=50), nullable=True),
        sa.Column("title_reference", sa.String(length=50), nullable=True),
        sa.Column("land_area_m2", sa.Numeric(precision=12, scale=2), nullable=True),
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
            "land_area_m2 IS NULL OR land_area_m2 > 0", name=op.f("ck_property_land_area_positive")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_property_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "address_id"],
            ["address.organisation_id", "address.id"],
            name=op.f("fk_property_organisation_id_address"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_property_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_property")),
        sa.UniqueConstraint("organisation_id", "id", name=op.f("uq_property_organisation_id_id")),
    )
    op.create_index(
        op.f("ix_property_organisation_id"), "property", ["organisation_id"], unique=False
    )
    op.create_table(
        "question_option",
        sa.Column("question_version_id", sa.UUID(), nullable=False),
        sa.Column("value", sa.String(length=100), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["question_version_id"],
            ["question_version.id"],
            name=op.f("fk_question_option_question_version_id_question_version"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_question_option")),
        sa.UniqueConstraint(
            "question_version_id",
            "ordinal",
            name=op.f("uq_question_option_question_version_id_ordinal"),
        ),
        sa.UniqueConstraint(
            "question_version_id",
            "value",
            name=op.f("uq_question_option_question_version_id_value"),
        ),
    )
    op.create_table(
        "project",
        sa.Column("vertical", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("status", sa.Text(), server_default="DRAFT", nullable=False),
        sa.Column("reference_code", sa.String(length=12), nullable=False),
        sa.Column("property_id", sa.UUID(), nullable=True),
        sa.Column("vessel_id", sa.UUID(), nullable=True),
        sa.Column("business_profile_id", sa.UUID(), nullable=True),
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
            "status IN ('DRAFT', 'IN_PROGRESS', 'ASSESSED', 'IN_REVIEW', 'COMPLETED', 'ARCHIVED')",
            name=op.f("ck_project_status_valid"),
        ),
        sa.CheckConstraint(
            "vertical IN ('PLANNING', 'VESSEL', 'BUSINESS', 'GRANT', 'SELL', 'RENT')",
            name=op.f("ck_project_vertical_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_project_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "business_profile_id"],
            ["business_profile.organisation_id", "business_profile.id"],
            name=op.f("fk_project_organisation_id_business_profile"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "property_id"],
            ["property.organisation_id", "property.id"],
            name=op.f("fk_project_organisation_id_property"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "vessel_id"],
            ["vessel.organisation_id", "vessel.id"],
            name=op.f("fk_project_organisation_id_vessel"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_project_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project")),
        sa.UniqueConstraint("organisation_id", "id", name=op.f("uq_project_organisation_id_id")),
        sa.UniqueConstraint("reference_code", name=op.f("uq_project_reference_code")),
    )
    op.create_index(
        op.f("ix_project_organisation_id"), "project", ["organisation_id"], unique=False
    )
    op.create_index(
        "ix_project_organisation_id_updated_at",
        "project",
        ["organisation_id", "updated_at"],
        unique=False,
    )
    op.create_table(
        "property_ownership",
        sa.Column("property_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("verified_at", sa.Date(), nullable=True),
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
            "role IN ('OWNER', 'AUTHORISED_AGENT', 'LANDLORD', 'PROSPECTIVE_BUYER', 'LESSEE')",
            name=op.f("ck_property_ownership_role_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_property_ownership_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "property_id"],
            ["property.organisation_id", "property.id"],
            name=op.f("fk_property_ownership_organisation_id_property"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_property_ownership_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_property_ownership")),
        sa.UniqueConstraint(
            "organisation_id",
            "property_id",
            "role",
            name=op.f("uq_property_ownership_organisation_id_property_id_role"),
        ),
    )
    op.create_index(
        op.f("ix_property_ownership_organisation_id"),
        "property_ownership",
        ["organisation_id"],
        unique=False,
    )
    op.create_table(
        "project_status_event",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN ('DRAFT', 'IN_PROGRESS', 'ASSESSED', 'IN_REVIEW', 'COMPLETED', 'ARCHIVED')",
            name=op.f("ck_project_status_event_from_status_valid"),
        ),
        sa.CheckConstraint(
            "to_status IN ('DRAFT', 'IN_PROGRESS', 'ASSESSED', 'IN_REVIEW', 'COMPLETED', 'ARCHIVED')",
            name=op.f("ck_project_status_event_to_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["app_user.id"],
            name=op.f("fk_project_status_event_actor_id_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "project_id"],
            ["project.organisation_id", "project.id"],
            name=op.f("fk_project_status_event_organisation_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_project_status_event_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_status_event")),
    )
    op.create_index(
        op.f("ix_project_status_event_organisation_id"),
        "project_status_event",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_status_event_project_id", "project_status_event", ["project_id"], unique=False
    )
    op.create_table(
        "questionnaire_submission",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("questionnaire_version_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.Text(), server_default="IN_PROGRESS", nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_by", sa.UUID(), nullable=True),
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
            "(status = 'SUBMITTED') = (submitted_at IS NOT NULL)",
            name=op.f("ck_questionnaire_submission_submitted_at_when_submitted"),
        ),
        sa.CheckConstraint(
            "status IN ('IN_PROGRESS', 'SUBMITTED')",
            name=op.f("ck_questionnaire_submission_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_questionnaire_submission_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "project_id"],
            ["project.organisation_id", "project.id"],
            name=op.f("fk_questionnaire_submission_organisation_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_questionnaire_submission_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["questionnaire_version_id"],
            ["questionnaire_version.id"],
            name=op.f("fk_questionnaire_submission_questionnaire_version_id_questionnaire_version"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"],
            ["app_user.id"],
            name=op.f("fk_questionnaire_submission_submitted_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_questionnaire_submission")),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_questionnaire_submission_organisation_id_id")
        ),
    )
    op.create_index(
        op.f("ix_questionnaire_submission_organisation_id"),
        "questionnaire_submission",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        "ix_questionnaire_submission_project_id",
        "questionnaire_submission",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_questionnaire_submission_questionnaire_version_id"),
        "questionnaire_submission",
        ["questionnaire_version_id"],
        unique=False,
    )
    op.create_table(
        "task",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("notes", sa.String(length=2000), nullable=True),
        sa.Column("status", sa.Text(), server_default="OPEN", nullable=False),
        sa.Column("source", sa.Text(), server_default="USER", nullable=False),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("assignee_user_id", sa.UUID(), nullable=True),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "(status = 'DONE') = (completed_at IS NOT NULL)",
            name=op.f("ck_task_completed_when_done"),
        ),
        sa.CheckConstraint(
            "source IN ('USER', 'RULE', 'REVIEWER')", name=op.f("ck_task_source_valid")
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'DONE', 'CANCELLED')", name=op.f("ck_task_status_valid")
        ),
        sa.ForeignKeyConstraint(
            ["assignee_user_id"],
            ["app_user.id"],
            name=op.f("fk_task_assignee_user_id_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_task_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "project_id"],
            ["project.organisation_id", "project.id"],
            name=op.f("fk_task_organisation_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_task_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task")),
        sa.UniqueConstraint("organisation_id", "id", name=op.f("uq_task_organisation_id_id")),
    )
    op.create_index(op.f("ix_task_organisation_id"), "task", ["organisation_id"], unique=False)
    op.create_index("ix_task_project_id", "task", ["project_id"], unique=False)
    op.create_table(
        "question_response",
        sa.Column("submission_id", sa.UUID(), nullable=False),
        sa.Column("question_version_id", sa.UUID(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("answered_by", sa.UUID(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["answered_by"],
            ["app_user.id"],
            name=op.f("fk_question_response_answered_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "submission_id"],
            ["questionnaire_submission.organisation_id", "questionnaire_submission.id"],
            name=op.f("fk_question_response_organisation_id_questionnaire_submission"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_question_response_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["question_version_id"],
            ["question_version.id"],
            name=op.f("fk_question_response_question_version_id_question_version"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_question_response")),
        sa.UniqueConstraint(
            "submission_id",
            "question_version_id",
            name=op.f("uq_question_response_submission_id_question_version_id"),
        ),
    )
    op.create_index(
        op.f("ix_question_response_organisation_id"),
        "question_response",
        ["organisation_id"],
        unique=False,
    )
    op.create_table(
        "reminder",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=True),
        sa.Column("recipient_user_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("fires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="SCHEDULED", nullable=False),
        sa.Column("recurrence", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
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
            "channel IN ('EMAIL', 'IN_APP')", name=op.f("ck_reminder_channel_valid")
        ),
        sa.CheckConstraint(
            "recurrence IS NULL OR recurrence IN ('WEEKLY', 'MONTHLY', 'YEARLY')",
            name=op.f("ck_reminder_recurrence_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('SCHEDULED', 'SENT', 'CANCELLED')", name=op.f("ck_reminder_status_valid")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_reminder_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "project_id"],
            ["project.organisation_id", "project.id"],
            name=op.f("fk_reminder_organisation_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "task_id"],
            ["task.organisation_id", "task.id"],
            name=op.f("fk_reminder_organisation_id_task"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_reminder_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"],
            ["app_user.id"],
            name=op.f("fk_reminder_recipient_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reminder")),
    )
    op.create_index(
        "ix_reminder_due",
        "reminder",
        ["fires_at"],
        unique=False,
        postgresql_where=sa.text("status = 'SCHEDULED'"),
    )
    op.create_index(
        op.f("ix_reminder_organisation_id"), "reminder", ["organisation_id"], unique=False
    )
    op.create_index("ix_reminder_project_id", "reminder", ["project_id"], unique=False)

    for table in TENANT_TABLES:
        _enable_tenant_rls(table)
    op.execute(QUESTIONNAIRE_IMMUTABLE_SQL)
    _grant_app_privileges()


def downgrade() -> None:
    # Revokes this database's privileges (incl. on 0001/0002 tables); the role itself is a
    # cluster object shared with the login role's membership, so it is kept.
    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                EXECUTE 'DROP OWNED BY {APP_ROLE}';
            END IF;
        END
        $$;
    """)
    op.drop_index("ix_reminder_project_id", table_name="reminder")
    op.drop_index(op.f("ix_reminder_organisation_id"), table_name="reminder")
    op.drop_index(
        "ix_reminder_due", table_name="reminder", postgresql_where=sa.text("status = 'SCHEDULED'")
    )
    op.drop_table("reminder")
    op.drop_index(op.f("ix_question_response_organisation_id"), table_name="question_response")
    op.drop_table("question_response")
    op.drop_index("ix_task_project_id", table_name="task")
    op.drop_index(op.f("ix_task_organisation_id"), table_name="task")
    op.drop_table("task")
    op.drop_index(
        op.f("ix_questionnaire_submission_questionnaire_version_id"),
        table_name="questionnaire_submission",
    )
    op.drop_index("ix_questionnaire_submission_project_id", table_name="questionnaire_submission")
    op.drop_index(
        op.f("ix_questionnaire_submission_organisation_id"), table_name="questionnaire_submission"
    )
    op.drop_table("questionnaire_submission")
    op.drop_index("ix_project_status_event_project_id", table_name="project_status_event")
    op.drop_index(
        op.f("ix_project_status_event_organisation_id"), table_name="project_status_event"
    )
    op.drop_table("project_status_event")
    op.drop_index(op.f("ix_property_ownership_organisation_id"), table_name="property_ownership")
    op.drop_table("property_ownership")
    op.drop_index("ix_project_organisation_id_updated_at", table_name="project")
    op.drop_index(op.f("ix_project_organisation_id"), table_name="project")
    op.drop_table("project")
    op.drop_table("question_option")
    op.drop_index(op.f("ix_property_organisation_id"), table_name="property")
    op.drop_table("property")
    op.drop_index(op.f("ix_business_profile_organisation_id"), table_name="business_profile")
    op.drop_table("business_profile")
    op.drop_index(op.f("ix_vessel_organisation_id"), table_name="vessel")
    op.drop_table("vessel")
    op.drop_table("question_version")
    op.drop_index(op.f("ix_address_organisation_id"), table_name="address")
    op.drop_table("address")
    op.drop_index(
        "uq_questionnaire_version_published",
        table_name="questionnaire_version",
        postgresql_where=sa.text("status = 'PUBLISHED'"),
    )
    op.drop_table("questionnaire_version")
    op.drop_table("questionnaire")
    op.drop_table("question")
    op.execute("DROP FUNCTION IF EXISTS questionnaire_content_guard()")
    op.execute("DROP FUNCTION IF EXISTS questionnaire_version_guard()")
