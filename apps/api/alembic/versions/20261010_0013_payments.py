"""Customer payments (Milestone 13): catalogue, prices, Stripe customers, payments,
subscriptions, invoices, the webhook event store, and paid professional reviews.

* ``product``, ``feature``, ``product_feature``: platform data synced from the reviewed
  ``app/modules/billing/catalogue.json`` on migrate (``python -m app.cli billing
  sync-catalogue``); read-only for the application role.
* ``price``: platform data that staff add at /admin/billing. Amount, currency, interval
  and product never change (trigger); prices are deactivated, never deleted.
* ``billing_customer``, ``payment``, ``subscription``, ``invoice_reference``: tenant tables
  with forced RLS, written by the server from verified Stripe webhooks.
* ``stripe_event``: platform, every verified webhook once (unique event id). The event never
  changes (trigger); only its processing columns do.
* ``billing_customer_organisation(customer)``: SECURITY DEFINER, the organisation a Stripe
  customer belongs to, so the webhook worker can bind that tenant.
* ``review_request`` gains ``payment_id`` and the ``PAYMENT_PENDING`` status: a priced review
  waits for payment before staff can assign it.
* New permissions ``billing.manage`` (organisation admins) and ``billing.configure``
  (platform ADMIN and SUPERADMIN).

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "approvalready_rw"
WRITE = "SELECT, INSERT, UPDATE"

# Privileges of the application role on the new tables (tests/test_rls.py keeps the map).
PRIVILEGES: dict[str, str] = {
    "product": "SELECT",
    "feature": "SELECT",
    "product_feature": "SELECT",
    "price": WRITE,
    "billing_customer": "SELECT, INSERT",
    "payment": WRITE,
    "subscription": WRITE,
    "invoice_reference": WRITE,
    "stripe_event": WRITE,
}

TENANT_TABLES = ("billing_customer", "payment", "subscription", "invoice_reference")

TENANT_PREDICATE = "organisation_id = nullif(current_setting('app.current_org', true), '')::uuid"

NEW_PERMISSIONS = {
    "billing.manage": "View billing, buy plans and manage payment details",
    "billing.configure": "Set prices and view payment events (staff)",
}
PERMISSION_ROLES = {
    "billing.manage": ("ORG_ADMIN", "PARTNER_ADMIN", "ADMIN", "SUPERADMIN"),
    "billing.configure": ("ADMIN", "SUPERADMIN"),
}

PRICE_GUARD = """
CREATE FUNCTION price_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'prices cannot be deleted; deactivate them';
    END IF;
    IF NEW.product_id IS DISTINCT FROM OLD.product_id
        OR NEW.amount_cents IS DISTINCT FROM OLD.amount_cents
        OR NEW.currency IS DISTINCT FROM OLD.currency
        OR NEW.interval IS DISTINCT FROM OLD.interval
        OR NEW.stripe_price_id IS DISTINCT FROM OLD.stripe_price_id THEN
        RAISE EXCEPTION 'a price never changes; add a new one';
    END IF;
    IF OLD.active = false AND NEW.active = true THEN
        RAISE EXCEPTION 'a deactivated price stays deactivated; add a new one';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER price_immutable
    BEFORE UPDATE OR DELETE ON price
    FOR EACH ROW EXECUTE FUNCTION price_guard();
"""

STRIPE_EVENT_GUARD = """
CREATE FUNCTION stripe_event_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'stripe events cannot be deleted';
    END IF;
    IF NEW.stripe_event_id IS DISTINCT FROM OLD.stripe_event_id
        OR NEW.type IS DISTINCT FROM OLD.type
        OR NEW.livemode IS DISTINCT FROM OLD.livemode
        OR NEW.stripe_created_at IS DISTINCT FROM OLD.stripe_created_at
        OR NEW.payload IS DISTINCT FROM OLD.payload
        OR NEW.received_at IS DISTINCT FROM OLD.received_at THEN
        RAISE EXCEPTION 'a stored stripe event never changes';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER stripe_event_immutable
    BEFORE UPDATE OR DELETE ON stripe_event
    FOR EACH ROW EXECUTE FUNCTION stripe_event_guard();
