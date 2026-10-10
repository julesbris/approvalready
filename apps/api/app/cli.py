"""Operator commands (run inside the API container).

    python -m app.cli grant-platform-role --email ops@example.com --role SUPERADMIN
    python -m app.cli platform-access [--email ops@example.com]  # who can open /admin
    python -m app.cli verify-audit
    python -m app.cli auth reset-mfa --email someone@example.com  # lost phone and codes
    python -m app.cli provision-db-role       # after migrations, as the owner
    python -m app.cli questionnaires sync     # publish changed bundled definitions
    python -m app.cli documents sync-templates  # publish changed report templates
    python -m app.cli ai sync-prompts         # publish changed AI prompts
    python -m app.cli rules load-pack planning_qld_cairns --email staff@example.com [--publish]

Platform roles can only be granted in the PLATFORM_ADMIN organisation, which is created on
first use. There is deliberately no HTTP endpoint that bootstraps the first super admin.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys

from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.core.resources import create_resources
from app.modules.ai import prompts as ai_prompts
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.billing import catalogue as billing_catalogue
from app.modules.documents import templates as document_templates
from app.modules.identity import mfa
from app.modules.identity.models import AppUser
from app.modules.identity.service import get_user_by_email
from app.modules.marketplace import service as marketplace
from app.modules.questionnaires import service as questionnaires
from app.modules.questionnaires.definition import load_bundled
from app.modules.regulatory.service import Actor
from app.modules.rules import packs
from app.modules.tenancy import service as tenancy
from app.modules.tenancy.models import (
    MemberRole,
    Organisation,
    OrganisationKind,
    OrganisationMember,
)
from app.modules.tenancy.rbac import Perm, RoleKey

PLATFORM_ORG_NAME = "ApprovalReady"
CLI_META = RequestMeta(ip=None, user_agent="app.cli")


async def grant_platform_role(email: str, role: RoleKey, settings: Settings | None = None) -> int:
    resources = create_resources(settings or get_settings())
    try:
        async with resources.session_factory() as db:
            user = await get_user_by_email(db, email)
            if user is None or user.email_verified_at is None:
                print(f"No verified user with email {email}", file=sys.stderr)
                return 1
            org = (
                await db.execute(
                    select(Organisation).where(
                        Organisation.kind == OrganisationKind.PLATFORM_ADMIN,
                        Organisation.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if org is None:
                if role != RoleKey.SUPERADMIN:
                    print("No platform organisation yet: grant SUPERADMIN first", file=sys.stderr)
                    return 1
                # Creates the organisation with this user as its first SUPERADMIN.
                org = await tenancy.create_organisation(
                    db,
                    creator=user,
                    kind=OrganisationKind.PLATFORM_ADMIN,
                    name=PLATFORM_ORG_NAME,
                    meta=CLI_META,
                )
            member = (
                await db.execute(
                    select(OrganisationMember).where(
                        OrganisationMember.organisation_id == org.id,
                        OrganisationMember.user_id == user.id,
                    )
                )
            ).scalar_one_or_none()
            if member is None:
                member = OrganisationMember(organisation_id=org.id, user_id=user.id)
                db.add(member)
                await db.flush()
            member.status = "ACTIVE"
            roles = await tenancy.roles_by_key(db, [role])
            existing = await tenancy.member_role_keys(db, member.id)
            if role not in existing:
                db.add(MemberRole(organisation_member_id=member.id, role_id=roles[role].id))
            await audit.record(
                db,
                "platform.role_granted",
                organisation_id=org.id,
                meta=CLI_META,
                target_type="organisation_member",
                target_id=member.id,
                details={"user_id": str(user.id), "role": role, "via": "cli"},
            )
            await db.commit()
            print(f"{email} now has {role} in the platform organisation ({org.id})")
            print(
                f"Next: sign in as {email} and choose {org.name} in the organisation menu at the"
                " top of the page. The admin pages only open while it is the active organisation."
            )
            return 0
    finally:
        await resources.close()


# What the admin area's pages check for (apps/web/src/app/admin), in display order.
ADMIN_PAGES = {
    "/admin/sources": Perm.SOURCE_MANAGE,
    "/admin/rules": Perm.RULE_AUTHOR,
    "/admin/accounts": Perm.PLATFORM_USERS_READ,
    "/admin/ops": Perm.PLATFORM_AUDIT_READ,
}


async def platform_access(email: str | None, settings: Settings | None = None) -> int:
    """Explain who can open the admin area: one account's organisations, roles and admin pages,
    or (without an email) everyone in the platform organisation. Changes nothing."""
    settings = settings or get_settings()
    resources = create_resources(settings)
    try:
        async with resources.session_factory() as db:
            platform = (
                await db.execute(
                    select(Organisation).where(
                        Organisation.kind == OrganisationKind.PLATFORM_ADMIN,
                        Organisation.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if email is None:
                if platform is None:
                    print("There is no platform organisation yet: run grant-platform-role first")
                    return 1
                members = (
                    await db.execute(
                        select(AppUser.email, OrganisationMember)
                        .join(AppUser, AppUser.id == OrganisationMember.user_id)
                        .where(OrganisationMember.organisation_id == platform.id)
                        .order_by(AppUser.email)
                    )
                ).all()
                print(f"Platform organisation: {platform.name} ({platform.status})")
                for member_email, member in members:
                    keys = await tenancy.member_role_keys(db, member.id)
                    print(f"  {member_email}: {', '.join(keys) or 'no roles'} ({member.status})")
                return 0

            user = await get_user_by_email(db, email)
            if user is None:
                print(f"No account with email {email}", file=sys.stderr)
                return 1
            verified = "verified" if user.email_verified_at else "NOT verified"
            two_step = "on" if await mfa.is_enabled(db, user.id) else "off"
            print(f"{user.email}: {user.status}, email {verified}, two-step sign-in {two_step}")
            rows = (
                await db.execute(
                    select(Organisation, OrganisationMember)
                    .join(OrganisationMember, OrganisationMember.organisation_id == Organisation.id)
                    .where(OrganisationMember.user_id == user.id, Organisation.deleted_at.is_(None))
                    .order_by(Organisation.kind, Organisation.name)
                )
            ).all()
            print("Organisations:")
            for org, member in rows:
                keys = await tenancy.member_role_keys(db, member.id)
                print(
                    f"  {org.name} [{org.kind}]: {', '.join(keys) or 'no roles'}"
                    f" (membership {member.status}, organisation {org.status})"
                )
            found = await tenancy.membership(db, user.id, platform.id) if platform else None
            if platform is None or found is None:
                print(
                    "\nNo platform role, so the admin pages won't open. Grant one with:\n"
                    f"  python -m app.cli grant-platform-role --email {user.email}"
                    " --role SUPERADMIN"
                )
                return 1
            print(f"\nAdmin pages, while {platform.name} is the active organisation:")
            for path, perm in ADMIN_PAGES.items():
                print(f"  {path}: {'yes' if perm in found.permissions else 'no'}")
            if settings.staff_mfa_required and two_step == "off":
                print("Turn on two-step sign-in (Account, Security) first: staff pages need it.")
            return 0
    finally:
        await resources.close()


async def reset_mfa(email: str, settings: Settings | None = None) -> int:
    """Turn off two-step sign-in for someone who lost both their phone and their recovery
    codes (check who they are first). Signs them out everywhere."""
    resources = create_resources(settings or get_settings())
    try:
        async with resources.session_factory() as db:
            user = await get_user_by_email(db, email)
            if user is None:
                print(f"No user with email {email}", file=sys.stderr)
                return 1
            had = await mfa.reset_for_user(db, user, CLI_META)
            await db.commit()
            if had:
                print(f"Two-step sign-in removed for {email}; they are signed out everywhere")
            else:
                print(f"{email} had no two-step sign-in; they are signed out everywhere")
            return 0
    finally:
        await resources.close()


async def verify_audit() -> int:
    resources = create_resources(get_settings())
    try:
        async with resources.session_factory() as db:
            result = await audit.verify_chain(db)
    finally:
        await resources.close()
    if result.ok:
        print(f"audit chain OK ({result.checked} events)")
        return 0
    print(f"audit chain BROKEN at seq {result.first_bad_seq}", file=sys.stderr)
    return 2


_ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
APP_GROUP_ROLE = "approvalready_rw"  # created by migration 0003
_PROVISION_SQL = f"""
DO $$
DECLARE
    role_name text := current_setting('ar.role_name');
    attributes text :=
        'LOGIN INHERIT NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION';
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = role_name) THEN
        EXECUTE format('ALTER ROLE %I WITH %s PASSWORD %L', role_name, attributes,
                       current_setting('ar.role_pw'));
    ELSE
        EXECUTE format('CREATE ROLE %I WITH %s PASSWORD %L', role_name, attributes,
                       current_setting('ar.role_pw'));
    END IF;
    EXECUTE format('GRANT {APP_GROUP_ROLE} TO %I', role_name);
