"""PropertyReady (Milestone 11): SellReady, RentReady, notifications and reminder delivery.

* SellReady (tenant): ``sale_project`` (one per SELL project: lifecycle, disclosure given),
  ``sale_document`` (the vault: the project's uploads filed by category), ``sale_offer``
  and ``sale_enquiry``.
* RentReady (tenant): ``rental_property`` (one per RENT project: details and listing),
  ``tenant_application`` (objective checks only, no scores), ``tenancy``, ``inspection``,
  ``inspection_item`` and ``maintenance_item``.
* ``notification`` (tenant): what a member is told in the app and by email, with a
  ``dedupe_key`` so scheduled jobs never repeat themselves.
* ``reminder``: delivered by the scheduler now. System reminders kept in step with a date
  (``source_key``) may have no project (a vessel certificate), and carry a body and a link.
* ``due_reminders(n)`` and ``grant_alert_projects(programs, statuses)``: SECURITY DEFINER
  functions returning ids only, so the scheduler can find work across organisations
  without the application role reading other tenants' rows.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "approvalready_rw"

# Privileges of the application role on the new tables (tests/test_rls.py keeps the map).
PRIVILEGES: dict[str, str] = {
    "sale_project": "SELECT, INSERT, UPDATE",
    "sale_document": "SELECT, INSERT, UPDATE, DELETE",
    "sale_offer": "SELECT, INSERT, UPDATE",
    "sale_enquiry": "SELECT, INSERT, UPDATE",
    "rental_property": "SELECT, INSERT, UPDATE",
    "tenant_application": "SELECT, INSERT, UPDATE",
    "tenancy": "SELECT, INSERT, UPDATE",
    "inspection": "SELECT, INSERT, UPDATE",
    "inspection_item": "SELECT, INSERT, UPDATE, DELETE",
    "maintenance_item": "SELECT, INSERT, UPDATE",
    "notification": "SELECT, INSERT, UPDATE",
}

TENANT_TABLES = tuple(PRIVILEGES)

TENANT_PREDICATE = "organisation_id = nullif(current_setting('app.current_org', true), '')::uuid"

# Ids only, enough to bind the tenant and deliver; owned by the schema owner, so they read
# past row-level security.
FUNCTIONS = (
    """
