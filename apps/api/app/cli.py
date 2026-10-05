"""Operator commands (run inside the API container).

    python -m app.cli grant-platform-role --email ops@example.com --role SUPERADMIN
    python -m app.cli verify-audit

Platform roles can only be granted in the PLATFORM_ADMIN organisation, which is created on
first use. There is deliberately no HTTP endpoint that bootstraps the first super admin.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.core.resources import create_resources
from app.modules.audit import service as audit
from app.modules.audit.service import RequestMeta
from app.modules.identity.service import get_user_by_email
from app.modules.tenancy import service as tenancy
from app.modules.tenancy.models import (
    MemberRole,
    Organisation,
    OrganisationKind,
    OrganisationMember,
)
from app.modules.tenancy.rbac import RoleKey

PLATFORM_ORG_NAME = "ApprovalReady"
CLI_META = RequestMeta(ip=None, user_agent="app.cli")


async def grant_platform_role(email: str, role: RoleKey) -> int:
    resources = create_resources(get_settings())
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    grant = sub.add_parser("grant-platform-role", help="Grant STAFF/ADMIN/SUPERADMIN")
    grant.add_argument("--email", required=True)
    grant.add_argument(
        "--role", required=True, choices=[RoleKey.STAFF, RoleKey.ADMIN, RoleKey.SUPERADMIN]
    )
    sub.add_parser("verify-audit", help="Verify the audit log hash chain")
    args = parser.parse_args(argv)
    if args.command == "grant-platform-role":
        return asyncio.run(grant_platform_role(args.email, RoleKey(args.role)))
    return asyncio.run(verify_audit())


if __name__ == "__main__":
    raise SystemExit(main())