"""

CUSTOMER_FUNCTION = """
CREATE FUNCTION billing_customer_organisation(customer text)
RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
    SELECT c.organisation_id FROM billing_customer c WHERE c.stripe_customer_id = customer
$$;
REVOKE ALL ON FUNCTION billing_customer_organisation(text) FROM PUBLIC;
"""

REVIEW_STATUSES_OLD = (
    "'REVIEW_REQUESTED', 'ASSIGNED', 'IN_REVIEW', 'CHANGES_REQUIRED', 'APPROVED', "
    "'COMPLETED', 'CANCELLED'"
)
REVIEW_STATUSES_NEW = "'PAYMENT_PENDING', " + REVIEW_STATUSES_OLD
OPEN_OLD = "'REVIEW_REQUESTED', 'ASSIGNED', 'IN_REVIEW', 'CHANGES_REQUIRED'"
OPEN_NEW = "'PAYMENT_PENDING', " + OPEN_OLD


def _review_statuses(statuses: str, open_statuses: str) -> None:
    op.drop_constraint(op.f("ck_review_request_status_valid"), "review_request", type_="check")
    op.create_check_constraint(
        op.f("ck_review_request_status_valid"), "review_request", f"status IN ({statuses})"
    )
    op.drop_index("uq_review_request_open_project", table_name="review_request")
    op.create_index(
        "uq_review_request_open_project",
        "review_request",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text(f"status IN ({open_statuses})"),
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
    op.create_table(
        "feature",
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("default_limit", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
            "default_limit IS NULL OR default_limit >= 0",
            name=op.f("ck_feature_limit_not_negative"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feature")),
        sa.UniqueConstraint("key", name=op.f("uq_feature_key")),
    )
    op.create_table(
        "product",
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("vertical", sa.Text(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
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
            "kind IN ('ONE_OFF', 'SAAS', 'REVIEW', 'PARTNER_PLAN', 'LEAD', 'CREDIT_PACK')",
            name=op.f("ck_product_kind_valid"),
        ),
        sa.CheckConstraint(
            "vertical IS NULL OR vertical IN ('PLANNING', 'VESSEL', 'BUSINESS', 'GRANT', 'SELL', 'RENT')",
            name=op.f("ck_product_vertical_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product")),
        sa.UniqueConstraint("key", name=op.f("uq_product_key")),
    )
    op.create_table(
        "price",
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="AUD", nullable=False),
        sa.Column("interval", sa.Text(), nullable=False),
        sa.Column("stripe_price_id", sa.String(length=255), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_price_currency_code")),
        sa.CheckConstraint(
            "interval IN ('ONE_TIME', 'MONTH', 'YEAR')", name=op.f("ck_price_interval_valid")
        ),
        sa.CheckConstraint("amount_cents > 0", name=op.f("ck_price_amount_positive")),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_price_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["product.id"],
            name=op.f("fk_price_product_id_product"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price")),
    )
    op.create_index("ix_price_product_id", "price", ["product_id"], unique=False)
    op.create_index(
        "uq_price_one_active",
        "price",
        ["product_id", "interval"],
        unique=True,
        postgresql_where=sa.text("active"),
    )
    op.create_table(
        "product_feature",
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("feature_id", sa.UUID(), nullable=False),
        sa.Column("limit_value", sa.Integer(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "limit_value IS NULL OR limit_value >= 0",
            name=op.f("ck_product_feature_limit_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["feature_id"],
            ["feature.id"],
            name=op.f("fk_product_feature_feature_id_feature"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["product.id"],
            name=op.f("fk_product_feature_product_id_product"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_feature")),
        sa.UniqueConstraint(
            "product_id", "feature_id", name=op.f("uq_product_feature_product_id_feature_id")
        ),
    )
    op.create_table(
        "billing_customer",
        sa.Column("stripe_customer_id", sa.String(length=255), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_billing_customer_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_billing_customer_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_customer")),
        sa.UniqueConstraint("organisation_id", name=op.f("uq_billing_customer_organisation_id")),
        sa.UniqueConstraint(
            "stripe_customer_id", name=op.f("uq_billing_customer_stripe_customer_id")
        ),
    )
    op.create_index(
        op.f("ix_billing_customer_organisation_id"),
        "billing_customer",
        ["organisation_id"],
        unique=False,
    )
    op.create_table(
        "invoice_reference",
        sa.Column("stripe_invoice_id", sa.String(length=255), nullable=False),
        sa.Column("stripe_subscription_id", sa.String(length=255), nullable=True),
        sa.Column("number", sa.String(length=100), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("amount_due_cents", sa.BigInteger(), nullable=False),
        sa.Column("amount_paid_cents", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("hosted_invoice_url", sa.String(length=2000), nullable=True),
        sa.Column("invoice_pdf_url", sa.String(length=2000), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stripe_event_at", sa.DateTime(timezone=True), nullable=False),
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
            "status IN ('DRAFT', 'OPEN', 'PAID', 'VOID', 'UNCOLLECTIBLE')",
            name=op.f("ck_invoice_reference_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_invoice_reference_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_reference")),
        sa.UniqueConstraint(
            "stripe_invoice_id", name=op.f("uq_invoice_reference_stripe_invoice_id")
        ),
    )
    op.create_index(
        "ix_invoice_reference_issued_at",
        "invoice_reference",
        ["organisation_id", "issued_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_invoice_reference_organisation_id"),
        "invoice_reference",
        ["organisation_id"],
        unique=False,
    )
    op.create_table(
        "payment",
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("price_id", sa.UUID(), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("subject_type", sa.String(length=40), nullable=True),
        sa.Column("subject_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.Text(), server_default="PENDING", nullable=False),
        sa.Column("stripe_checkout_session_id", sa.String(length=255), nullable=True),
        sa.Column("stripe_payment_intent_id", sa.String(length=255), nullable=True),
        sa.Column("refunded_cents", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
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
            "purpose IN ('REVIEW', 'PRODUCT')", name=op.f("ck_payment_purpose_valid")
        ),
        sa.CheckConstraint(
            "status <> 'PAID' OR paid_at IS NOT NULL", name=op.f("ck_payment_paid_has_time")
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PAID', 'FAILED', 'CANCELLED', 'REFUNDED', 'PARTIALLY_REFUNDED')",
            name=op.f("ck_payment_status_valid"),
        ),
        sa.CheckConstraint("amount_cents > 0", name=op.f("ck_payment_amount_positive")),
        sa.CheckConstraint(
            "refunded_cents >= 0 AND refunded_cents <= amount_cents",
            name=op.f("ck_payment_refund_in_range"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_payment_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_payment_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["price_id"], ["price.id"], name=op.f("fk_payment_price_id_price"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["product.id"],
            name=op.f("fk_payment_product_id_product"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment")),
        sa.UniqueConstraint("organisation_id", "id", name=op.f("uq_payment_organisation_id_id")),
    )
    op.create_index(
        op.f("ix_payment_organisation_id"), "payment", ["organisation_id"], unique=False
    )
    op.create_index(
        "ix_payment_stripe_payment_intent_id", "payment", ["stripe_payment_intent_id"], unique=False
    )
    op.create_index("ix_payment_subject_id", "payment", ["subject_id"], unique=False)
    op.create_table(
        "stripe_event",
        sa.Column("stripe_event_id", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("livemode", sa.Boolean(), nullable=False),
        sa.Column("stripe_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("organisation_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.Text(), server_default="RECEIVED", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "status IN ('RECEIVED', 'PROCESSED', 'IGNORED', 'FAILED')",
            name=op.f("ck_stripe_event_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_stripe_event_organisation_id_organisation"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stripe_event")),
        sa.UniqueConstraint("stripe_event_id", name=op.f("uq_stripe_event_stripe_event_id")),
    )
    op.create_index("ix_stripe_event_received_at", "stripe_event", ["received_at"], unique=False)
    op.create_index(
        "ix_stripe_event_status", "stripe_event", ["status", "received_at"], unique=False
    )
    op.create_table(
        "subscription",
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("price_id", sa.UUID(), nullable=False),
        sa.Column("stripe_subscription_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cancel_at_period_end", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("past_due_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stripe_event_at", sa.DateTime(timezone=True), nullable=False),
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
            "status IN ('INCOMPLETE', 'INCOMPLETE_EXPIRED', 'TRIALING', 'ACTIVE', 'PAST_DUE', 'CANCELED', 'UNPAID', 'PAUSED')",
            name=op.f("ck_subscription_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_subscription_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["price_id"],
            ["price.id"],
            name=op.f("fk_subscription_price_id_price"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["product.id"],
            name=op.f("fk_subscription_product_id_product"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscription")),
        sa.UniqueConstraint(
            "organisation_id", "id", name=op.f("uq_subscription_organisation_id_id")
        ),
        sa.UniqueConstraint(
            "stripe_subscription_id", name=op.f("uq_subscription_stripe_subscription_id")
        ),
    )
    op.create_index(
        op.f("ix_subscription_organisation_id"), "subscription", ["organisation_id"], unique=False
    )
    op.add_column("review_request", sa.Column("payment_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_review_request_organisation_id_payment"),
        "review_request",
        "payment",
        ["organisation_id", "payment_id"],
        ["organisation_id", "id"],
    )
    op.create_check_constraint(
        op.f("ck_review_request_pending_has_payment"),
        "review_request",
        "status <> 'PAYMENT_PENDING' OR payment_id IS NOT NULL",
    )
    _review_statuses(REVIEW_STATUSES_NEW, OPEN_NEW)
    op.execute(PRICE_GUARD)
    op.execute(STRIPE_EVENT_GUARD)
    op.execute(CUSTOMER_FUNCTION)
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
        )
    for table, privileges in PRIVILEGES.items():
        op.execute(f"GRANT {privileges} ON {table} TO {APP_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION billing_customer_organisation(text) TO {APP_ROLE}")
    _seed_permissions()


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permission WHERE permission_id IN "
        "(SELECT id FROM permission WHERE key IN ('billing.manage', 'billing.configure'))"
    )
    op.execute("DELETE FROM permission WHERE key IN ('billing.manage', 'billing.configure')")
    op.execute("DROP FUNCTION billing_customer_organisation(text)")
    op.execute("DROP TRIGGER stripe_event_immutable ON stripe_event")
    op.execute("DROP FUNCTION stripe_event_guard()")
    op.execute("DROP TRIGGER price_immutable ON price")
    op.execute("DROP FUNCTION price_guard()")
    # Reviews waiting for payment can't exist without payments: cancel them.
    op.execute(
        "UPDATE review_request SET status = 'CANCELLED', closed_at = now() "
        "WHERE status = 'PAYMENT_PENDING'"
    )
    _review_statuses(REVIEW_STATUSES_OLD, OPEN_OLD)
    op.drop_constraint(
        op.f("ck_review_request_pending_has_payment"), "review_request", type_="check"
    )
    op.drop_constraint(
        op.f("fk_review_request_organisation_id_payment"), "review_request", type_="foreignkey"
    )
    op.drop_column("review_request", "payment_id")
    op.drop_index(op.f("ix_subscription_organisation_id"), table_name="subscription")
    op.drop_table("subscription")
    op.drop_index("ix_stripe_event_status", table_name="stripe_event")
    op.drop_index("ix_stripe_event_received_at", table_name="stripe_event")
    op.drop_table("stripe_event")
    op.drop_index("ix_payment_subject_id", table_name="payment")
    op.drop_index("ix_payment_stripe_payment_intent_id", table_name="payment")
    op.drop_index(op.f("ix_payment_organisation_id"), table_name="payment")
    op.drop_table("payment")
    op.drop_index(op.f("ix_invoice_reference_organisation_id"), table_name="invoice_reference")
    op.drop_index("ix_invoice_reference_issued_at", table_name="invoice_reference")
    op.drop_table("invoice_reference")
    op.drop_index(op.f("ix_billing_customer_organisation_id"), table_name="billing_customer")
    op.drop_table("billing_customer")
    op.drop_table("product_feature")
    op.drop_index("uq_price_one_active", table_name="price", postgresql_where=sa.text("active"))
    op.drop_index("ix_price_product_id", table_name="price")
    op.drop_table("price")
    op.drop_table("product")
    op.drop_table("feature")
