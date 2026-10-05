"""Identity, tenancy, RBAC and audit (Milestone 2).

Creates users, credentials, sessions, one-time tokens, organisations, memberships,
invitations, roles/permissions (seeded), and the append-only hash-chained audit log.

The role/permission seed is a frozen snapshot of app/modules/tenancy/rbac.py at the time
of writing; tests/test_rbac.py asserts the database matches the module. Changing a role's
permissions means a new migration.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISSIONS = {
    "org.read": "View the organisation",
    "org.update": "Edit organisation details",
    "org.members.read": "View organisation members",
    "org.members.manage": "Change member roles and remove members",
    "org.invitations.manage": "Invite people to the organisation",
    "org.audit.read": "View the organisation's audit log",
    "project.read": "View projects",
    "project.write": "Create and edit projects",
    "review.perform": "Perform professional reviews",
    "lead.read": "View anonymised leads",
    "lead.claim": "Claim leads",
    "source.verify": "Verify regulatory source references",
    "rule.publish": "Publish rule versions",
    "platform.users.read": "View any user (staff)",
    "platform.organisations.read": "View any organisation (staff)",
    "platform.audit.read": "View and verify the platform audit log",
    "platform.roles.manage": "Grant platform roles",
}

_ORG_ADMIN = [
    "org.audit.read",
    "org.invitations.manage",
    "org.members.manage",
    "org.members.read",
    "org.read",
    "org.update",
]
_STAFF = [
    "org.members.read",
    "org.read",
    "platform.organisations.read",
    "platform.users.read",
    "source.verify",
]
_ADMIN = sorted({*_STAFF, *_ORG_ADMIN, "platform.audit.read", "rule.publish"})

# key: (scope, description, organisation kinds it may be granted in, permissions)
ROLES = {
    "CUSTOMER": (
        "ORG",
        "Customer using ApprovalReady products",
        ["PERSONAL", "BUSINESS"],
        ["org.members.read", "org.read", "project.read", "project.write"],
    ),
    "ORG_ADMIN": (
        "ORG",
        "Manages an organisation's details and members",
        ["PERSONAL", "BUSINESS", "PROFESSIONAL_PRACTICE"],
        _ORG_ADMIN,
    ),
    "PROFESSIONAL": (
        "ORG",
        "Professional reviewer in a practice",
        ["PROFESSIONAL_PRACTICE"],
        ["org.members.read", "org.read", "project.read", "review.perform"],
    ),
    "PARTNER_USER": (
        "ORG",
        "Partner staff member",
        ["PARTNER"],
        ["lead.claim", "lead.read", "org.members.read", "org.read"],
    ),
    "PARTNER_ADMIN": (
        "ORG",
        "Partner account administrator",
        ["PARTNER"],
        sorted({"lead.claim", "lead.read", *_ORG_ADMIN}),
    ),
    "STAFF": ("PLATFORM", "ApprovalReady staff", ["PLATFORM_ADMIN"], _STAFF),
    "ADMIN": ("PLATFORM", "ApprovalReady administrator", ["PLATFORM_ADMIN"], _ADMIN),
    "SUPERADMIN": (
        "PLATFORM",
        "ApprovalReady super administrator",
        ["PLATFORM_ADMIN"],
        sorted({*_ADMIN, "platform.roles.manage"}),
    ),
}

# Audit rows are append-only. Triggers apply to every role, including the table owner.
AUDIT_IMMUTABLE_SQL = """
CREATE FUNCTION audit_event_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'audit_event is append-only (% rejected)', TG_OP
    USING ERRCODE = 'insufficient_privilege';
END;
$$;
CREATE TRIGGER audit_event_no_update_delete BEFORE UPDATE OR DELETE ON audit_event
  FOR EACH ROW EXECUTE FUNCTION audit_event_immutable();
CREATE TRIGGER audit_event_no_truncate BEFORE TRUNCATE ON audit_event
  FOR EACH STATEMENT EXECUTE FUNCTION audit_event_immutable();
"""

# A role may only be granted in organisation kinds it allows (e.g. platform roles only in
# the PLATFORM_ADMIN organisation). The service checks first; this is the backstop.
MEMBER_ROLE_KIND_SQL = """
CREATE FUNCTION member_role_kind_check() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  org_kind text;
  allowed text[];
BEGIN
  SELECT o.kind INTO org_kind
    FROM organisation_member m JOIN organisation o ON o.id = m.organisation_id
   WHERE m.id = NEW.organisation_member_id;
  SELECT r.allowed_org_kinds INTO allowed FROM role r WHERE r.id = NEW.role_id;
  IF NOT (org_kind = ANY (allowed)) THEN
    RAISE EXCEPTION 'role % cannot be granted in a % organisation', NEW.role_id, org_kind
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER member_role_kind_check BEFORE INSERT OR UPDATE ON member_role
  FOR EACH ROW EXECUTE FUNCTION member_role_kind_check();
