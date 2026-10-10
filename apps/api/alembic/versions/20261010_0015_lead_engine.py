"""Lead engine (Milestone 15): referral consent, leads, matching, claims, lead prices and
partner credits.

* ``consent_text_version``: reviewed consent wording, synced on migrate
  (``python -m app.cli leads sync-consent``); read-only for the application.
* ``referral_consent`` (tenant, forced RLS): what the customer agreed to. Only the
  withdrawal can change afterwards (trigger).
* ``lead``, ``lead_contact``, ``lead_match``, ``lead_claim``, ``lead_status_event``,
  ``lead_price``: platform tables guarded by the API (matching runs across partners and
  customers), like the partner tables. Lead prices never change (trigger); events are
  append-only.
* ``credit_ledger_entry`` (tenant, forced RLS, append-only): the partner's credits.
* ``partner_organisation`` gains ``paused`` and ``max_open_leads``.
* Notification kinds ``LEAD_OFFERED`` and ``LEAD_CLAIMED``; permission ``lead.manage``
  (ADMIN, SUPERADMIN): lead prices, credits and refunds.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "approvalready_rw"
TENANT_PREDICATE = "organisation_id = nullif(current_setting('app.current_org', true), '')::uuid"
TENANT_TABLES = ("referral_consent", "credit_ledger_entry")

# Privileges of the application role on the new tables (tests/test_rls.py keeps the map).
PRIVILEGES: dict[str, str] = {
    "consent_text_version": "SELECT",
    "referral_consent": "SELECT, INSERT, UPDATE",
    "lead": "SELECT, INSERT, UPDATE",
    "lead_contact": "SELECT, INSERT, DELETE",
    "lead_match": "SELECT, INSERT, UPDATE",
    "lead_claim": "SELECT, INSERT, UPDATE",
    "lead_status_event": "SELECT, INSERT",
    "lead_price": "SELECT, INSERT, UPDATE",
    "credit_ledger_entry": "SELECT, INSERT",
}

KINDS_OLD = ("REMINDER", "GRANT_ROUND", "SOURCES_DUE")
KINDS_NEW = (*KINDS_OLD, "LEAD_OFFERED", "LEAD_CLAIMED")

NEW_PERMISSIONS = {
    "lead.manage": "Set lead prices, give credits and refund lead fees (staff)",
}
PERMISSION_ROLES = {
    "lead.manage": ("ADMIN", "SUPERADMIN"),
}

# What the customer agreed to never changes; only the withdrawal is recorded later.
CONSENT_GUARD = """
CREATE FUNCTION referral_consent_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'a referral consent cannot be deleted';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['withdrawn_at', 'withdrawn_by', 'updated_at'])
        IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['withdrawn_at', 'withdrawn_by', 'updated_at']) THEN
        RAISE EXCEPTION 'a referral consent never changes; only its withdrawal is recorded';
    END IF;
    IF OLD.withdrawn_at IS NOT NULL AND NEW.withdrawn_at IS DISTINCT FROM OLD.withdrawn_at THEN
        RAISE EXCEPTION 'a withdrawn consent stays withdrawn';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER referral_consent_immutable
    BEFORE UPDATE OR DELETE ON referral_consent
    FOR EACH ROW EXECUTE FUNCTION referral_consent_guard();
"""

LEAD_PRICE_GUARD = """
CREATE FUNCTION lead_price_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'lead prices cannot be deleted; deactivate them';
    END IF;
    IF NEW.category_id IS DISTINCT FROM OLD.category_id
        OR NEW.amount_cents IS DISTINCT FROM OLD.amount_cents
        OR NEW.currency IS DISTINCT FROM OLD.currency
        OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'a lead price never changes; add a new one';
    END IF;
    IF OLD.deactivated_at IS NOT NULL AND NEW.deactivated_at IS DISTINCT FROM OLD.deactivated_at THEN
        RAISE EXCEPTION 'a deactivated lead price stays deactivated';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER lead_price_immutable
    BEFORE UPDATE OR DELETE ON lead_price
    FOR EACH ROW EXECUTE FUNCTION lead_price_guard();
