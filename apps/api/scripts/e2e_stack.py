"""Test-only helpers for the browser end-to-end suite (scripts/e2e.sh drives them).

    uv run python scripts/e2e_stack.py reset             # recreate the E2E database, flush Redis
    uv run python scripts/e2e_stack.py seed --out FILE   # accounts, rules, an assessed project

``seed`` sets up what the partner journey needs but is not part of it: verified accounts,
platform staff (through ``python -m app.cli grant-platform-role``) with two-step sign-in on
(their authenticator secret goes in the seed file, so the browser can make codes), a
published rule whose
finding names the referral categories, and a customer's submitted planning project with its
assessment. Everything goes through the running API over HTTP except two things a test
cannot do through it: confirming email addresses (a fresh verification token is issued in
the database and redeemed at ``POST /v1/auth/verify-email``, so no mailbox is needed) and
pausing partners and closing open leads left by an earlier run on the same database.

Both commands refuse to run unless APP_ENV is development or test, and ``reset`` only drops
a database whose name ends in ``_e2e``. All data is fictional (example.com, "Test Council").
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

from redis.asyncio import Redis  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core.config import Environment, Settings, get_settings  # noqa: E402

PASSWORD = "correct horse battery staple"  # noqa: S105 - test accounts on the E2E stack
TEST_ENVS = {Environment.DEVELOPMENT, Environment.TEST}

CUSTOMER_NAME = "Casey Customer"
CUSTOMER_PHONE = "0400 111 222"
FLOOR_OVER_80 = {
    "fact": "planning.secondary_dwelling_floor_area_m2",
    "op": "greater_than",
    "value": 80,
}
ADDRESS = {"line1": "1 Example St", "suburb": "Edge Hill", "state": "QLD", "postcode": "4870"}
REFERRAL_CATEGORIES = ["town_planner", "building_certifier"]


class SeedError(RuntimeError):
    pass


def test_only_settings() -> Settings:
    settings = get_settings()
    if settings.is_production or settings.app_env not in TEST_ENVS:
        raise SystemExit(
            f"e2e_stack refuses to run with APP_ENV={settings.app_env.value}: it is for the "
            "end-to-end test stack only (APP_ENV=test or development)"
        )
    return settings


# --- reset -----------------------------------------------------------------------------


async def reset(settings: Settings) -> None:
    """Drop and recreate the E2E database (as the owner) and flush the E2E Redis database."""
    owner = make_url(settings.owner_database_url)
    name = owner.database or ""
    if not name.endswith("_e2e"):
        raise SystemExit(f"Refusing to drop {name!r}: the E2E database's name must end in _e2e")
    engine = create_async_engine(
        owner.set(database="postgres"), poolclass=NullPool, isolation_level="AUTOCOMMIT"
    )
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            await conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await engine.dispose()
    redis = Redis.from_url(settings.redis_url)
    try:
        await redis.flushdb()
    finally:
        await redis.aclose()
    print(f"e2e: database {name} recreated, redis {settings.redis_url} flushed")


# --- seed ------------------------------------------------------------------------------


class Client:
    """One signed-in (or anonymous) API client with its own cookie jar."""

    def __init__(self, base_url: str) -> None:
        self.http = httpx.AsyncClient(base_url=base_url, timeout=30)

    async def call(
        self, method: str, url: str, body: Any = None, *, ok: int | tuple[int, ...] = 200
    ) -> Any:
        headers = {"x-csrf-token": self.http.cookies.get("ar_csrf") or ""}
        r = await self.http.request(method, url, json=body, headers=headers)
        if r.status_code not in (ok if isinstance(ok, tuple) else (ok,)):
            raise SeedError(f"{method} {url} returned {r.status_code}: {r.text}")
        return r.json() if r.content else None

    async def aclose(self) -> None:
        await self.http.aclose()


class Seeder:
    def __init__(self, settings: Settings, base_url: str, run_id: str) -> None:
        self.settings = settings
        self.base_url = base_url
        self.run_id = run_id
        self.anon = Client(base_url)
        self.clients: list[Client] = [self.anon]
        self.owner = create_async_engine(settings.owner_database_url, poolclass=NullPool)

    def email(self, who: str) -> str:
        return f"e2e-{who}-{self.run_id}@example.com"

    async def verified_user(self, who: str, name: str) -> str:
        """Register through the API, then confirm the address with a token issued here."""
        from app.modules.identity import service as identity
        from app.modules.identity.models import TokenPurpose

        email = self.email(who)
        await self.anon.call(
            "POST",
            "/v1/auth/register",
            {"email": email, "password": PASSWORD, "display_name": name, "accept_terms": True},
            ok=202,
        )
        async with async_sessionmaker(self.owner, expire_on_commit=False)() as db:
            user = await identity.get_user_by_email(db, email)
            if user is None:
                raise SeedError(f"{email} was not registered")
            token = await identity.issue_token(
                db, user.id, TokenPurpose.EMAIL_VERIFY, timedelta(hours=1)
            )
            await db.commit()
        await self.anon.call("POST", "/v1/auth/verify-email", {"token": token})
        return email

    async def login(self, email: str) -> tuple[Client, dict[str, Any]]:
        client = Client(self.base_url)
        self.clients.append(client)
        session = await client.call(
            "POST", "/v1/auth/login", {"email": email, "password": PASSWORD}
        )
        return client, session

    async def enable_mfa(self, client: Client) -> str:
        """Turn on two-step sign-in for a signed-in client; returns the authenticator secret.
        Staff routes need it (Milestone 18)."""
        from app.core import totp

        setup = await client.call("POST", "/v1/auth/mfa/totp/setup", {"password": PASSWORD})
        secret = str(setup["secret"])
        code = totp.code_at(secret, totp.current_step())
        await client.call("POST", "/v1/auth/mfa/totp/confirm", {"code": code})
        return secret

    def grant(self, email: str, role: str) -> None:
        subprocess.run(  # noqa: S603 - fixed argv, our own CLI
            [
                sys.executable,
                "-m",
                "app.cli",
                "grant-platform-role",
                "--email",
                email,
                "--role",
                role,
            ],
            cwd=API_ROOT,
            check=True,
        )

    async def leave_earlier_runs_behind(self) -> None:
        """Partners are platform-wide: pause those from earlier runs and close their open
        leads, so this run's partner is the one offered this run's referral."""
        async with self.owner.begin() as conn:
            await conn.execute(text("UPDATE partner_organisation SET paused = true"))
            await conn.execute(
                text("UPDATE lead SET status = 'EXPIRED', closed_at = now() WHERE status = 'OPEN'")
            )

    async def published_rule(self, staff: Client, lot: str) -> None:
        """A planning rule set scoped to one lot, with a rule whose finding says a town
        planner and a building certifier can help."""
        admin = "/v1/admin"
        org = await staff.call(
            "POST",
            f"{admin}/source-organisations",
            {"name": f"Test Council {self.run_id}", "kind": "COUNCIL", "jurisdiction": "QLD"},
            ok=201,
        )
        document = await staff.call(
            "POST",
            f"{admin}/source-documents",
            {
                "source_organisation_id": org["id"],
                "jurisdiction": "LGA:QLD_TEST",
                "title": f"Test Planning Scheme {self.run_id}",
                "url": "https://example.com/planning-scheme",
                "source_type": "PLANNING_SCHEME",
                "effective_from": "2020-01-01",
            },
            ok=201,
        )
        ref = await staff.call(
            "POST",
            f"{admin}/source-documents/{document['id']}/references",
            {"section": "Part 1", "clause": "1.1", "extracted_text": "Example extract."},
            ok=201,
        )
        await staff.call(
            "POST",
            f"{admin}/source-documents/{document['id']}/snapshots",
            {"content_text": "Clause 1. Example text.", "retrieved_at": "2026-01-01T00:00:00Z"},
        )
        await staff.call(
            "POST", f"{admin}/source-references/{ref['id']}/review", {"action": "VERIFY"}
        )
        rule_set = await staff.call(
            "POST",
            f"{admin}/rule-sets",
            {
                "key": f"test.e2e_{self.run_id}",
                "vertical": "PLANNING",
                "jurisdiction": "QLD",
                "title": "Test rules (end-to-end)",
                "applies_when": {
                    "all": [{"fact": "property.lot_plan", "op": "equals", "value": lot}]
                },
            },
            ok=201,
        )
        rule = await staff.call(
            "POST",
            f"{admin}/rule-sets/{rule_set['id']}/rules",
            {"key": f"rule_{self.run_id}", "title": "Test rule", "condition": FLOOR_OVER_80},
            ok=201,
        )
        version_id = rule["versions"][0]["id"]
        await staff.call(
            "PUT",
            f"{admin}/rule-versions/{version_id}",
            {
                "condition": FLOOR_OVER_80,
                "effective_from": "2026-01-01",
                "outcomes": [
                    {
                        "on_result": "MATCH",
                        "outcome_type": "APPROVAL_LIKELY",
                        "title": "A development application is likely",
                        "payload": {
                            "approval": {
                                "kind": "PLANNING_MATERIAL_CHANGE_OF_USE",
                                "authority": "Test Council",
                            },
                            "referral_categories": REFERRAL_CATEGORIES,
                        },
                    },
                    {
                        "on_result": "NO_MATCH",
                        "outcome_type": "NOT_REQUIRED",
                        "title": "Not needed",
                    },
                ],
                "sources": [{"source_reference_id": ref["id"], "relationship": "BASIS"}],
                "test_cases": [{"name": "missing", "facts": {}, "expected_result": "UNKNOWN"}],
            },
        )
        await staff.call("POST", f"{admin}/rule-versions/{version_id}/publish")

    async def assessed_project(
        self, customer: Client, org_id: str, lot: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """The customer's submitted granny-flat project and its assessment."""
        org = f"/v1/organisations/{org_id}"
        project = await customer.call(
            "POST", f"{org}/projects", {"vertical": "PLANNING", "title": "Granny flat"}, ok=201
        )
        submission = await customer.call(
            "POST", f"{org}/projects/{project['id']}/submissions", {}, ok=(200, 201)
        )
        answers = {
            "property.address": ADDRESS,
            "property.lot_plan": lot,
            "property.land_area_m2": 812.25,
            "property.has_existing_dwelling": True,
            "planning.development_type": "secondary_dwelling",
            "planning.secondary_dwelling_bedrooms": 1,
            "planning.secondary_dwelling_floor_area_m2": 92.5,
            "planning.storeys": 1,
        }
        await customer.call(
            "PUT", f"{org}/submissions/{submission['id']}/answers", {"answers": answers}
        )
        await customer.call("POST", f"{org}/submissions/{submission['id']}/submit")
        assessment = await customer.call(
            "POST", f"{org}/projects/{project['id']}/assessments", ok=201
        )
        found = {c["key"] for c in assessment["referral_categories"]}
        if found != set(REFERRAL_CATEGORIES):
            raise SeedError(f"the assessment names {found or 'no'} referral categories")
        return project, assessment

    async def run(self) -> dict[str, Any]:
        await self.leave_earlier_runs_behind()
        # Platform staff: a super admin who writes and publishes the rules, and a staff
        # member who checks partners in the browser.
        founder = await self.verified_user("founder", "Founder")
        self.grant(founder, "SUPERADMIN")
        staff = await self.verified_user("staff", "Sam Staff")
        self.grant(staff, "STAFF")
        rules_admin, session = await self.login(founder)
        await self.enable_mfa(rules_admin)
        staff_client, _ = await self.login(staff)
        staff_totp_secret = await self.enable_mfa(staff_client)
        platform = next(o for o in session["organisations"] if o["kind"] == "PLATFORM_ADMIN")
        await rules_admin.call(
            "PUT", "/v1/auth/session/organisation", {"organisation_id": platform["organisation_id"]}
        )
        lot = f"LOT_E2E_{self.run_id}"
        await self.published_rule(rules_admin, lot)

        customer_email = await self.verified_user("customer", CUSTOMER_NAME)
        customer, session = await self.login(customer_email)
        personal = next(o for o in session["organisations"] if o["kind"] == "PERSONAL")
        project, assessment = await self.assessed_project(
            customer, personal["organisation_id"], lot
        )

        partner_email = await self.verified_user("partner", "Pat Partner")
        # Turns on two-step sign-in in the browser (account-security.spec.ts).
        security_email = await self.verified_user("security", "Sky Secure")
        return {
            "runId": self.run_id,
            "password": PASSWORD,
            "platformOrganisation": platform["name"],
            "staff": {"email": staff, "totpSecret": staff_totp_secret},
            "partner": {"email": partner_email, "business": f"Reef Certifiers {self.run_id}"},
            "security": {"email": security_email},
            "customer": {"email": customer_email, "name": CUSTOMER_NAME, "phone": CUSTOMER_PHONE},
            "projectId": project["id"],
            "assessmentId": assessment["id"],
        }

    async def aclose(self) -> None:
        for client in self.clients:
            await client.aclose()
        await self.owner.dispose()


async def seed(settings: Settings) -> dict[str, Any]:
    base_url = os.environ.get("E2E_API_URL", "http://127.0.0.1:8000")
    seeder = Seeder(settings, base_url, uuid.uuid4().hex[:8])
    try:
        return await seeder.run()
    finally:
        await seeder.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("reset", help="Recreate the E2E database and flush the E2E Redis database")
    s = sub.add_parser("seed", help="Seed what the partner journey starts from")
    s.add_argument("--out", type=Path, required=True, help="Where to write the seed (JSON)")
    args = parser.parse_args()
    settings = test_only_settings()
    if args.command == "reset":
        asyncio.run(reset(settings))
    else:
        data = asyncio.run(seed(settings))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(data, indent=2) + "\n")
        print(f"e2e: seeded run {data['runId']} into {args.out}")


if __name__ == "__main__":
    main()
