"""Test harness for authenticated API flows: users, sessions, emails and CSRF headers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from app.core import totp
from app.core.email import MemoryEmailProvider, OutgoingEmail

PASSWORD = "correct horse battery staple"


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


@dataclass
class User:
    email: str
    password: str
    client: AsyncClient
    session: dict[str, Any]
    # Set by ``enable_mfa``.
    mfa_secret: str | None = None
    recovery_codes: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return str(self.session["user"]["id"])

    @property
    def personal_org_id(self) -> str:
        return str(
            next(o for o in self.session["organisations"] if o["kind"] == "PERSONAL")[
                "organisation_id"
            ]
        )

    def csrf(self) -> dict[str, str]:
        return {"x-csrf-token": self.client.cookies.get("ar_csrf") or ""}

    async def get(self, url: str, **kw: Any) -> Response:
        return await self.client.get(url, **kw)

    async def post(self, url: str, **kw: Any) -> Response:
        return await self.client.post(url, headers=self.csrf(), **kw)

    async def put(self, url: str, **kw: Any) -> Response:
        return await self.client.put(url, headers=self.csrf(), **kw)

    async def patch(self, url: str, **kw: Any) -> Response:
        return await self.client.patch(url, headers=self.csrf(), **kw)

    async def delete(self, url: str, **kw: Any) -> Response:
        return await self.client.delete(url, headers=self.csrf(), **kw)


class ApiHarness:
    def __init__(self, app: FastAPI, client: AsyncClient) -> None:
        self.app = app
        self.client = client
        self._clients: list[AsyncClient] = []

    @property
    def outbox(self) -> list[OutgoingEmail]:
        provider = self.app.state.resources.email
        assert isinstance(provider, MemoryEmailProvider)
        return provider.outbox

    def last_email(self, to: str, kind: str | None = None) -> OutgoingEmail:
        for message in reversed(self.outbox):
            if message.to.lower() == to.lower() and (kind is None or message.kind == kind):
                return message
        raise AssertionError(f"no {kind or 'email'} sent to {to}")

    def emails_to(self, to: str, kind: str | None = None) -> list[OutgoingEmail]:
        return [
            m
            for m in self.outbox
            if m.to.lower() == to.lower() and (kind is None or m.kind == kind)
        ]

    @staticmethod
    def token_from(message: OutgoingEmail, link: str) -> str:
        return parse_qs(urlparse(message.links[link]).query)["token"][0]

    async def new_client(self) -> AsyncClient:
        """A separate browser (own cookie jar) against the same running app."""
        c = AsyncClient(transport=ASGITransport(app=self.app), base_url="http://testserver")
        self._clients.append(c)
        return c

    async def session_status(self, token: str | None) -> int:
        """GET /v1/auth/session from a fresh browser holding only this session token."""
        c = await self.new_client()
        c.cookies.set("ar_session", token or "")
        return (await c.get("/v1/auth/session")).status_code

    async def register(
        self, email: str | None = None, password: str = PASSWORD, name: str = "Test User"
    ) -> str:
        email = email or unique_email()
        r = await self.client.post(
            "/v1/auth/register",
            json={
                "email": email,
                "password": password,
                "display_name": name,
                "accept_terms": True,
            },
        )
        assert r.status_code == 202, r.text
        return email

    async def verify(self, email: str) -> None:
        token = self.token_from(self.last_email(email, "auth.verify_email"), "verify")
        r = await self.client.post("/v1/auth/verify-email", json={"token": token})
        assert r.status_code == 200, r.text

    async def login(self, email: str, password: str = PASSWORD) -> User:
        c = await self.new_client()
        r = await c.post("/v1/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        return User(email, password, c, r.json())

    async def user(self, name: str = "Test User", email: str | None = None) -> User:
        email = await self.register(email=email, name=name)
        await self.verify(email)
        return await self.login(email)

    async def aclose(self) -> None:
        for c in self._clients:
            await c.aclose()


def totp_code(secret: str, offset: int = 0) -> str:
    """The authenticator code for now (``offset`` steps ahead, within the drift window, for
    a second code in the same 30 seconds: a used step is never accepted again)."""
    return totp.code_at(secret, totp.current_step() + offset)


async def enable_mfa(user: User) -> str:
    """Turn on two-step sign-in for a signed-in user through the API; returns the secret."""
    r = await user.post("/v1/auth/mfa/totp/setup", json={"password": user.password})
    assert r.status_code == 200, r.text
    secret = str(r.json()["secret"])
    r = await user.post("/v1/auth/mfa/totp/confirm", json={"code": totp_code(secret)})
    assert r.status_code == 200, r.text
    user.mfa_secret = secret
    user.recovery_codes = list(r.json()["recovery_codes"])
    user.session = (await user.get("/v1/auth/session")).json()
    return secret


async def platform_user(api: ApiHarness, role: str = "ADMIN", name: str = "Staff") -> User:
    """A user holding a platform role, signed in with the platform organisation active."""
    from sqlalchemy import select

    from app import cli
    from app.modules.tenancy.models import Organisation

    settings = api.app.state.settings
    factory = api.app.state.resources.session_factory

    async def platform_org() -> Organisation | None:
        async with factory() as db:
            return (
                await db.execute(select(Organisation).where(Organisation.kind == "PLATFORM_ADMIN"))
            ).scalar_one_or_none()

    if await platform_org() is None:
        founder = await api.user(name="Founder")
        assert await cli.grant_platform_role(founder.email, cli.RoleKey.SUPERADMIN, settings) == 0
    user = await api.user(name=name)
    # Staff routes need a session that passed two-step sign-in (Milestone 18).
    await enable_mfa(user)
    assert await cli.grant_platform_role(user.email, cli.RoleKey(role), settings) == 0
    org = await platform_org()
    assert org is not None
    r = await user.put("/v1/auth/session/organisation", json={"organisation_id": str(org.id)})
    assert r.status_code == 200, r.text
    user.session = r.json()
    return user