"""


def _notification_kinds(kinds: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_notification_kind_valid"), "notification")
    quoted = ", ".join(f"'{k}'" for k in kinds)
    op.create_check_constraint(
        op.f("ck_notification_kind_valid"), "notification", f"kind IN ({quoted})"
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
                "WHERE r.key = ANY(:roles) AND p.key = :permission"
            ),
            {"roles": list(PERMISSION_ROLES[key]), "permission": key},
        )


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "consent_text_version",
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('PARTNER_REFERRAL')", name=op.f("ck_consent_text_version_purpose_valid")
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_consent_text_version_version_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consent_text_version")),
        sa.UniqueConstraint(
            "purpose", "content_hash", name=op.f("uq_consent_text_version_purpose_content_hash")
        ),
        sa.UniqueConstraint(
            "purpose", "version", name=op.f("uq_consent_text_version_purpose_version")
        ),
    )
    op.create_table(
        "lead_price",
        sa.Column("category_id", sa.UUID(), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="AUD", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.CheckConstraint("currency = 'AUD'", name=op.f("ck_lead_price_currency_aud")),
        sa.CheckConstraint("amount_cents > 0", name=op.f("ck_lead_price_amount_positive")),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["marketplace_category.id"],
            name=op.f("fk_lead_price_category_id_marketplace_category"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_lead_price_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lead_price")),
    )
    op.create_index(
        "uq_lead_price_active_category",
        "lead_price",
        ["category_id"],
        unique=True,
        postgresql_where=sa.text("deactivated_at IS NULL"),
    )
    op.create_table(
        "credit_ledger_entry",
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("delta_cents", sa.BigInteger(), nullable=False),
        sa.Column("balance_after_cents", sa.BigInteger(), nullable=False),
        sa.Column("reference_type", sa.String(length=40), nullable=True),
        sa.Column("reference_id", sa.UUID(), nullable=True),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('PURCHASE', 'PROMO', 'LEAD_CHARGE', 'REFUND', 'ADJUSTMENT')",
            name=op.f("ck_credit_ledger_entry_kind_valid"),
        ),
        sa.CheckConstraint(
            "balance_after_cents >= 0", name=op.f("ck_credit_ledger_entry_balance_not_negative")
        ),
        sa.CheckConstraint("delta_cents <> 0", name=op.f("ck_credit_ledger_entry_delta_not_zero")),
        sa.CheckConstraint("seq > 0", name=op.f("ck_credit_ledger_entry_seq_positive")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_credit_ledger_entry_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_credit_ledger_entry_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credit_ledger_entry")),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_credit_ledger_entry_organisation_id_id")
        ),
        sa.UniqueConstraint(
            "organisation_id", "seq", name=op.f("uq_credit_ledger_entry_organisation_id_seq")
        ),
    )
    op.create_index(
        op.f("ix_credit_ledger_entry_organisation_id"),
        "credit_ledger_entry",
        ["organisation_id"],
        unique=False,
    )
    op.create_table(
        "referral_consent",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("assessment_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("consent_text_version_id", sa.UUID(), nullable=False),
        sa.Column("categories", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("max_providers", sa.Integer(), nullable=False),
        sa.Column("fields_released", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("contact", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("suburb", sa.String(length=100), nullable=True),
        sa.Column("lga", sa.String(length=120), nullable=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("postcode", sa.String(length=4), nullable=False),
        sa.Column("timing", sa.Text(), nullable=False),
        sa.Column("summary", sa.String(length=600), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_by", sa.UUID(), nullable=True),
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
            "fields_released <@ ARRAY['name','email','phone','site_address']::text[] AND cardinality(fields_released) > 0",
            name=op.f("ck_referral_consent_fields_released_valid"),
        ),
        sa.CheckConstraint(
            "postcode ~ '^[0-9]{4}$'", name=op.f("ck_referral_consent_postcode_format")
        ),
        sa.CheckConstraint(
            "state IN ('NSW', 'VIC', 'QLD', 'SA', 'WA', 'TAS', 'NT', 'ACT')",
            name=op.f("ck_referral_consent_state_valid"),
        ),
        sa.CheckConstraint(
            "timing IN ('ASAP', 'WITHIN_3_MONTHS', 'LATER', 'RESEARCHING')",
            name=op.f("ck_referral_consent_timing_valid"),
        ),
        sa.CheckConstraint(
            "cardinality(categories) BETWEEN 1 AND 5",
            name=op.f("ck_referral_consent_categories_count"),
        ),
        sa.CheckConstraint(
            "max_providers BETWEEN 1 AND 3", name=op.f("ck_referral_consent_max_providers_range")
        ),
        sa.CheckConstraint(
            "withdrawn_at IS NULL OR withdrawn_by IS NOT NULL",
            name=op.f("ck_referral_consent_withdrawn_has_actor"),
        ),
        sa.ForeignKeyConstraint(
            ["consent_text_version_id"],
            ["consent_text_version.id"],
            name=op.f("fk_referral_consent_consent_text_version_id_consent_text_version"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "assessment_id"],
            ["assessment.organisation_id", "assessment.id"],
            name=op.f("fk_referral_consent_organisation_id_assessment"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id", "project_id"],
            ["project.organisation_id", "project.id"],
            name=op.f("fk_referral_consent_organisation_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_referral_consent_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_referral_consent_user_id_app_user"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["withdrawn_by"],
            ["app_user.id"],
            name=op.f("fk_referral_consent_withdrawn_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_referral_consent")),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_referral_consent_organisation_id_id")
        ),
    )
    op.create_index(
        op.f("ix_referral_consent_organisation_id"),
        "referral_consent",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        "ix_referral_consent_project",
        "referral_consent",
        ["organisation_id", "project_id"],
        unique=False,
    )
    op.create_table(
        "lead",
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("referral_consent_id", sa.UUID(), nullable=False),
        sa.Column("category_id", sa.UUID(), nullable=False),
        sa.Column("vertical", sa.Text(), nullable=False),
        sa.Column("suburb", sa.String(length=100), nullable=True),
        sa.Column("lga", sa.String(length=120), nullable=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("postcode", sa.String(length=4), nullable=False),
        sa.Column("timing", sa.Text(), nullable=False),
        sa.Column("summary", sa.String(length=600), nullable=True),
        sa.Column("requirements", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("max_claims", sa.Integer(), nullable=False),
        sa.Column("claimed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), server_default="OPEN", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_wave_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "state IN ('NSW', 'VIC', 'QLD', 'SA', 'WA', 'TAS', 'NT', 'ACT')",
            name=op.f("ck_lead_state_valid"),
        ),
        sa.CheckConstraint(
            "status = 'OPEN' OR closed_at IS NOT NULL", name=op.f("ck_lead_closed_has_time")
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'FILLED', 'EXPIRED', 'WITHDRAWN')",
            name=op.f("ck_lead_status_valid"),
        ),
        sa.CheckConstraint(
            "timing IN ('ASAP', 'WITHIN_3_MONTHS', 'LATER', 'RESEARCHING')",
            name=op.f("ck_lead_timing_valid"),
        ),
        sa.CheckConstraint(
            "claimed_count >= 0 AND claimed_count <= max_claims",
            name=op.f("ck_lead_claimed_in_range"),
        ),
        sa.CheckConstraint("max_claims BETWEEN 1 AND 3", name=op.f("ck_lead_max_claims_range")),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["marketplace_category.id"],
            name=op.f("fk_lead_category_id_marketplace_category"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_lead_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
            name=op.f("fk_lead_project_id_project"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["referral_consent_id"],
            ["referral_consent.id"],
            name=op.f("fk_lead_referral_consent_id_referral_consent"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lead")),
        sa.UniqueConstraint(
            "referral_consent_id",
            "category_id",
            name=op.f("uq_lead_referral_consent_id_category_id"),
        ),
    )
    op.create_index("ix_lead_organisation", "lead", ["organisation_id", "project_id"], unique=False)
    op.create_index("ix_lead_status", "lead", ["status", "expires_at"], unique=False)
    op.create_table(
        "lead_contact",
        sa.Column("lead_id", sa.UUID(), nullable=False),
        sa.Column("contact", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fields_released", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["lead.id"], name=op.f("fk_lead_contact_lead_id_lead"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("lead_id", name=op.f("pk_lead_contact")),
    )
    op.create_table(
        "lead_match",
        sa.Column("lead_id", sa.UUID(), nullable=False),
        sa.Column("partner_organisation_id", sa.UUID(), nullable=False),
        sa.Column("score", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("score_breakdown", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("is_promoted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status", sa.Text(), server_default="MATCHED", nullable=False),
        sa.Column("offered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
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
            "status IN ('MATCHED', 'EXPIRED') OR offered_at IS NOT NULL",
            name=op.f("ck_lead_match_acted_on_was_offered"),
        ),
        sa.CheckConstraint(
            "status IN ('MATCHED', 'VIEWED', 'CLAIMED', 'CONTACTED', 'QUOTED', 'WON', 'LOST', 'EXPIRED', 'DECLINED')",
            name=op.f("ck_lead_match_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["lead.id"], name=op.f("fk_lead_match_lead_id_lead"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["partner_organisation_id"],
            ["partner_organisation.id"],
            name=op.f("fk_lead_match_partner_organisation_id_partner_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lead_match")),
        sa.UniqueConstraint(
            "lead_id",
            "partner_organisation_id",
            name=op.f("uq_lead_match_lead_id_partner_organisation_id"),
        ),
    )
    op.create_index("ix_lead_match_lead", "lead_match", ["lead_id", "rank"], unique=False)
    op.create_index(
        "ix_lead_match_partner",
        "lead_match",
        ["partner_organisation_id", "status", "offered_at"],
        unique=False,
    )
    op.create_table(
        "lead_claim",
        sa.Column("lead_match_id", sa.UUID(), nullable=False),
        sa.Column("lead_id", sa.UUID(), nullable=False),
        sa.Column("partner_organisation_id", sa.UUID(), nullable=False),
        sa.Column("claimed_by", sa.UUID(), nullable=True),
        sa.Column("included", sa.Boolean(), nullable=False),
        sa.Column("fee_cents", sa.BigInteger(), nullable=False),
        sa.Column("credit_ledger_entry_id", sa.UUID(), nullable=True),
        sa.Column("released_fields", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("released_contact", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("entitlement_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "NOT included OR fee_cents = 0", name=op.f("ck_lead_claim_included_is_free")
        ),
        sa.CheckConstraint("fee_cents >= 0", name=op.f("ck_lead_claim_fee_not_negative")),
        sa.ForeignKeyConstraint(
            ["claimed_by"],
            ["app_user.id"],
            name=op.f("fk_lead_claim_claimed_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["lead.id"], name=op.f("fk_lead_claim_lead_id_lead"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["lead_match_id"],
            ["lead_match.id"],
            name=op.f("fk_lead_claim_lead_match_id_lead_match"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["partner_organisation_id"],
            ["partner_organisation.id"],
            name=op.f("fk_lead_claim_partner_organisation_id_partner_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lead_claim")),
        sa.UniqueConstraint(
            "lead_id",
            "partner_organisation_id",
            name=op.f("uq_lead_claim_lead_id_partner_organisation_id"),
        ),
        sa.UniqueConstraint("lead_match_id", name=op.f("uq_lead_claim_lead_match_id")),
    )
    op.create_index(
        "ix_lead_claim_partner",
        "lead_claim",
        ["partner_organisation_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "lead_status_event",
        sa.Column("lead_match_id", sa.UUID(), nullable=False),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "from_status IS NULL OR from_status IN ('MATCHED', 'VIEWED', 'CLAIMED', 'CONTACTED', 'QUOTED', 'WON', 'LOST', 'EXPIRED', 'DECLINED')",
            name=op.f("ck_lead_status_event_from_status_valid"),
        ),
        sa.CheckConstraint(
            "to_status IN ('MATCHED', 'VIEWED', 'CLAIMED', 'CONTACTED', 'QUOTED', 'WON', 'LOST', 'EXPIRED', 'DECLINED')",
            name=op.f("ck_lead_status_event_to_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["app_user.id"],
            name=op.f("fk_lead_status_event_actor_id_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["lead_match_id"],
            ["lead_match.id"],
            name=op.f("fk_lead_status_event_lead_match_id_lead_match"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lead_status_event")),
    )
    op.create_index(
        "ix_lead_status_event_match",
        "lead_status_event",
        ["lead_match_id", "occurred_at"],
        unique=False,
    )
    op.add_column(
        "partner_organisation",
        sa.Column("paused", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("partner_organisation", sa.Column("max_open_leads", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f("ck_partner_organisation_max_open_leads_range"),
        "partner_organisation",
        "max_open_leads IS NULL OR max_open_leads BETWEEN 1 AND 500",
    )
    _notification_kinds(KINDS_NEW)
    op.execute(CONSENT_GUARD)
    op.execute(LEAD_PRICE_GUARD)
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
        )
    for table, privileges in PRIVILEGES.items():
        op.execute(f"GRANT {privileges} ON {table} TO {APP_ROLE}")
    _seed_permissions()
    # ### end Alembic commands ###


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permission WHERE permission_id IN "
        "(SELECT id FROM permission WHERE key = 'lead.manage')"
    )
    op.execute("DELETE FROM permission WHERE key = 'lead.manage'")
    op.execute("DELETE FROM notification WHERE kind IN ('LEAD_OFFERED', 'LEAD_CLAIMED')")
    _notification_kinds(KINDS_OLD)
    op.drop_constraint(op.f("ck_partner_organisation_max_open_leads_range"), "partner_organisation")
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("partner_organisation", "max_open_leads")
    op.drop_column("partner_organisation", "paused")
    op.drop_index("ix_lead_status_event_match", table_name="lead_status_event")
    op.drop_table("lead_status_event")
    op.drop_index("ix_lead_claim_partner", table_name="lead_claim")
    op.drop_table("lead_claim")
    op.drop_index("ix_lead_match_partner", table_name="lead_match")
    op.drop_index("ix_lead_match_lead", table_name="lead_match")
    op.drop_table("lead_match")
    op.drop_table("lead_contact")
    op.drop_index("ix_lead_status", table_name="lead")
    op.drop_index("ix_lead_organisation", table_name="lead")
    op.drop_table("lead")
    op.drop_index("ix_referral_consent_project", table_name="referral_consent")
    op.drop_index(op.f("ix_referral_consent_organisation_id"), table_name="referral_consent")
    op.drop_table("referral_consent")
    op.execute("DROP FUNCTION referral_consent_guard()")
    op.drop_index(op.f("ix_credit_ledger_entry_organisation_id"), table_name="credit_ledger_entry")
    op.drop_table("credit_ledger_entry")
    op.drop_index(
        "uq_lead_price_active_category",
        table_name="lead_price",
        postgresql_where=sa.text("deactivated_at IS NULL"),
    )
    op.drop_table("lead_price")
    op.execute("DROP FUNCTION lead_price_guard()")
    op.drop_table("consent_text_version")
    # ### end Alembic commands ###