END
$$;
"""


async def provision_db_role(settings: Settings) -> int:
    """Create or update the login role the application connects as (from DATABASE_URL) and
    make it a member of the privilege-holding group role. Runs as the owner
    (MIGRATION_DATABASE_URL). Idempotent; also resets the password to the configured one."""
    app_url = make_url(settings.database_url)
    owner_url = make_url(settings.owner_database_url)
    name, password = app_url.username, app_url.password
    if not name or not password:
        print("DATABASE_URL must include the application role's name and password", file=sys.stderr)
        return 1
    if name == owner_url.username:
        print(
            "DATABASE_URL uses the owner role; set MIGRATION_DATABASE_URL to the owner and "
            "DATABASE_URL to a separate application role",
            file=sys.stderr,
        )
        return 1
    if not _ROLE_NAME.match(name):
        print(f"Unsupported role name {name!r}", file=sys.stderr)
        return 1
    engine = create_async_engine(settings.owner_database_url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            exists = (
                await conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :n"), {"n": name})
            ).scalar_one_or_none()
            # Pass name and password as bound values (transaction-local settings) and build
            # the DDL server-side with format(): %I quotes the identifier, %L the password.
            await conn.execute(
                text(
                    "SELECT set_config('ar.role_name', :n, true), "
                    "set_config('ar.role_pw', :p, true)"
                ),
                {"n": name, "p": password},
            )
            await conn.execute(text(_PROVISION_SQL))
    finally:
        await engine.dispose()
    print(f"database role {name} {'updated' if exists else 'created'}")
    return 0


async def sync_questionnaires(settings: Settings) -> int:
    """Publish bundled questionnaire definitions whose content changed. Definitions are
    read-only for the application role, so this runs as the owner."""
    definitions = load_bundled()
    engine = create_async_engine(settings.owner_database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            results = await questionnaires.sync_definitions(db, definitions)
            await db.commit()
    finally:
        await engine.dispose()
    for r in results:
        print(f"{r.key}: version {r.version} {'published' if r.changed else 'unchanged'}")
    return 0


async def sync_templates(settings: Settings) -> int:
    """Publish bundled report templates whose content changed (owner only, like
    questionnaires)."""
    definitions = document_templates.load_bundled()
    engine = create_async_engine(settings.owner_database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            results = await document_templates.sync_templates(db, definitions)
            await db.commit()
    finally:
        await engine.dispose()
    for r in results:
        print(f"{r.key}: version {r.version} {'published' if r.changed else 'unchanged'}")
    return 0


async def sync_prompts(settings: Settings) -> int:
    """Publish bundled AI prompts whose content changed (owner only, like templates)."""
    definitions = ai_prompts.load_bundled()
    engine = create_async_engine(settings.owner_database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            results = await ai_prompts.sync_prompts(db, definitions)
            await db.commit()
    finally:
        await engine.dispose()
    for r in results:
        print(f"{r.task}: version {r.version} {'published' if r.changed else 'unchanged'}")
    return 0


async def sync_categories(settings: Settings) -> int:
    """Apply the reviewed marketplace category file (owner only, like questionnaires)."""
    definitions = marketplace.load_bundled()
    engine = create_async_engine(settings.owner_database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            report = await marketplace.sync(db, definitions)
            await db.commit()
    finally:
        await engine.dispose()
    for line in report.lines():
        print(line)
    return 0


async def sync_catalogue(settings: Settings) -> int:
    """Apply the reviewed billing catalogue (products and plan limits, never prices)."""
    catalogue = billing_catalogue.load_bundled()
    engine = create_async_engine(settings.owner_database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            report = await billing_catalogue.sync(db, catalogue)
            await db.commit()
    finally:
        await engine.dispose()
    for line in report.lines():
        print(line)
    return 0


async def sync_consent(settings: Settings) -> int:
    """Publish changed referral consent texts (owner only; the app role can only read)."""
    from app.modules.leads import consent

    texts = consent.load_bundled()
    engine = create_async_engine(settings.owner_database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            lines = await consent.sync(db, texts)
            await db.commit()
    finally:
        await engine.dispose()
    for line in lines:
        print(line)
    return 0


async def load_pack(
    name: str, email: str, *, publish: bool, settings: Settings | None = None
) -> int:
    """Create a content pack's sources and rules as the given platform staff member (so the
    audit log names them). Existing items are left alone; see ``app/modules/rules/packs.py``."""
    try:
        pack = packs.load_file(name)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    needed = {Perm.SOURCE_MANAGE, Perm.RULE_AUTHOR} | ({Perm.RULE_PUBLISH} if publish else set())
    resources = create_resources(settings or get_settings())
    try:
        async with resources.session_factory() as db:
            user = await get_user_by_email(db, email)
            org = (
                await db.execute(
                    select(Organisation).where(
                        Organisation.kind == OrganisationKind.PLATFORM_ADMIN,
                        Organisation.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            found = await tenancy.membership(db, user.id, org.id) if user and org else None
            if user is None or org is None or found is None:
                print(f"{email} is not a member of the platform organisation", file=sys.stderr)
                return 1
            missing = sorted(needed - set(found.permissions))
            if missing:
                print(f"{email} lacks permissions: {', '.join(missing)}", file=sys.stderr)
                return 1
            report = await packs.load(db, pack, Actor(user.id, org.id, CLI_META), publish=publish)
            await db.commit()
    finally:
        await resources.close()
    print(f"{pack.title}\n")
    for line in report.lines():
        print(line)
    if not publish:
        print("\nRules were created as drafts. Publish them in /admin/rules after review.")
    return 0


async def check_sources(settings: Settings) -> int:
    """Run the weekly source check now (documents checked in the last 6 days are skipped)."""
    from app.core.email import create_email_provider
    from app.modules.regulatory import checks
    from app.modules.regulatory.fetch import SourceFetcher
    from app.modules.regulatory.models import CheckOutcome

    resources = create_resources(settings)
    try:
        result = await checks.run_weekly(
            resources.session_factory,
            create_email_provider(settings),
            settings,
            SourceFetcher(settings),
        )
    finally:
        await resources.close()
    print(f"Checked {result.checked} source document(s).")
    for outcome, count in sorted(result.outcomes.items()):
        print(f"  {checks.OUTCOME_LABELS[CheckOutcome(outcome)]}: {count}")
    for title, outcome, error in result.news:
        label = checks.OUTCOME_LABELS[CheckOutcome(outcome)]
        print(f"- {title}: {label}{f' ({error})' if error else ''}")
    return 0


async def delete_closed_workspaces(settings: Settings) -> int:
    """Delete the closed accounts' workspaces that are due now (the nightly job)."""
    from app.modules.privacy import purge

    resources = create_resources(settings)
    try:
        done = await purge.run_due(
            resources.session_factory, resources.storage, settings.privacy_purge_after_days
        )
    finally:
        await resources.close()
    print(f"Deleted {len(done)} closed account workspace(s).")
    for result in done:
        print(f"- request {result.request_id}: {result.total} records, {result.files} files")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    grant = sub.add_parser("grant-platform-role", help="Grant STAFF/ADMIN/SUPERADMIN")
    grant.add_argument("--email", required=True)
    grant.add_argument(
        "--role", required=True, choices=[RoleKey.STAFF, RoleKey.ADMIN, RoleKey.SUPERADMIN]
    )
    access = sub.add_parser("platform-access", help="Show who can open the admin pages")
    access.add_argument("--email", help="One account (default: everyone with a platform role)")
    sub.add_parser("verify-audit", help="Verify the audit log hash chain")
    au = sub.add_parser("auth", help="Account security")
    au_sub = au.add_subparsers(dest="auth_command", required=True)
    rm = au_sub.add_parser("reset-mfa", help="Turn off two-step sign-in for one user")
    rm.add_argument("--email", required=True)
    sub.add_parser("provision-db-role", help="Create/update the application's database role")
    q = sub.add_parser("questionnaires", help="Questionnaire definitions")
    q.add_argument("action", choices=["sync"])
    d = sub.add_parser("documents", help="Report templates")
    d.add_argument("action", choices=["sync-templates"])
    a = sub.add_parser("ai", help="AI prompts")
    a.add_argument("action", choices=["sync-prompts"])
    m = sub.add_parser("marketplace", help="Marketplace categories")
    m.add_argument("action", choices=["sync-categories"])
    b = sub.add_parser("billing", help="Billing catalogue (products and plan limits)")
    b.add_argument("action", choices=["sync-catalogue"])
    le = sub.add_parser("leads", help="Referral consent texts")
    le.add_argument("action", choices=["sync-consent"])
    r = sub.add_parser("rules", help="Rule content packs")
    r_sub = r.add_subparsers(dest="rules_command", required=True)
    lp = r_sub.add_parser("load-pack", help="Create a pack's sources and rules (as drafts)")
    lp.add_argument("name", help=f"One of: {', '.join(packs.available())}")
    lp.add_argument("--email", required=True, help="Platform staff member doing the load")
    lp.add_argument("--publish", action="store_true", help="Publish rules that pass the gate")
    sc = sub.add_parser("sources", help="Regulatory sources")
    sc.add_argument("action", choices=["check"], help="Run the weekly source check now")
    pv = sub.add_parser("privacy", help="Closed accounts")
    pv.add_argument(
        "action",
        choices=["delete-closed-workspaces"],
        help="Delete the closed accounts' workspaces that are due now",
    )
    args = parser.parse_args(argv)
    if args.command == "grant-platform-role":
        return asyncio.run(grant_platform_role(args.email, RoleKey(args.role)))
    if args.command == "platform-access":
        return asyncio.run(platform_access(args.email))
    if args.command == "auth":
        return asyncio.run(reset_mfa(args.email))
    if args.command == "provision-db-role":
        return asyncio.run(provision_db_role(get_settings()))
    if args.command == "questionnaires":
        return asyncio.run(sync_questionnaires(get_settings()))
    if args.command == "documents":
        return asyncio.run(sync_templates(get_settings()))
    if args.command == "ai":
        return asyncio.run(sync_prompts(get_settings()))
    if args.command == "marketplace":
        return asyncio.run(sync_categories(get_settings()))
    if args.command == "billing":
        return asyncio.run(sync_catalogue(get_settings()))
    if args.command == "leads":
        return asyncio.run(sync_consent(get_settings()))
    if args.command == "sources":
        return asyncio.run(check_sources(get_settings()))
    if args.command == "privacy":
        return asyncio.run(delete_closed_workspaces(get_settings()))
    if args.command == "rules":
        return asyncio.run(load_pack(args.name, args.email, publish=args.publish))
    return asyncio.run(verify_audit())


if __name__ == "__main__":
    raise SystemExit(main())