CREATE FUNCTION due_reminders(max_rows integer)
RETURNS TABLE (id uuid, organisation_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT r.id, r.organisation_id FROM reminder r
     WHERE r.status = 'SCHEDULED' AND r.fires_at <= now()
     ORDER BY r.fires_at
     LIMIT least(greatest(max_rows, 1), 1000)
$$;
REVOKE ALL ON FUNCTION due_reminders(integer) FROM PUBLIC;
""",
    """
CREATE FUNCTION grant_alert_projects(programs uuid[], statuses text[])
RETURNS TABLE (organisation_id uuid, project_id uuid, program_id uuid, created_by uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT p.organisation_id, p.id, m.program_id, p.created_by
      FROM project p
      JOIN LATERAL (
            SELECT a.id FROM assessment a
             WHERE a.project_id = p.id ORDER BY a.created_at DESC LIMIT 1
           ) latest ON true
      JOIN grant_match m ON m.assessment_id = latest.id
     WHERE p.vertical = 'GRANT' AND p.deleted_at IS NULL AND p.status <> 'ARCHIVED'
       AND m.program_id = ANY(programs) AND m.status = ANY(statuses)
     LIMIT 5000
$$;
REVOKE ALL ON FUNCTION grant_alert_projects(uuid[], text[]) FROM PUBLIC;
""",
)


def upgrade() -> None:
    op.create_table(
        "rental_property",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("bedrooms", sa.Integer(), nullable=True),
        sa.Column("bathrooms", sa.Integer(), nullable=True),
        sa.Column("parking", sa.Integer(), nullable=True),
        sa.Column("furnished", sa.Boolean(), nullable=True),
        sa.Column("pets_considered", sa.Boolean(), nullable=True),
        sa.Column("listing_status", sa.Text(), server_default="NOT_LISTED", nullable=False),
        sa.Column("headline", sa.String(length=200), nullable=True),
        sa.Column("description", sa.String(length=4000), nullable=True),
        sa.Column("rent_cents", sa.BigInteger(), nullable=True),
        sa.Column("rent_period", sa.Text(), server_default="WEEK", nullable=False),
        sa.Column("available_from", sa.Date(), nullable=True),
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
            "listing_status <> 'ADVERTISED' OR rent_cents IS NOT NULL",
            name=op.f("ck_rental_property_advertised_rent"),
        ),
        sa.CheckConstraint(
            "listing_status IN ('NOT_LISTED', 'ADVERTISED', 'LEASED', 'WITHDRAWN')",
            name=op.f("ck_rental_property_listing_status_valid"),
        ),
        sa.CheckConstraint(
            "bathrooms IS NULL OR bathrooms BETWEEN 0 AND 30",
            name=op.f("ck_rental_property_bathrooms"),
        ),
        sa.CheckConstraint(
            "bedrooms IS NULL OR bedrooms BETWEEN 0 AND 30",
            name=op.f("ck_rental_property_bedrooms"),
        ),
        sa.CheckConstraint(
            "parking IS NULL OR parking BETWEEN 0 AND 30", name=op.f("ck_rental_property_parking")
        ),
        sa.CheckConstraint(
            "rent_cents IS NULL OR rent_cents > 0", name=op.f("ck_rental_property_rent_positive")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_rental_property_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "project_id"],
            ["project.organisation_id", "project.id"],
            name=op.f("fk_rental_property_organisation_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_rental_property_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rental_property")),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_rental_property_organisation_id_id")
        ),
        sa.UniqueConstraint("project_id", name=op.f("uq_rental_property_project_id")),
    )
    op.create_index(
        op.f("ix_rental_property_organisation_id"),
        "rental_property",
        ["organisation_id"],
        unique=False,
    )
    op.create_table(
        "sale_project",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.Text(), server_default="PREPARING", nullable=False),
        sa.Column("asking_price_cents", sa.BigInteger(), nullable=True),
        sa.Column("price_guide", sa.String(length=200), nullable=True),
        sa.Column("listed_on", sa.Date(), nullable=True),
        sa.Column("contract_on", sa.Date(), nullable=True),
        sa.Column("settlement_on", sa.Date(), nullable=True),
        sa.Column("disclosure_given_on", sa.Date(), nullable=True),
        sa.Column("disclosure_given_to", sa.String(length=200), nullable=True),
        sa.Column(
            "disclosure_document_ids",
            postgresql.ARRAY(sa.UUID()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("disclosure_not_needed_note", sa.String(length=1000), nullable=True),
        sa.Column("notes", sa.String(length=2000), nullable=True),
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
            "status IN ('PREPARING', 'READY_TO_LIST', 'LISTED', 'UNDER_OFFER', 'UNDER_CONTRACT', 'SETTLED', 'WITHDRAWN')",
            name=op.f("ck_sale_project_status_valid"),
        ),
        sa.CheckConstraint(
            "(disclosure_given_on IS NULL) = (disclosure_given_to IS NULL)",
            name=op.f("ck_sale_project_disclosure_given_together"),
        ),
        sa.CheckConstraint(
            "asking_price_cents IS NULL OR asking_price_cents >= 0",
            name=op.f("ck_sale_project_price"),
        ),
        sa.CheckConstraint(
            "settlement_on IS NULL OR contract_on IS NULL OR settlement_on >= contract_on",
            name=op.f("ck_sale_project_settles_after_contract"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_sale_project_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "project_id"],
            ["project.organisation_id", "project.id"],
            name=op.f("fk_sale_project_organisation_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_sale_project_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sale_project")),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_sale_project_organisation_id_id")
        ),
        sa.UniqueConstraint("project_id", name=op.f("uq_sale_project_project_id")),
    )
    op.create_index(
        op.f("ix_sale_project_organisation_id"), "sale_project", ["organisation_id"], unique=False
    )
    op.create_table(
        "sale_document",
        sa.Column("sale_id", sa.UUID(), nullable=False),
        sa.Column("uploaded_document_id", sa.UUID(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("in_disclosure", sa.Boolean(), server_default="false", nullable=False),
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
            "category IN ('DISCLOSURE_STATEMENT', 'TITLE_SEARCH', 'REGISTERED_PLAN', 'BODY_CORPORATE', 'POOL_SAFETY', 'SMOKE_ALARMS', 'BUILDING_APPROVAL', 'RATES_AND_WATER', 'PLANNING_AND_ZONING', 'TENANCY', 'CONTRACT', 'OTHER')",
            name=op.f("ck_sale_document_category_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_sale_document_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "sale_id"],
            ["sale_project.organisation_id", "sale_project.id"],
            name=op.f("fk_sale_document_organisation_id_sale_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "uploaded_document_id"],
            ["uploaded_document.organisation_id", "uploaded_document.id"],
            name=op.f("fk_sale_document_organisation_id_uploaded_document"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_sale_document_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sale_document")),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_sale_document_organisation_id_id")
        ),
        sa.UniqueConstraint(
            "sale_id",
            "uploaded_document_id",
            name=op.f("uq_sale_document_sale_id_uploaded_document_id"),
        ),
    )
    op.create_index(
        op.f("ix_sale_document_organisation_id"), "sale_document", ["organisation_id"], unique=False
    )
    op.create_index("ix_sale_document_sale_id", "sale_document", ["sale_id"], unique=False)
    op.create_table(
        "sale_enquiry",
        sa.Column("sale_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("contact", sa.String(length=200), nullable=True),
        sa.Column("channel", sa.String(length=60), nullable=True),
        sa.Column("message", sa.String(length=2000), nullable=True),
        sa.Column("status", sa.Text(), server_default="NEW", nullable=False),
        sa.Column("received_on", sa.Date(), nullable=False),
        sa.Column("notes", sa.String(length=2000), nullable=True),
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
            "status IN ('NEW', 'RESPONDED', 'CLOSED')", name=op.f("ck_sale_enquiry_status_valid")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_sale_enquiry_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "sale_id"],
            ["sale_project.organisation_id", "sale_project.id"],
            name=op.f("fk_sale_enquiry_organisation_id_sale_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_sale_enquiry_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sale_enquiry")),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_sale_enquiry_organisation_id_id")
        ),
    )
    op.create_index(
        op.f("ix_sale_enquiry_organisation_id"), "sale_enquiry", ["organisation_id"], unique=False
    )
    op.create_index("ix_sale_enquiry_sale_id", "sale_enquiry", ["sale_id"], unique=False)
    op.create_table(
        "sale_offer",
        sa.Column("sale_id", sa.UUID(), nullable=False),
        sa.Column("buyer_name", sa.String(length=200), nullable=False),
        sa.Column("buyer_contact", sa.String(length=200), nullable=True),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("deposit_cents", sa.BigInteger(), nullable=True),
        sa.Column("subject_to_finance", sa.Boolean(), nullable=False),
        sa.Column("subject_to_inspection", sa.Boolean(), nullable=False),
        sa.Column("settlement_days", sa.Integer(), nullable=True),
        sa.Column("conditions", sa.String(length=2000), nullable=True),
        sa.Column("status", sa.Text(), server_default="RECEIVED", nullable=False),
        sa.Column("received_on", sa.Date(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('RECEIVED', 'COUNTERED', 'ACCEPTED', 'REJECTED', 'WITHDRAWN', 'LAPSED')",
            name=op.f("ck_sale_offer_status_valid"),
        ),
        sa.CheckConstraint("amount_cents > 0", name=op.f("ck_sale_offer_amount_positive")),
        sa.CheckConstraint(
            "settlement_days IS NULL OR settlement_days BETWEEN 0 AND 730",
            name=op.f("ck_sale_offer_settlement_days"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_sale_offer_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "sale_id"],
            ["sale_project.organisation_id", "sale_project.id"],
            name=op.f("fk_sale_offer_organisation_id_sale_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_sale_offer_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sale_offer")),
        sa.UniqueConstraint("organisation_id", "id", name=op.f("uq_sale_offer_organisation_id_id")),
    )
    op.create_index(
        op.f("ix_sale_offer_organisation_id"), "sale_offer", ["organisation_id"], unique=False
    )
    op.create_index("ix_sale_offer_sale_id", "sale_offer", ["sale_id"], unique=False)
    op.create_index(
        "uq_sale_offer_one_accepted",
        "sale_offer",
        ["sale_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACCEPTED' AND deleted_at IS NULL"),
    )
    op.create_table(
        "tenant_application",
        sa.Column("rental_id", sa.UUID(), nullable=False),
        sa.Column("applicant_name", sa.String(length=200), nullable=False),
        sa.Column("applicant_contact", sa.String(length=200), nullable=True),
        sa.Column("household_size", sa.Integer(), nullable=True),
        sa.Column("preferred_start_on", sa.Date(), nullable=True),
        sa.Column("received_on", sa.Date(), nullable=False),
        sa.Column("status", sa.Text(), server_default="RECEIVED", nullable=False),
        sa.Column("checks", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("notes", sa.String(length=2000), nullable=True),
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
            "jsonb_typeof(checks) = 'object'", name=op.f("ck_tenant_application_checks_object")
        ),
        sa.CheckConstraint(
            "status IN ('RECEIVED', 'SHORTLISTED', 'APPROVED', 'DECLINED', 'WITHDRAWN')",
            name=op.f("ck_tenant_application_status_valid"),
        ),
        sa.CheckConstraint(
            "household_size IS NULL OR household_size BETWEEN 1 AND 30",
            name=op.f("ck_tenant_application_household"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_tenant_application_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "rental_id"],
            ["rental_property.organisation_id", "rental_property.id"],
            name=op.f("fk_tenant_application_organisation_id_rental_property"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_tenant_application_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant_application")),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_tenant_application_organisation_id_id")
        ),
    )
    op.create_index(
        op.f("ix_tenant_application_organisation_id"),
        "tenant_application",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        "ix_tenant_application_rental_id", "tenant_application", ["rental_id"], unique=False
    )
    op.create_table(
        "tenancy",
        sa.Column("rental_id", sa.UUID(), nullable=False),
        sa.Column("application_id", sa.UUID(), nullable=True),
        sa.Column("tenant_names", sa.String(length=300), nullable=False),
        sa.Column("tenant_contact", sa.String(length=200), nullable=True),
        sa.Column("start_on", sa.Date(), nullable=False),
        sa.Column("end_on", sa.Date(), nullable=True),
        sa.Column("rent_cents", sa.BigInteger(), nullable=False),
        sa.Column("rent_period", sa.Text(), nullable=False),
        sa.Column("bond_cents", sa.BigInteger(), nullable=True),
        sa.Column("bond_lodged_on", sa.Date(), nullable=True),
        sa.Column("bond_reference", sa.String(length=60), nullable=True),
        sa.Column("last_rent_increase_on", sa.Date(), nullable=True),
        sa.Column("next_rent_review_on", sa.Date(), nullable=True),
        sa.Column("ended_on", sa.Date(), nullable=True),
        sa.Column("notes", sa.String(length=2000), nullable=True),
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
            "rent_period IN ('WEEK', 'FORTNIGHT', 'MONTH')",
            name=op.f("ck_tenancy_rent_period_valid"),
        ),
        sa.CheckConstraint("bond_cents IS NULL OR bond_cents >= 0", name=op.f("ck_tenancy_bond")),
        sa.CheckConstraint(
            "end_on IS NULL OR end_on >= start_on", name=op.f("ck_tenancy_ends_after_start")
        ),
        sa.CheckConstraint(
            "ended_on IS NULL OR ended_on >= start_on", name=op.f("ck_tenancy_ended_after_start")
        ),
        sa.CheckConstraint("rent_cents > 0", name=op.f("ck_tenancy_rent_positive")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_tenancy_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "application_id"],
            ["tenant_application.organisation_id", "tenant_application.id"],
            name=op.f("fk_tenancy_organisation_id_tenant_application"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "rental_id"],
            ["rental_property.organisation_id", "rental_property.id"],
            name=op.f("fk_tenancy_organisation_id_rental_property"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_tenancy_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenancy")),
        sa.UniqueConstraint("organisation_id", "id", name=op.f("uq_tenancy_organisation_id_id")),
    )
    op.create_index(
        op.f("ix_tenancy_organisation_id"), "tenancy", ["organisation_id"], unique=False
    )
    op.create_index("ix_tenancy_rental_id", "tenancy", ["rental_id"], unique=False)
    op.create_table(
        "inspection",
        sa.Column("rental_id", sa.UUID(), nullable=False),
        sa.Column("tenancy_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="SCHEDULED", nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.String(length=2000), nullable=True),
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
            "(status = 'COMPLETED') = (completed_at IS NOT NULL)",
            name=op.f("ck_inspection_completed_when_done"),
        ),
        sa.CheckConstraint(
            "kind IN ('ENTRY', 'ROUTINE', 'EXIT')", name=op.f("ck_inspection_kind_valid")
        ),
        sa.CheckConstraint(
            "status IN ('SCHEDULED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')",
            name=op.f("ck_inspection_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_inspection_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "rental_id"],
            ["rental_property.organisation_id", "rental_property.id"],
            name=op.f("fk_inspection_organisation_id_rental_property"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "tenancy_id"],
            ["tenancy.organisation_id", "tenancy.id"],
            name=op.f("fk_inspection_organisation_id_tenancy"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_inspection_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inspection")),
        sa.UniqueConstraint("organisation_id", "id", name=op.f("uq_inspection_organisation_id_id")),
    )
    op.create_index(
        op.f("ix_inspection_organisation_id"), "inspection", ["organisation_id"], unique=False
    )
    op.create_index("ix_inspection_rental_id", "inspection", ["rental_id"], unique=False)
    op.create_table(
        "maintenance_item",
        sa.Column("rental_id", sa.UUID(), nullable=False),
        sa.Column("tenancy_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("detail", sa.String(length=2000), nullable=True),
        sa.Column("priority", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="REPORTED", nullable=False),
        sa.Column("reported_on", sa.Date(), nullable=False),
        sa.Column("reported_by", sa.String(length=200), nullable=True),
        sa.Column("scheduled_on", sa.Date(), nullable=True),
        sa.Column("resolved_on", sa.Date(), nullable=True),
        sa.Column("tradesperson", sa.String(length=200), nullable=True),
        sa.Column("cost_cents", sa.BigInteger(), nullable=True),
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
            "(status = 'DONE') = (resolved_on IS NOT NULL)",
            name=op.f("ck_maintenance_item_resolved_when_done"),
        ),
        sa.CheckConstraint(
            "priority IN ('EMERGENCY', 'URGENT', 'ROUTINE')",
            name=op.f("ck_maintenance_item_priority_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('REPORTED', 'SCHEDULED', 'IN_PROGRESS', 'DONE', 'CANCELLED')",
            name=op.f("ck_maintenance_item_status_valid"),
        ),
        sa.CheckConstraint(
            "cost_cents IS NULL OR cost_cents >= 0", name=op.f("ck_maintenance_item_cost")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_maintenance_item_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "rental_id"],
            ["rental_property.organisation_id", "rental_property.id"],
            name=op.f("fk_maintenance_item_organisation_id_rental_property"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "tenancy_id"],
            ["tenancy.organisation_id", "tenancy.id"],
            name=op.f("fk_maintenance_item_organisation_id_tenancy"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_maintenance_item_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_maintenance_item")),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_maintenance_item_organisation_id_id")
        ),
    )
    op.create_index(
        op.f("ix_maintenance_item_organisation_id"),
        "maintenance_item",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        "ix_maintenance_item_rental_id", "maintenance_item", ["rental_id"], unique=False
    )
    op.create_table(
        "inspection_item",
        sa.Column("inspection_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("room", sa.String(length=100), nullable=False),
        sa.Column("item", sa.String(length=100), nullable=False),
        sa.Column("condition", sa.Text(), nullable=True),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.Column(
            "photo_document_ids", postgresql.ARRAY(sa.UUID()), server_default="{}", nullable=False
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
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "condition IS NULL OR condition IN ('GOOD', 'FAIR', 'POOR', 'DAMAGED', 'NOT_APPLICABLE')",
            name=op.f("ck_inspection_item_condition_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "inspection_id"],
            ["inspection.organisation_id", "inspection.id"],
            name=op.f("fk_inspection_item_organisation_id_inspection"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_inspection_item_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inspection_item")),
        sa.UniqueConstraint(
            "inspection_id", "room", "item", name=op.f("uq_inspection_item_inspection_id_room_item")
        ),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_inspection_item_organisation_id_id")
        ),
    )
    op.create_index(
        "ix_inspection_item_inspection_id",
        "inspection_item",
        ["inspection_id", "position"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inspection_item_organisation_id"),
        "inspection_item",
        ["organisation_id"],
        unique=False,
    )
    op.create_table(
        "notification",
        sa.Column("recipient_user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.String(length=1000), nullable=True),
        sa.Column("link_path", sa.String(length=300), nullable=True),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("reminder_id", sa.UUID(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=200), nullable=True),
        sa.Column("email_status", sa.Text(), nullable=False),
        sa.Column("emailed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "email_status IN ('NOT_REQUESTED', 'PENDING', 'SENT', 'FAILED')",
            name=op.f("ck_notification_email_status_valid"),
        ),
        sa.CheckConstraint(
            "kind IN ('REMINDER', 'GRANT_ROUND', 'SOURCES_DUE')",
            name=op.f("ck_notification_kind_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "project_id"],
            ["project.organisation_id", "project.id"],
            name=op.f("fk_notification_organisation_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_notification_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"],
            ["app_user.id"],
            name=op.f("fk_notification_recipient_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification")),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_notification_organisation_id_id")
        ),
    )
    op.create_index(
        op.f("ix_notification_organisation_id"), "notification", ["organisation_id"], unique=False
    )
    op.create_index(
        "ix_notification_recipient",
        "notification",
        ["recipient_user_id", "organisation_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_notification_dedupe",
        "notification",
        ["organisation_id", "recipient_user_id", "dedupe_key"],
        unique=True,
        postgresql_where=sa.text("dedupe_key IS NOT NULL"),
    )
    op.add_column("reminder", sa.Column("source_key", sa.String(length=200), nullable=True))
    op.add_column("reminder", sa.Column("body", sa.String(length=1000), nullable=True))
    op.add_column("reminder", sa.Column("link_path", sa.String(length=300), nullable=True))
    op.alter_column("reminder", "project_id", existing_type=sa.UUID(), nullable=True)
    op.create_index(
        "ix_reminder_source_key", "reminder", ["organisation_id", "source_key"], unique=False
    )
    op.create_check_constraint(
        op.f("ck_reminder_project_or_system"),
        "reminder",
        "project_id IS NOT NULL OR source_key IS NOT NULL",
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
    for sql in FUNCTIONS:
        op.execute(sql)
    op.execute(f"GRANT EXECUTE ON FUNCTION due_reminders(integer) TO {APP_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION grant_alert_projects(uuid[], text[]) TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS grant_alert_projects(uuid[], text[])")
    op.execute("DROP FUNCTION IF EXISTS due_reminders(integer)")
    # System reminders without a project can't survive the NOT NULL coming back.
    op.execute("DELETE FROM reminder WHERE project_id IS NULL")
    op.drop_constraint(op.f("ck_reminder_project_or_system"), "reminder", type_="check")
    op.drop_index("ix_reminder_source_key", table_name="reminder")
    op.alter_column("reminder", "project_id", existing_type=sa.UUID(), nullable=False)
    op.drop_column("reminder", "link_path")
    op.drop_column("reminder", "body")
    op.drop_column("reminder", "source_key")
    op.drop_index(
        "uq_notification_dedupe",
        table_name="notification",
        postgresql_where=sa.text("dedupe_key IS NOT NULL"),
    )
    op.drop_index("ix_notification_recipient", table_name="notification")
    op.drop_index(op.f("ix_notification_organisation_id"), table_name="notification")
    op.drop_table("notification")
    op.drop_index(op.f("ix_inspection_item_organisation_id"), table_name="inspection_item")
    op.drop_index("ix_inspection_item_inspection_id", table_name="inspection_item")
    op.drop_table("inspection_item")
    op.drop_index("ix_maintenance_item_rental_id", table_name="maintenance_item")
    op.drop_index(op.f("ix_maintenance_item_organisation_id"), table_name="maintenance_item")
    op.drop_table("maintenance_item")
    op.drop_index("ix_inspection_rental_id", table_name="inspection")
    op.drop_index(op.f("ix_inspection_organisation_id"), table_name="inspection")
    op.drop_table("inspection")
    op.drop_index("ix_tenancy_rental_id", table_name="tenancy")
    op.drop_index(op.f("ix_tenancy_organisation_id"), table_name="tenancy")
    op.drop_table("tenancy")
    op.drop_index("ix_tenant_application_rental_id", table_name="tenant_application")
    op.drop_index(op.f("ix_tenant_application_organisation_id"), table_name="tenant_application")
    op.drop_table("tenant_application")
    op.drop_index(
        "uq_sale_offer_one_accepted",
        table_name="sale_offer",
        postgresql_where=sa.text("status = 'ACCEPTED' AND deleted_at IS NULL"),
    )
    op.drop_index("ix_sale_offer_sale_id", table_name="sale_offer")
    op.drop_index(op.f("ix_sale_offer_organisation_id"), table_name="sale_offer")
    op.drop_table("sale_offer")
    op.drop_index("ix_sale_enquiry_sale_id", table_name="sale_enquiry")
    op.drop_index(op.f("ix_sale_enquiry_organisation_id"), table_name="sale_enquiry")
    op.drop_table("sale_enquiry")
    op.drop_index("ix_sale_document_sale_id", table_name="sale_document")
    op.drop_index(op.f("ix_sale_document_organisation_id"), table_name="sale_document")
    op.drop_table("sale_document")
    op.drop_index(op.f("ix_sale_project_organisation_id"), table_name="sale_project")
    op.drop_table("sale_project")
    op.drop_index(op.f("ix_rental_property_organisation_id"), table_name="rental_property")
    op.drop_table("rental_property")
