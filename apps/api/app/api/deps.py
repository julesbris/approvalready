"""Request dependencies: database session, request metadata, authentication and policy.

Authorisation is enforced here, in the backend, for every request: the web app never
decides what a user may see. Organisation-scoped routes resolve the caller's membership
of the organisation in the URL and answer 404 (not 403) when there is none, so the
existence of other tenants' organisations is not revealed.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ApiError, forbidden, not_found, unauthenticated
from app.core.ratelimit import RateLimiter
from app.core.resources import Resources
from app.core.security import constant_time_equals, csrf_token_for
from app.modules.audit.service import RequestMeta
from app.modules.identity import service as identity
from app.modules.identity.models import AppUser, AuthSession
from app.modules.tenancy import service as tenancy
from app.modules.tenancy.models import Organisation

CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_resources(request: Request) -> Resources:
    resources: Resources = request.app.state.resources
    return resources


async def get_db(
    resources: Annotated[Resources, Depends(get_resources)],
) -> AsyncIterator[AsyncSession]:
    async with resources.session_factory() as session:
        yield session


def get_limiter(resources: Annotated[Resources, Depends(get_resources)]) -> RateLimiter:
    return RateLimiter(resources.redis)


def get_meta(request: Request) -> RequestMeta:
    # request.client is the proxy-resolved client address (uvicorn --proxy-headers).
    return RequestMeta(
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
ResourcesDep = Annotated[Resources, Depends(get_resources)]
DbDep = Annotated[AsyncSession, Depends(get_db)]
LimiterDep = Annotated[RateLimiter, Depends(get_limiter)]
MetaDep = Annotated[RequestMeta, Depends(get_meta)]


# --- Cookies ---------------------------------------------------------------------------


def set_session_cookies(
    response: Response, settings: Settings, token: str, session: AuthSession
) -> str:
    """Set the HttpOnly session cookie and the script-readable CSRF cookie."""
    max_age = max(int((session.expires_at - datetime.now(UTC)).total_seconds()), 0)
    csrf = csrf_token_for(settings.secret_key.get_secret_value(), session.id)
    for name, value, httponly in (
        (settings.session_cookie_name, token, True),
        (settings.csrf_cookie_name, csrf, False),
    ):
        response.set_cookie(
            name,
            value,
            max_age=max_age,
            path="/",
            secure=settings.cookie_secure,
            httponly=httponly,
            samesite="lax",
        )
    return csrf


def clear_session_cookies(response: Response, settings: Settings) -> None:
    for name in (settings.session_cookie_name, settings.csrf_cookie_name):
        response.delete_cookie(name, path="/", secure=settings.cookie_secure, samesite="lax")


# --- Authentication --------------------------------------------------------------------


@dataclass
class AuthContext:
    user: AppUser
    session: AuthSession
    csrf_token: str


async def get_auth(
    request: Request, response: Response, db: DbDep, settings: SettingsDep
) -> AuthContext:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise unauthenticated()
    resolved = await identity.resolve_session(db, token)
    if resolved is None:
        raise unauthenticated()
    session, user = resolved
    csrf = csrf_token_for(settings.secret_key.get_secret_value(), session.id)
    # Cookie-authenticated state changes need the CSRF header (double-submit, bound to the
    # session by HMAC so a cookie planted by a sibling subdomain can't forge it).
    if request.method not in SAFE_METHODS:
        supplied = request.headers.get(CSRF_HEADER, "")
        if not supplied or not constant_time_equals(supplied, csrf):
            raise ApiError(403, "csrf_failed", "Your session check failed. Reload the page.")
    rotated = await identity.touch_session(db, settings, session)
    await db.commit()
    if rotated:
        set_session_cookies(response, settings, rotated, session)
    return AuthContext(user=user, session=session, csrf_token=csrf)


AuthDep = Annotated[AuthContext, Depends(get_auth)]


# --- Organisation policy ---------------------------------------------------------------


@dataclass
class OrgContext:
    auth: AuthContext
    organisation: Organisation
    role_keys: tuple[str, ...]
    permissions: frozenset[str]

    def can(self, permission: str) -> bool:
        return permission in self.permissions


def require_org_permission(
    permission: str,
) -> Callable[[uuid.UUID, AuthContext, AsyncSession], Awaitable[OrgContext]]:
    """Dependency factory for ``/organisations/{organisation_id}/...`` routes."""

    async def dependency(organisation_id: uuid.UUID, auth: AuthDep, db: DbDep) -> OrgContext:
        found = await tenancy.membership(db, auth.user.id, organisation_id)
        if found is None:
            raise not_found("Organisation")
        if permission not in found.permissions:
            raise forbidden()
        return OrgContext(auth, found.organisation, found.role_keys, found.permissions)

    return dependency


def require_platform_permission(
    permission: str,
) -> Callable[[AuthContext, AsyncSession], Awaitable[OrgContext]]:
    """Staff/admin routes. Platform roles count only while the session's active
    organisation is the PLATFORM_ADMIN organisation (explicit context switch)."""

    async def dependency(auth: AuthDep, db: DbDep) -> OrgContext:
        active = auth.session.active_organisation_id
        found = await tenancy.membership(db, auth.user.id, active) if active else None
        if found is None or found.organisation.kind != "PLATFORM_ADMIN":
            raise forbidden()
        if permission not in found.permissions:
            raise forbidden()
        return OrgContext(auth, found.organisation, found.role_keys, found.permissions)

    return dependency
