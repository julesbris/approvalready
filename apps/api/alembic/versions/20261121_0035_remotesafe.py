"""RemoteSafe Stage 1: remote-work journey plans, risk assessment, controls and approvals.

All tables are tenant-owned, with forced row-level security on ``organisation_id`` and
composite tenant foreign keys:

* ``rs_settings``: RemoteSafe switched on for an organisation (tier, risk policy overrides).
* ``rs_member_role``: RemoteSafe roles (worker, supervisor, monitor, WHS administrator).
  Product roles live here, so the platform role catalogue and its permissions are unchanged.
* ``rs_vehicle``: the organisation's vehicle register.
* ``rs_journey``, ``rs_route_leg``, ``rs_checkin_plan``: the plan. Planned places only; no
  live location is collected.
* ``rs_risk_assessment``, ``rs_hazard_finding``: every run of the rules engine
  (append-only history).
* ``rs_control_check``: the pre-departure checklist for each journey.
* ``rs_journey_event``, ``rs_journey_revision``: the audit trail and plan snapshots
  (append-only).

No existing table changes. No data is back-filled.

Revision ID: 0035
Revises: 0034
Create Date: 2026-11-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "approvalready_rw"

# Privileges of the application role on the new tables (tests/test_rls.py keeps the map).
PRIVILEGES: dict[str, str] = {
    "rs_settings": "SELECT, INSERT, UPDATE",
    "rs_member_role": "SELECT, INSERT, UPDATE, DELETE",
    "rs_vehicle": "SELECT, INSERT, UPDATE",
    "rs_journey": "SELECT, INSERT, UPDATE",
    "rs_route_leg": "SELECT, INSERT, UPDATE, DELETE",
    "rs_checkin_plan": "SELECT, INSERT, UPDATE, DELETE",
    "rs_risk_assessment": "SELECT, INSERT",
    "rs_hazard_finding": "SELECT, INSERT",
    "rs_control_check": "SELECT, INSERT, UPDATE",
    "rs_journey_event": "SELECT, INSERT",
    "rs_journey_revision": "SELECT, INSERT",
}

TENANT_PREDICATE = "organisation_id = nullif(current_setting('app.current_org', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "rs_member_role",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
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
            "role IN ('WORKER', 'SUPERVISOR', 'MONITOR', 'WHS_ADMIN')",
            name=op.f("ck_rs_member_role_role_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_rs_member_role_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_rs_member_role_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_rs_member_role_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rs_member_role")),
        sa.UniqueConstraint(
            "organisation_id",
            "user_id",
            "role",
            name=op.f("uq_rs_member_role_organisation_id_user_id_role"),
        ),
    )
    op.create_index(
        op.f("ix_rs_member_role_organisation_id"),
        "rs_member_role",
        ["organisation_id"],
        unique=False,
    )
    op.create_table(
        "rs_settings",
        sa.Column("tier", sa.Text(), server_default="STARTER", nullable=False),
        sa.Column("default_timezone", sa.String(length=40), nullable=False),
        sa.Column("policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
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
            "jsonb_typeof(policy) = 'object'", name=op.f("ck_rs_settings_policy_object")
        ),
        sa.CheckConstraint(
            "tier IN ('STARTER', 'PROFESSIONAL', 'ENTERPRISE')",
            name=op.f("ck_rs_settings_tier_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_rs_settings_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_rs_settings_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rs_settings")),
        sa.UniqueConstraint("organisation_id", name=op.f("uq_rs_settings_organisation_id")),
    )
    op.create_index(
        op.f("ix_rs_settings_organisation_id"), "rs_settings", ["organisation_id"], unique=False
    )
    op.create_table(
        "rs_vehicle",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("registration", sa.String(length=20), nullable=False),
        sa.Column("vehicle_type", sa.String(length=60), nullable=False),
        sa.Column("fuel_range_km", sa.Integer(), nullable=True),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
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
            "fuel_range_km IS NULL OR fuel_range_km BETWEEN 1 AND 5000",
            name=op.f("ck_rs_vehicle_fuel_range"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_rs_vehicle_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_rs_vehicle_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rs_vehicle")),
        sa.UniqueConstraint("organisation_id", "id", name=op.f("uq_rs_vehicle_organisation_id_id")),
    )
    op.create_index(
        op.f("ix_rs_vehicle_organisation_id"), "rs_vehicle", ["organisation_id"], unique=False
    )
    op.create_table(
        "rs_journey",
        sa.Column("reference", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.Text(), server_default="DRAFT", nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("worker_user_id", sa.UUID(), nullable=False),
        sa.Column("supervisor_user_id", sa.UUID(), nullable=True),
        sa.Column("monitor_user_id", sa.UUID(), nullable=True),
        sa.Column("team", sa.String(length=120), nullable=True),
        sa.Column("worker_phone", sa.String(length=40), nullable=True),
        sa.Column("purpose", sa.String(length=1000), nullable=False),
        sa.Column("activities", sa.String(length=2000), nullable=True),
        sa.Column("origin", sa.String(length=200), nullable=False),
        sa.Column("destination", sa.String(length=200), nullable=False),
        sa.Column("remoteness", sa.Text(), server_default="UNKNOWN", nullable=False),
        sa.Column("return_journey", sa.Boolean(), nullable=False),
        sa.Column("timezone", sa.String(length=40), nullable=False),
        sa.Column("departs_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("arrives_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("returns_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("vehicle_id", sa.UUID(), nullable=True),
        sa.Column("vehicle_description", sa.String(length=200), nullable=True),
        sa.Column("vehicle_registration", sa.String(length=20), nullable=True),
        sa.Column("occupants", sa.Integer(), nullable=False),
        sa.Column("comms_mobile", sa.Boolean(), nullable=False),
        sa.Column("comms_uhf", sa.Boolean(), nullable=False),
        sa.Column("comms_sat_phone", sa.Boolean(), nullable=False),
        sa.Column("comms_sat_messenger", sa.Boolean(), nullable=False),
        sa.Column("comms_notes", sa.String(length=1000), nullable=True),
        sa.Column("emergency_contacts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("checkin_interval_minutes", sa.Integer(), nullable=True),
        sa.Column("alternative_route", sa.String(length=2000), nullable=True),
        sa.Column("contingency_plan", sa.String(length=2000), nullable=True),
        sa.Column("weather_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("weather_source", sa.String(length=200), nullable=True),
        sa.Column("weather_warnings", sa.String(length=1000), nullable=True),
        sa.Column("current_assessment_id", sa.UUID(), nullable=True),
        sa.Column("risk_outcome", sa.Text(), nullable=True),
        sa.Column("approved_revision", sa.Integer(), nullable=True),
        sa.Column("approved_outcome", sa.Text(), nullable=True),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("critical_alternative_process", sa.String(length=2000), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
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
            "approved_outcome IS NULL OR approved_outcome IN ('LOW', 'MODERATE', 'HIGH', 'CRITICAL')",
            name=op.f("ck_rs_journey_approved_outcome_valid"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(emergency_contacts) = 'array'", name=op.f("ck_rs_journey_contacts_array")
        ),
        sa.CheckConstraint(
            "remoteness IN ('UNKNOWN', 'NOT_REMOTE', 'REMOTE', 'VERY_REMOTE')",
            name=op.f("ck_rs_journey_remoteness_valid"),
        ),
        sa.CheckConstraint(
            "risk_outcome IS NULL OR risk_outcome IN ('LOW', 'MODERATE', 'HIGH', 'CRITICAL')",
            name=op.f("ck_rs_journey_risk_outcome_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'SUBMITTED', 'CHANGES_REQUESTED', 'APPROVED', 'ACTIVE', 'OVERDUE', 'ESCALATED', 'COMPLETED', 'CANCELLED')",
            name=op.f("ck_rs_journey_status_valid"),
        ),
        sa.CheckConstraint(
            "arrives_at > departs_at", name=op.f("ck_rs_journey_arrives_after_departs")
        ),
        sa.CheckConstraint(
            "checkin_interval_minutes IS NULL OR checkin_interval_minutes BETWEEN 15 AND 1440",
            name=op.f("ck_rs_journey_checkin_interval"),
        ),
        sa.CheckConstraint("occupants BETWEEN 1 AND 60", name=op.f("ck_rs_journey_occupants")),
        sa.CheckConstraint(
            "returns_at IS NULL OR returns_at >= arrives_at",
            name=op.f("ck_rs_journey_returns_after"),
        ),
        sa.CheckConstraint("revision >= 1", name=op.f("ck_rs_journey_revision_positive")),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["app_user.id"],
            name=op.f("fk_rs_journey_approved_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_rs_journey_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["monitor_user_id"],
            ["app_user.id"],
            name=op.f("fk_rs_journey_monitor_user_id_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "vehicle_id"],
            ["rs_vehicle.organisation_id", "rs_vehicle.id"],
            name=op.f("fk_rs_journey_organisation_id_rs_vehicle"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_rs_journey_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["supervisor_user_id"],
            ["app_user.id"],
            name=op.f("fk_rs_journey_supervisor_user_id_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["worker_user_id"],
            ["app_user.id"],
            name=op.f("fk_rs_journey_worker_user_id_app_user"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rs_journey")),
        sa.UniqueConstraint("organisation_id", "id", name=op.f("uq_rs_journey_organisation_id_id")),
        sa.UniqueConstraint(
            "organisation_id", "reference", name=op.f("uq_rs_journey_organisation_id_reference")
        ),
    )
    op.create_index(
        op.f("ix_rs_journey_organisation_id"), "rs_journey", ["organisation_id"], unique=False
    )
    op.create_index(
        "ix_rs_journey_status", "rs_journey", ["organisation_id", "status"], unique=False
    )
    op.create_index(
        "ix_rs_journey_supervisor",
        "rs_journey",
        ["organisation_id", "supervisor_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_rs_journey_worker", "rs_journey", ["organisation_id", "worker_user_id"], unique=False
    )
    op.create_table(
        "rs_checkin_plan",
        sa.Column("journey_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("method", sa.Text(), nullable=False),
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
            "method IN ('PHONE_CALL', 'SMS', 'SATELLITE_MESSAGE', 'SATELLITE_CALL', 'UHF', 'APP')",
            name=op.f("ck_rs_checkin_plan_method_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "journey_id"],
            ["rs_journey.organisation_id", "rs_journey.id"],
            name=op.f("fk_rs_checkin_plan_organisation_id_rs_journey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_rs_checkin_plan_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rs_checkin_plan")),
        sa.UniqueConstraint(
            "journey_id", "position", name=op.f("uq_rs_checkin_plan_journey_id_position")
        ),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_rs_checkin_plan_organisation_id_id")
        ),
    )
    op.create_index(
        op.f("ix_rs_checkin_plan_organisation_id"),
        "rs_checkin_plan",
        ["organisation_id"],
        unique=False,
    )
    op.create_table(
        "rs_control_check",
        sa.Column("journey_id", sa.UUID(), nullable=False),
        sa.Column("control_key", sa.String(length=60), nullable=False),
        sa.Column("control_group", sa.String(length=20), nullable=False),
        sa.Column("label", sa.String(length=300), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("mandatory", sa.Boolean(), nullable=False),
        sa.Column("required_by", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("status", sa.Text(), server_default="PENDING", nullable=False),
        sa.Column("note", sa.String(length=1000), nullable=True),
        sa.Column("completed_by", sa.UUID(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_revision", sa.Integer(), nullable=True),
        sa.Column("exception_reason", sa.String(length=1000), nullable=True),
        sa.Column("exception_by", sa.UUID(), nullable=True),
        sa.Column(
            "evidence_document_ids",
            postgresql.ARRAY(sa.UUID()),
            server_default="{}",
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
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "NOT (mandatory AND status = 'NOT_APPLICABLE')",
            name=op.f("ck_rs_control_check_mandatory_applies"),
        ),
        sa.CheckConstraint(
            "status <> 'EXCEPTION' OR (exception_reason IS NOT NULL AND exception_by IS NOT NULL)",
            name=op.f("ck_rs_control_check_exception_recorded"),
        ),
        sa.CheckConstraint(
            "status = 'PENDING' OR (completed_by IS NOT NULL AND completed_at IS NOT NULL)",
            name=op.f("ck_rs_control_check_who_and_when"),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'DONE', 'FAILED', 'NOT_APPLICABLE', 'EXCEPTION')",
            name=op.f("ck_rs_control_check_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["completed_by"],
            ["app_user.id"],
            name=op.f("fk_rs_control_check_completed_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["exception_by"],
            ["app_user.id"],
            name=op.f("fk_rs_control_check_exception_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "journey_id"],
            ["rs_journey.organisation_id", "rs_journey.id"],
            name=op.f("fk_rs_control_check_organisation_id_rs_journey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_rs_control_check_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rs_control_check")),
        sa.UniqueConstraint(
            "journey_id", "control_key", name=op.f("uq_rs_control_check_journey_id_control_key")
        ),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_rs_control_check_organisation_id_id")
        ),
    )
    op.create_index(
        op.f("ix_rs_control_check_organisation_id"),
        "rs_control_check",
        ["organisation_id"],
        unique=False,
    )
    op.create_table(
        "rs_journey_event",
        sa.Column("journey_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("note", sa.String(length=2000), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["app_user.id"],
            name=op.f("fk_rs_journey_event_actor_user_id_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "journey_id"],
            ["rs_journey.organisation_id", "rs_journey.id"],
            name=op.f("fk_rs_journey_event_organisation_id_rs_journey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_rs_journey_event_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rs_journey_event")),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_rs_journey_event_organisation_id_id")
        ),
    )
    op.create_index(
        "ix_rs_journey_event_journey",
        "rs_journey_event",
        ["journey_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_rs_journey_event_organisation_id"),
        "rs_journey_event",
        ["organisation_id"],
        unique=False,
    )
    op.create_table(
        "rs_journey_revision",
        sa.Column("journey_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "changed_fields", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_rs_journey_revision_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "journey_id"],
            ["rs_journey.organisation_id", "rs_journey.id"],
            name=op.f("fk_rs_journey_revision_organisation_id_rs_journey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_rs_journey_revision_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rs_journey_revision")),
        sa.UniqueConstraint(
            "journey_id", "revision", name=op.f("uq_rs_journey_revision_journey_id_revision")
        ),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_rs_journey_revision_organisation_id_id")
        ),
    )
    op.create_index(
        op.f("ix_rs_journey_revision_organisation_id"),
        "rs_journey_revision",
        ["organisation_id"],
        unique=False,
    )
    op.create_table(
        "rs_risk_assessment",
        sa.Column("journey_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("library_version", sa.String(length=20), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("facts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("stop_conditions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('LOW', 'MODERATE', 'HIGH', 'CRITICAL')",
            name=op.f("ck_rs_risk_assessment_outcome_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_rs_risk_assessment_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "journey_id"],
            ["rs_journey.organisation_id", "rs_journey.id"],
            name=op.f("fk_rs_risk_assessment_organisation_id_rs_journey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_rs_risk_assessment_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rs_risk_assessment")),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_rs_risk_assessment_organisation_id_id")
        ),
    )
    op.create_index(
        "ix_rs_risk_assessment_journey",
        "rs_risk_assessment",
        ["journey_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_rs_risk_assessment_organisation_id"),
        "rs_risk_assessment",
        ["organisation_id"],
        unique=False,
    )
    op.create_table(
        "rs_route_leg",
        sa.Column("journey_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(length=200), nullable=False),
        sa.Column("destination", sa.String(length=200), nullable=False),
        sa.Column("origin_lat", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("origin_lng", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("destination_lat", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("destination_lng", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("timezone", sa.String(length=40), nullable=False),
        sa.Column("departs_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("arrives_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("distance_km", sa.Numeric(precision=7, scale=1), nullable=True),
        sa.Column("road_surface", sa.Text(), nullable=False),
        sa.Column("mobile_coverage", sa.Text(), nullable=False),
        sa.Column("crossings", sa.Integer(), nullable=False),
        sa.Column("closure_status", sa.Text(), nullable=False),
        sa.Column("closure_source", sa.String(length=200), nullable=True),
        sa.Column("closure_observed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "closure_status IN ('NOT_CHECKED', 'NONE_KNOWN', 'RESTRICTED', 'CONFIRMED_CLOSED')",
            name=op.f("ck_rs_route_leg_closure_status_valid"),
        ),
        sa.CheckConstraint(
            "mobile_coverage IN ('UNKNOWN', 'GOOD', 'PATCHY', 'NONE')",
            name=op.f("ck_rs_route_leg_mobile_coverage_valid"),
        ),
        sa.CheckConstraint(
            "road_surface IN ('UNKNOWN', 'SEALED', 'MIXED', 'UNSEALED')",
            name=op.f("ck_rs_route_leg_road_surface_valid"),
        ),
        sa.CheckConstraint(
            "(origin_lat IS NULL OR origin_lat BETWEEN -45 AND -9) AND (destination_lat IS NULL OR destination_lat BETWEEN -45 AND -9) AND (origin_lng IS NULL OR origin_lng BETWEEN 112 AND 155) AND (destination_lng IS NULL OR destination_lng BETWEEN 112 AND 155)",
            name=op.f("ck_rs_route_leg_in_australia"),
        ),
        sa.CheckConstraint(
            "arrives_at > departs_at", name=op.f("ck_rs_route_leg_arrives_after_departs")
        ),
        sa.CheckConstraint("crossings BETWEEN 0 AND 500", name=op.f("ck_rs_route_leg_crossings")),
        sa.CheckConstraint(
            "distance_km IS NULL OR (distance_km > 0 AND distance_km < 10000)",
            name=op.f("ck_rs_route_leg_distance"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "journey_id"],
            ["rs_journey.organisation_id", "rs_journey.id"],
            name=op.f("fk_rs_route_leg_organisation_id_rs_journey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_rs_route_leg_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rs_route_leg")),
        sa.UniqueConstraint(
            "journey_id", "position", name=op.f("uq_rs_route_leg_journey_id_position")
        ),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_rs_route_leg_organisation_id_id")
        ),
    )
    op.create_index(
        op.f("ix_rs_route_leg_organisation_id"), "rs_route_leg", ["organisation_id"], unique=False
    )
    op.create_table(
        "rs_hazard_finding",
        sa.Column("assessment_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("hazard_key", sa.String(length=60), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("likelihood", sa.Integer(), nullable=False),
        sa.Column("consequence", sa.Integer(), nullable=False),
        sa.Column("initial_score", sa.Integer(), nullable=False),
        sa.Column("initial_rating", sa.Text(), nullable=False),
        sa.Column("controls", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("residual_likelihood", sa.Integer(), nullable=False),
        sa.Column("residual_score", sa.Integer(), nullable=False),
        sa.Column("residual_rating", sa.Text(), nullable=False),
        sa.Column("responsible", sa.Text(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "initial_rating IN ('LOW', 'MODERATE', 'HIGH', 'CRITICAL')",
            name=op.f("ck_rs_hazard_finding_initial_rating_valid"),
        ),
        sa.CheckConstraint(
            "residual_rating IN ('LOW', 'MODERATE', 'HIGH', 'CRITICAL')",
            name=op.f("ck_rs_hazard_finding_residual_rating_valid"),
        ),
        sa.CheckConstraint(
            "likelihood BETWEEN 1 AND 5 AND consequence BETWEEN 1 AND 5 AND residual_likelihood BETWEEN 1 AND 5",
            name=op.f("ck_rs_hazard_finding_scales"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "assessment_id"],
            ["rs_risk_assessment.organisation_id", "rs_risk_assessment.id"],
            name=op.f("fk_rs_hazard_finding_organisation_id_rs_risk_assessment"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_rs_hazard_finding_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rs_hazard_finding")),
        sa.UniqueConstraint(
            "assessment_id",
            "hazard_key",
            name=op.f("uq_rs_hazard_finding_assessment_id_hazard_key"),
        ),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_rs_hazard_finding_organisation_id_id")
        ),
    )
    op.create_index(
        op.f("ix_rs_hazard_finding_organisation_id"),
        "rs_hazard_finding",
        ["organisation_id"],
        unique=False,
    )
    for table, privileges in PRIVILEGES.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
        )
        op.execute(f"GRANT {privileges} ON {table} TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_index(op.f("ix_rs_hazard_finding_organisation_id"), table_name="rs_hazard_finding")
    op.drop_table("rs_hazard_finding")
    op.drop_index(op.f("ix_rs_route_leg_organisation_id"), table_name="rs_route_leg")
    op.drop_table("rs_route_leg")
    op.drop_index(op.f("ix_rs_risk_assessment_organisation_id"), table_name="rs_risk_assessment")
    op.drop_index("ix_rs_risk_assessment_journey", table_name="rs_risk_assessment")
    op.drop_table("rs_risk_assessment")
    op.drop_index(op.f("ix_rs_journey_revision_organisation_id"), table_name="rs_journey_revision")
    op.drop_table("rs_journey_revision")
    op.drop_index(op.f("ix_rs_journey_event_organisation_id"), table_name="rs_journey_event")
    op.drop_index("ix_rs_journey_event_journey", table_name="rs_journey_event")
    op.drop_table("rs_journey_event")
    op.drop_index(op.f("ix_rs_control_check_organisation_id"), table_name="rs_control_check")
    op.drop_table("rs_control_check")
    op.drop_index(op.f("ix_rs_checkin_plan_organisation_id"), table_name="rs_checkin_plan")
    op.drop_table("rs_checkin_plan")
    op.drop_index("ix_rs_journey_worker", table_name="rs_journey")
    op.drop_index("ix_rs_journey_supervisor", table_name="rs_journey")
    op.drop_index("ix_rs_journey_status", table_name="rs_journey")
    op.drop_index(op.f("ix_rs_journey_organisation_id"), table_name="rs_journey")
    op.drop_table("rs_journey")
    op.drop_index(op.f("ix_rs_vehicle_organisation_id"), table_name="rs_vehicle")
    op.drop_table("rs_vehicle")
    op.drop_index(op.f("ix_rs_settings_organisation_id"), table_name="rs_settings")
    op.drop_table("rs_settings")
    op.drop_index(op.f("ix_rs_member_role_organisation_id"), table_name="rs_member_role")
    op.drop_table("rs_member_role")
