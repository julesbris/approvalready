"""Deleting closed accounts' workspaces (Milestone 29).

The Privacy Policy says that within 30 days of an account closing we delete the projects,
answers and files in its personal workspace, keeping only what the law requires (payment
records) and the security log. Milestone 19 queued a request for staff to do it by hand;
this makes it automatic.

* ``privacy_request.organisation_id``: the closed personal workspace a deletion request is
  about (backfilled for accounts closed before this milestone), and ``purged_at``: when the
  workspace was deleted.
* ``purge_closed_workspace(org, tables)``: SECURITY DEFINER function that deletes one closed
  personal workspace's rows from the listed tenant tables. The application role has no
  DELETE on most of those tables (several are append-only records), so this is its only way
  to remove them, and the function refuses anything but a closed personal workspace and
  never touches payment records.
* ``lead.project_id`` and ``lead.referral_consent_id`` become nullable (``ON DELETE SET
  NULL``): a referral a partner received is that partner's record and stays with them; only
  its link to the deleted project goes.
* ``referral_consent_guard`` lets the purge function delete a consent; nothing else can.

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "approvalready_rw"

PURGE_FUNCTION = """
CREATE FUNCTION purge_closed_workspace(p_org uuid, p_tables text[])
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    t text;
    n bigint;
    counts jsonb := '{}'::jsonb;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM organisation
         WHERE id = p_org AND kind = 'PERSONAL' AND deleted_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'only a closed personal workspace can be deleted';
    END IF;
    FOREACH t IN ARRAY p_tables LOOP
        -- Kept for tax law; mirrors KEPT_TABLES in app/modules/privacy/purge.py.
        IF t = ANY (ARRAY['billing_customer', 'payment', 'subscription', 'invoice_reference',
                          'refund', 'credit_ledger_entry']) THEN
            RAISE EXCEPTION 'table % is kept (payment records)', t;
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
             WHERE schemaname = 'public' AND tablename = t AND policyname = 'tenant_isolation'
        ) THEN
            RAISE EXCEPTION 'table % is not workspace data', t;
        END IF;
    END LOOP;

    -- Row-level security is forced on the table owner too.
    PERFORM set_config('app.current_org', p_org::text, true);
    PERFORM set_config('app.purge_org', p_org::text, true);

    -- Referrals partners received stay with them, without the customer's own details.
    DELETE FROM lead_contact WHERE lead_id IN (SELECT id FROM lead WHERE organisation_id = p_org);
    UPDATE lead SET project_id = NULL, referral_consent_id = NULL, summary = NULL
     WHERE organisation_id = p_org;

    FOREACH t IN ARRAY p_tables LOOP
        EXECUTE format('DELETE FROM %I WHERE organisation_id = $1', t) USING p_org;
        GET DIAGNOSTICS n = ROW_COUNT;
        IF n > 0 THEN
            counts := counts || jsonb_build_object(t, n);
        END IF;
    END LOOP;

    PERFORM set_config('app.purge_org', '', true);
    RETURN counts;
END;
$$;
REVOKE ALL ON FUNCTION purge_closed_workspace(uuid, text[]) FROM PUBLIC;
"""

# As in 0015, plus: the purge function (running as the owner, for the workspace it is
# deleting) may delete a consent.
CONSENT_GUARD = """
CREATE OR REPLACE FUNCTION referral_consent_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF current_user <> session_user
            AND current_setting('app.purge_org', true) = OLD.organisation_id::text THEN
            RETURN OLD;
        END IF;
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
"""

CONSENT_GUARD_OLD = """
CREATE OR REPLACE FUNCTION referral_consent_guard() RETURNS trigger
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
"""


def _lead_fk(column: str, target: str, ondelete: str) -> None:
    name = f"fk_lead_{column}_{target}"
    op.drop_constraint(name, "lead", type_="foreignkey")
    op.create_foreign_key(name, "lead", target, [column], ["id"], ondelete=ondelete)


def upgrade() -> None:
    op.add_column("privacy_request", sa.Column("organisation_id", sa.UUID(), nullable=True))
    op.add_column(
        "privacy_request", sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_privacy_request_organisation_id_organisation"),
        "privacy_request",
        "organisation",
        ["organisation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Accounts closed before this milestone: their personal workspace.
    op.execute(
        """
        UPDATE privacy_request r SET organisation_id = o.id
          FROM organisation_member m JOIN organisation o ON o.id = m.organisation_id
         WHERE r.source = 'ACCOUNT_CLOSED' AND r.organisation_id IS NULL
           AND m.user_id = r.user_id AND o.kind = 'PERSONAL'
        """
    )

    op.alter_column("lead", "project_id", nullable=True)
    op.alter_column("lead", "referral_consent_id", nullable=True)
    _lead_fk("project_id", "project", "SET NULL")
    _lead_fk("referral_consent_id", "referral_consent", "SET NULL")

    op.execute(CONSENT_GUARD)
    op.execute(PURGE_FUNCTION)
    op.execute(f"GRANT EXECUTE ON FUNCTION purge_closed_workspace(uuid, text[]) TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION purge_closed_workspace(uuid, text[])")
    op.execute(CONSENT_GUARD_OLD)
    # The columns stay nullable: referrals detached from a deleted workspace can't point
    # anywhere again, and their quotes and messages can't be deleted.
    _lead_fk("referral_consent_id", "referral_consent", "CASCADE")
    _lead_fk("project_id", "project", "CASCADE")
    op.drop_constraint(
        op.f("fk_privacy_request_organisation_id_organisation"),
        "privacy_request",
        type_="foreignkey",
    )
    op.drop_column("privacy_request", "purged_at")
    op.drop_column("privacy_request", "organisation_id")
