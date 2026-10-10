"""Partner accounts (Milestone 14): partner organisations, applications, categories,
credentials and service areas, and the permissions to manage and verify them.

* ``partner_organisation``: one per ``PARTNER`` organisation, with the verification status
  (``APPLIED``, ``UNDER_REVIEW``, ``ACTIVE``, ``SUSPENDED``, ``REJECTED``), contact details
  and the reason shown when rejected or suspended.
* ``partner_application``: each submission with a snapshot of what was submitted and the
  staff decision.
* ``partner_category`` (marketplace categories the partner asked for, each approved by
  staff, optionally naming the credential that covers it), ``partner_credential`` (licences,
  insurance, accreditations, each checked by staff) and ``partner_service_area`` (postcodes,
  council areas, states).

Platform tables, like ``professional``: staff verify across partners and the lead engine
(Milestone 15) matches across them, so application authorisation guards them, not RLS.
Partner plans are ``PARTNER_PLAN`` products in the billing catalogue (synced on migrate)
and a partner's plan is an ordinary ``subscription`` of its organisation.

New permissions ``partner.manage`` (PARTNER_ADMIN) and ``partner.verify`` (STAFF, ADMIN,
SUPERADMIN).

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "approvalready_rw"

# Privileges of the application role on the new tables (tests/test_rls.py keeps the map).
PRIVILEGES: dict[str, str] = {
    "partner_organisation": "SELECT, INSERT, UPDATE",
    "partner_application": "SELECT, INSERT, UPDATE",
    "partner_credential": "SELECT, INSERT, UPDATE, DELETE",
    "partner_category": "SELECT, INSERT, UPDATE, DELETE",
    "partner_service_area": "SELECT, INSERT, DELETE",
}

NEW_PERMISSIONS = {
    "partner.manage": "Edit the partner profile, categories, service areas and credentials",
    "partner.verify": "Verify partners, their categories and credentials (staff)",
}
PERMISSION_ROLES = {
    "partner.manage": ("PARTNER_ADMIN",),
    "partner.verify": ("STAFF", "ADMIN", "SUPERADMIN"),
}


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
                "WHERE r.key = ANY(:roles) AND p.key = :permission"
            ),
            {"roles": list(PERMISSION_ROLES[key]), "permission": key},
        )


def upgrade() -> None:
    op.create_table(
        "partner_organisation",
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.Column("verification_status", sa.Text(), server_default="APPLIED", nullable=False),
        sa.Column("website", sa.String(length=300), nullable=True),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("contact_email", sa.String(length=320), nullable=True),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("status_reason", sa.String(length=1000), nullable=True),
        sa.Column("status_changed_by", sa.UUID(), nullable=True),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
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
            "verification_status IN ('APPLIED', 'UNDER_REVIEW', 'ACTIVE', 'SUSPENDED', 'REJECTED')",
            name=op.f("ck_partner_organisation_verification_status_valid"),
        ),
        sa.CheckConstraint(
            "verification_status NOT IN ('REJECTED', 'SUSPENDED') OR status_reason IS NOT NULL",
            name=op.f("ck_partner_organisation_stopped_has_reason"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_partner_organisation_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_partner_organisation_organisation_id_organisation"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["status_changed_by"],
            ["app_user.id"],
            name=op.f("fk_partner_organisation_status_changed_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_partner_organisation")),
        sa.UniqueConstraint(
            "organisation_id", name=op.f("uq_partner_organisation_organisation_id")
        ),
    )
    op.create_index(
        "ix_partner_organisation_status",
        "partner_organisation",
        ["verification_status", "submitted_at"],
        unique=False,
    )
    op.create_table(
        "partner_application",
        sa.Column("partner_organisation_id", sa.UUID(), nullable=False),
        sa.Column("submitted_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("submitted_by", sa.UUID(), nullable=True),
        sa.Column("status", sa.Text(), server_default="SUBMITTED", nullable=False),
        sa.Column("reviewed_by", sa.UUID(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_notes", sa.String(length=1000), nullable=True),
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
            "status = 'SUBMITTED' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name=op.f("ck_partner_application_decided_has_reviewer"),
        ),
        sa.CheckConstraint(
            "status IN ('SUBMITTED', 'APPROVED', 'REJECTED')",
            name=op.f("ck_partner_application_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["partner_organisation_id"],
            ["partner_organisation.id"],
            name=op.f("fk_partner_application_partner_organisation_id_partner_organisation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["app_user.id"],
            name=op.f("fk_partner_application_reviewed_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"],
            ["app_user.id"],
            name=op.f("fk_partner_application_submitted_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_partner_application")),
    )
    op.create_index(
        "ix_partner_application_partner",
        "partner_application",
        ["partner_organisation_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "partner_credential",
        sa.Column("partner_organisation_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("issuer", sa.String(length=200), nullable=False),
        sa.Column("number", sa.String(length=100), nullable=False),
        sa.Column("cover_cents", sa.BigInteger(), nullable=True),
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
            "kind IN ('LICENCE', 'PI_INSURANCE', 'PL_INSURANCE', 'ACCREDITATION')",
            name=op.f("ck_partner_credential_kind_valid"),
        ),
        sa.CheckConstraint(
            "status = 'UNVERIFIED' OR (verified_by IS NOT NULL AND verified_at IS NOT NULL)",
            name=op.f("ck_partner_credential_checked_has_checker"),
        ),
        sa.CheckConstraint(
            "status IN ('UNVERIFIED', 'VERIFIED', 'REJECTED')",
            name=op.f("ck_partner_credential_status_valid"),
        ),
        sa.CheckConstraint(
            "cover_cents IS NULL OR cover_cents > 0",
            name=op.f("ck_partner_credential_cover_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_partner_credential_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["partner_organisation_id"],
            ["partner_organisation.id"],
            name=op.f("fk_partner_credential_partner_organisation_id_partner_organisation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["verified_by"],
            ["app_user.id"],
            name=op.f("fk_partner_credential_verified_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_partner_credential")),
    )
    op.create_index(
        "ix_partner_credential_partner",
        "partner_credential",
        ["partner_organisation_id"],
        unique=False,
    )
    op.create_table(
        "partner_service_area",
        sa.Column("partner_organisation_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("value", sa.String(length=120), nullable=False),
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
            "kind <> 'POSTCODE' OR value ~ '^[0-9]{4}$'",
            name=op.f("ck_partner_service_area_postcode_format"),
        ),
        sa.CheckConstraint(
            "kind <> 'STATE' OR value = state", name=op.f("ck_partner_service_area_state_value")
        ),
        sa.CheckConstraint(
            "kind IN ('POSTCODE', 'LGA', 'STATE')", name=op.f("ck_partner_service_area_kind_valid")
        ),
        sa.CheckConstraint(
            "state IN ('NSW', 'VIC', 'QLD', 'SA', 'WA', 'TAS', 'NT', 'ACT')",
            name=op.f("ck_partner_service_area_state_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_partner_service_area_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["partner_organisation_id"],
            ["partner_organisation.id"],
            name=op.f("fk_partner_service_area_partner_organisation_id_partner_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_partner_service_area")),
        sa.UniqueConstraint(
            "partner_organisation_id",
            "kind",
            "state",
            "value",
            name=op.f("uq_partner_service_area_partner_organisation_id_kind_state_value"),
        ),
    )
    op.create_index(
        "ix_partner_service_area_match",
        "partner_service_area",
        ["kind", "state", "value"],
        unique=False,
    )
    op.create_table(
        "partner_category",
        sa.Column("partner_organisation_id", sa.UUID(), nullable=False),
        sa.Column("category_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.Text(), server_default="PENDING", nullable=False),
        sa.Column("credential_id", sa.UUID(), nullable=True),
        sa.Column("notes", sa.String(length=500), nullable=True),
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
        sa.CheckConstraint(
            "status = 'PENDING' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name=op.f("ck_partner_category_decided_has_reviewer"),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED')",
            name=op.f("ck_partner_category_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["marketplace_category.id"],
            name=op.f("fk_partner_category_category_id_marketplace_category"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_partner_category_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["partner_credential.id"],
            name=op.f("fk_partner_category_credential_id_partner_credential"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["partner_organisation_id"],
            ["partner_organisation.id"],
            name=op.f("fk_partner_category_partner_organisation_id_partner_organisation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["app_user.id"],
            name=op.f("fk_partner_category_reviewed_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_partner_category")),
        sa.UniqueConstraint(
            "partner_organisation_id",
            "category_id",
            name=op.f("uq_partner_category_partner_organisation_id_category_id"),
        ),
    )
    for table, privileges in PRIVILEGES.items():
        op.execute(f"GRANT {privileges} ON {table} TO {APP_ROLE}")
    _seed_permissions()


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permission WHERE permission_id IN "
        "(SELECT id FROM permission WHERE key IN ('partner.manage', 'partner.verify'))"
    )
    op.execute("DELETE FROM permission WHERE key IN ('partner.manage', 'partner.verify')")
    op.drop_table("partner_category")
    op.drop_index("ix_partner_service_area_match", table_name="partner_service_area")
    op.drop_table("partner_service_area")
    op.drop_index("ix_partner_credential_partner", table_name="partner_credential")
    op.drop_table("partner_credential")
    op.drop_index("ix_partner_application_partner", table_name="partner_application")
    op.drop_table("partner_application")
    op.drop_index("ix_partner_organisation_status", table_name="partner_organisation")
    op.drop_table("partner_organisation")