"""


def _seed_rbac() -> None:
    conn = op.get_bind()
    for key, description in PERMISSIONS.items():
        conn.execute(
            sa.text(
                "INSERT INTO permission (id, key, description) "
                "VALUES (gen_random_uuid(), :key, :description)"
            ),
            {"key": key, "description": description},
        )
    for key, (scope, description, kinds, permissions) in ROLES.items():
        conn.execute(
            sa.text(
                "INSERT INTO role (id, key, scope, description, allowed_org_kinds) "
                "VALUES (gen_random_uuid(), :key, :scope, :description, :kinds)"
            ),
            {"key": key, "scope": scope, "description": description, "kinds": kinds},
        )
        conn.execute(
            sa.text(
                "INSERT INTO role_permission (role_id, permission_id) "
                "SELECT r.id, p.id FROM role r, permission p "
                "WHERE r.key = :key AND p.key = ANY(:permissions)"
            ),
            {"key": key, "permissions": permissions},
        )


def upgrade() -> None:
    op.create_table(
        "app_user",
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.Text(), server_default="ACTIVE", nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locale", sa.Text(), server_default="en-AU", nullable=False),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'LOCKED', 'SUSPENDED', 'DELETION_REQUESTED')",
            name=op.f("ck_app_user_status_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_user")),
        sa.UniqueConstraint("email", name=op.f("uq_app_user_email")),
    )
    op.create_table(
        "audit_event",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("organisation_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=True),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("prev_hash", sa.LargeBinary(), nullable=True),
        sa.Column("hash", sa.LargeBinary(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_event")),
        sa.UniqueConstraint("hash", name=op.f("uq_audit_event_hash")),
        sa.UniqueConstraint("seq", name=op.f("uq_audit_event_seq")),
    )
    op.create_index(
        "ix_audit_event_actor_user_id_seq", "audit_event", ["actor_user_id", "seq"], unique=False
    )
    op.create_index(
        "ix_audit_event_organisation_id_seq",
        "audit_event",
        ["organisation_id", "seq"],
        unique=False,
    )
    op.create_table(
        "permission",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_permission")),
        sa.UniqueConstraint("key", name=op.f("uq_permission_key")),
    )
    op.create_table(
        "role",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("allowed_org_kinds", postgresql.ARRAY(sa.Text()), nullable=False),
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
        sa.CheckConstraint("scope IN ('ORG', 'PLATFORM')", name=op.f("ck_role_scope_valid")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_role")),
        sa.UniqueConstraint("key", name=op.f("uq_role_key")),
    )
    op.create_table(
        "auth_identity",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
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
            "provider IN ('GOOGLE', 'MICROSOFT', 'PASSKEY')",
            name=op.f("ck_auth_identity_provider_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_auth_identity_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_identity")),
        sa.UniqueConstraint("provider", "subject", name=op.f("uq_auth_identity_provider_subject")),
    )
    op.create_index(op.f("ix_auth_identity_user_id"), "auth_identity", ["user_id"], unique=False)
    op.create_table(
        "one_time_token",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
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
            "purpose IN ('EMAIL_VERIFY', 'PASSWORD_RESET')",
            name=op.f("ck_one_time_token_purpose_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_one_time_token_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_one_time_token")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_one_time_token_token_hash")),
    )
    op.create_index(op.f("ix_one_time_token_user_id"), "one_time_token", ["user_id"], unique=False)
    op.create_table(
        "organisation",
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("abn", sa.String(length=11), nullable=True),
        sa.Column("status", sa.Text(), server_default="ACTIVE", nullable=False),
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
        sa.CheckConstraint(
            "abn IS NULL OR abn ~ '^[0-9]{11}$'", name=op.f("ck_organisation_abn_format")
        ),
        sa.CheckConstraint(
            "kind IN ('PERSONAL', 'BUSINESS', 'PROFESSIONAL_PRACTICE', 'PARTNER', 'PLATFORM_ADMIN')",
            name=op.f("ck_organisation_kind_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'SUSPENDED')", name=op.f("ck_organisation_status_valid")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_organisation_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organisation")),
    )
    op.create_table(
        "password_credential",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "password_changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_password_credential_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_password_credential")),
        sa.UniqueConstraint("user_id", name=op.f("uq_password_credential_user_id")),
    )
    op.create_table(
        "role_permission",
        sa.Column("role_id", sa.UUID(), nullable=False),
        sa.Column("permission_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["permission_id"],
            ["permission.id"],
            name=op.f("fk_role_permission_permission_id_permission"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["role.id"],
            name=op.f("fk_role_permission_role_id_role"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("role_id", "permission_id", name=op.f("pk_role_permission")),
    )
    op.create_table(
        "auth_session",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("previous_token_hash", sa.LargeBinary(), nullable=True),
        sa.Column("previous_token_valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("surface", sa.Text(), server_default="app", nullable=False),
        sa.Column("active_organisation_id", sa.UUID(), nullable=True),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.Text(), nullable=True),
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
            "surface IN ('public', 'app', 'partners', 'review')",
            name=op.f("ck_auth_session_surface_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["active_organisation_id"],
            ["organisation.id"],
            name=op.f("fk_auth_session_active_organisation_id_organisation"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_auth_session_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_session")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_auth_session_token_hash")),
    )
    op.create_index(
        "ix_auth_session_previous_token_hash",
        "auth_session",
        ["previous_token_hash"],
        unique=True,
        postgresql_where=sa.text("previous_token_hash IS NOT NULL"),
    )
    op.create_index(op.f("ix_auth_session_user_id"), "auth_session", ["user_id"], unique=False)
    op.create_table(
        "organisation_invitation",
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("role_keys", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by", sa.UUID(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["accepted_by"],
            ["app_user.id"],
            name=op.f("fk_organisation_invitation_accepted_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_organisation_invitation_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_organisation_invitation_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organisation_invitation")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_organisation_invitation_token_hash")),
    )
    op.create_index(
        op.f("ix_organisation_invitation_organisation_id"),
        "organisation_invitation",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        "uq_organisation_invitation_open",
        "organisation_invitation",
        ["organisation_id", "email"],
        unique=True,
        postgresql_where=sa.text("accepted_at IS NULL AND revoked_at IS NULL"),
    )
    op.create_table(
        "organisation_member",
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.Text(), server_default="ACTIVE", nullable=False),
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
            "status IN ('ACTIVE', 'REMOVED')", name=op.f("ck_organisation_member_status_valid")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_organisation_member_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisation.id"],
            name=op.f("fk_organisation_member_organisation_id_organisation"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name=op.f("fk_organisation_member_user_id_app_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organisation_member")),
        sa.UniqueConstraint(
            "organisation_id",
            "user_id",
            name=op.f("uq_organisation_member_organisation_id_user_id"),
        ),
    )
    op.create_index(
        op.f("ix_organisation_member_user_id"), "organisation_member", ["user_id"], unique=False
    )
    op.create_table(
        "member_role",
        sa.Column("organisation_member_id", sa.UUID(), nullable=False),
        sa.Column("role_id", sa.UUID(), nullable=False),
        sa.Column("granted_by", sa.UUID(), nullable=True),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"],
            ["app_user.id"],
            name=op.f("fk_member_role_granted_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_member_id"],
            ["organisation_member.id"],
            name=op.f("fk_member_role_organisation_member_id_organisation_member"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["role.id"], name=op.f("fk_member_role_role_id_role"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("organisation_member_id", "role_id", name=op.f("pk_member_role")),
    )
    op.execute(AUDIT_IMMUTABLE_SQL)
    op.execute(MEMBER_ROLE_KIND_SQL)
    _seed_rbac()


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS member_role_kind_check ON member_role")
    op.execute("DROP FUNCTION IF EXISTS member_role_kind_check()")
    op.execute("DROP TRIGGER IF EXISTS audit_event_no_truncate ON audit_event")
    op.execute("DROP TRIGGER IF EXISTS audit_event_no_update_delete ON audit_event")
    op.execute("DROP FUNCTION IF EXISTS audit_event_immutable()")
    op.drop_table("member_role")
    op.drop_index(op.f("ix_organisation_member_user_id"), table_name="organisation_member")
    op.drop_table("organisation_member")
    op.drop_index(
        "uq_organisation_invitation_open",
        table_name="organisation_invitation",
        postgresql_where=sa.text("accepted_at IS NULL AND revoked_at IS NULL"),
    )
    op.drop_index(
        op.f("ix_organisation_invitation_organisation_id"), table_name="organisation_invitation"
    )
    op.drop_table("organisation_invitation")
    op.drop_index(op.f("ix_auth_session_user_id"), table_name="auth_session")
    op.drop_index(
        "ix_auth_session_previous_token_hash",
        table_name="auth_session",
        postgresql_where=sa.text("previous_token_hash IS NOT NULL"),
    )
    op.drop_table("auth_session")
    op.drop_table("role_permission")
    op.drop_table("password_credential")
    op.drop_table("organisation")
    op.drop_index(op.f("ix_one_time_token_user_id"), table_name="one_time_token")
    op.drop_table("one_time_token")
    op.drop_index(op.f("ix_auth_identity_user_id"), table_name="auth_identity")
    op.drop_table("auth_identity")
    op.drop_table("role")
    op.drop_table("permission")
    op.drop_index("ix_audit_event_organisation_id_seq", table_name="audit_event")
    op.drop_index("ix_audit_event_actor_user_id_seq", table_name="audit_event")
    op.drop_table("audit_event")
    op.drop_table("app_user")
