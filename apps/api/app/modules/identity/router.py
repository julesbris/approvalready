"""``/v1/auth``: registration, verification, login/logout, session, passwords."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import (
    AuthDep,
    DbDep,
    LimiterDep,
    MetaDep,
    ResourcesDep,
    SettingsDep,
    clear_session_cookies,
    set_session_cookies,
)
from app.core.email import OutgoingEmail
from app.core.ratelimit import RateLimiter
from app.core.security import csrf_token_for
from app.modules.audit import service as audit
from app.modules.identity import service as identity
from app.modules.identity.models import AppUser, AuthSession
from app.modules.identity.schemas import (
    Accepted,
    EmailRequest,
    LoginRequest,
    MembershipOut,
    PasswordChangeRequest,
    PasswordResetConfirm,
    RegisterRequest,
    SessionOut,
    SwitchOrganisationRequest,
    TokenRequest,
    UserOut,
)
from app.modules.tenancy import service as tenancy

router = APIRouter(prefix="/v1/auth", tags=["auth"])


async def _guard(limiter: LimiterDep, settings: SettingsDep, meta: MetaDep) -> identity.AuthLimits:
    limits = identity.AuthLimits.from_settings(settings)
    await identity.guard_request_rate(limiter, limits, meta.ip)
    return limits


GuardDep = Annotated[identity.AuthLimits, Depends(_guard)]


async def _session_out(
    db: DbDep, settings: SettingsDep, user: AppUser, session: AuthSession
) -> SessionOut:
    memberships = await tenancy.memberships(db, user.id)
    active = next(
        (m for m in memberships if m.organisation.id == session.active_organisation_id), None
    )
    return SessionOut(
        user=UserOut(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            email_verified=user.email_verified_at is not None,
        ),
        active_organisation_id=active.organisation.id if active else None,
        organisations=[
            MembershipOut(
                organisation_id=m.organisation.id,
                name=m.organisation.name,
                kind=m.organisation.kind,
                roles=list(m.role_keys),
            )
            for m in memberships
        ],
        permissions=sorted(active.permissions) if active else [],
        csrf_token=csrf_token_for(settings.secret_key.get_secret_value(), session.id),
        expires_at=session.expires_at,
        idle_expires_at=session.idle_expires_at,
    )


async def _send_capped(
    limiter: RateLimiter,
    limits: identity.AuthLimits,
    resources: ResourcesDep,
    message: OutgoingEmail | None,
) -> None:
    if message and await identity.may_email(limiter, limits, message.kind, message.to):
        await identity.send_email(resources.email, message)


@router.post("/register", status_code=status.HTTP_202_ACCEPTED, response_model=Accepted)
async def register(
    body: RegisterRequest,
    db: DbDep,
    settings: SettingsDep,
    resources: ResourcesDep,
    limiter: LimiterDep,
    meta: MetaDep,
    limits: GuardDep,
) -> Accepted:
    """Create an account. Always 202: a verification email (or, if the address is already
    registered, a "you already have an account" email) is sent."""
    message = await identity.register(
        db,
        settings,
        email=body.email,
        password=body.password,
        display_name=body.display_name,
        meta=meta,
    )
    await db.commit()
    await _send_capped(limiter, limits, resources, message)
    return Accepted()


@router.post("/verify-email", response_model=Accepted)
async def verify_email(body: TokenRequest, db: DbDep, meta: MetaDep, _: GuardDep) -> Accepted:
    await identity.verify_email(db, body.token, meta)
    await db.commit()
    return Accepted()


@router.post("/verify-email/resend", status_code=status.HTTP_202_ACCEPTED, response_model=Accepted)
async def resend_verification(
    body: EmailRequest,
    db: DbDep,
    settings: SettingsDep,
    resources: ResourcesDep,
    limiter: LimiterDep,
    limits: GuardDep,
) -> Accepted:
    message = await identity.resend_verification(db, settings, body.email)
    await db.commit()
    await _send_capped(limiter, limits, resources, message)
    return Accepted()


@router.post("/login", response_model=SessionOut)
async def login(
    body: LoginRequest,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    limiter: LimiterDep,
    meta: MetaDep,
    limits: GuardDep,
) -> SessionOut:
    user = await identity.authenticate(
        db, limiter, limits, email=body.email, password=body.password, meta=meta
    )
    issued = await identity.create_session(db, settings, user, meta)
    await db.commit()
    set_session_cookies(response, settings, issued.token, issued.session)
    return await _session_out(db, settings, user, issued.session)


@router.get("/session", response_model=SessionOut)
async def current_session(auth: AuthDep, db: DbDep, settings: SettingsDep) -> SessionOut:
    return await _session_out(db, settings, auth.user, auth.session)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    auth: AuthDep, response: Response, db: DbDep, settings: SettingsDep, meta: MetaDep
) -> None:
    await identity.revoke_session(db, auth.session, "logout", meta)
    await db.commit()
    clear_session_cookies(response, settings)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_everywhere(
    auth: AuthDep, response: Response, db: DbDep, settings: SettingsDep, meta: MetaDep
) -> None:
    await identity.revoke_all_sessions(db, auth.user.id, "logout_all")
    await audit.record(
        db,
        "auth.logout_all",
        actor_user_id=auth.user.id,
        meta=meta,
        target_type="app_user",
        target_id=auth.user.id,
    )
    await db.commit()
    clear_session_cookies(response, settings)


@router.put("/session/organisation", response_model=SessionOut)
async def switch_organisation(
    body: SwitchOrganisationRequest,
    auth: AuthDep,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    meta: MetaDep,
) -> SessionOut:
    """Change the active organisation. The session token is rotated (privilege change)."""
    token = await identity.switch_organisation(db, auth.session, body.organisation_id, meta)
    await db.commit()
    set_session_cookies(response, settings, token, auth.session)
    return await _session_out(db, settings, auth.user, auth.session)


@router.post(
    "/password-reset/request", status_code=status.HTTP_202_ACCEPTED, response_model=Accepted
)
async def request_password_reset(
    body: EmailRequest,
    db: DbDep,
    settings: SettingsDep,
    resources: ResourcesDep,
    limiter: LimiterDep,
    meta: MetaDep,
    limits: GuardDep,
) -> Accepted:
    message = await identity.request_password_reset(db, settings, body.email, meta)
    await db.commit()
    await _send_capped(limiter, limits, resources, message)
    return Accepted()


@router.post("/password-reset/confirm", response_model=Accepted)
async def confirm_password_reset(
    body: PasswordResetConfirm,
    db: DbDep,
    settings: SettingsDep,
    resources: ResourcesDep,
    meta: MetaDep,
    _: GuardDep,
) -> Accepted:
    """Set a new password from an emailed link. Signs the user out everywhere."""
    message = await identity.confirm_password_reset(db, settings, body.token, body.password, meta)
    await db.commit()
    await identity.send_email(resources.email, message)
    return Accepted()


@router.post("/password", response_model=SessionOut)
async def change_password(
    body: PasswordChangeRequest,
    auth: AuthDep,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    resources: ResourcesDep,
    limiter: LimiterDep,
    meta: MetaDep,
) -> SessionOut:
    """Change password (requires the current one). Other sessions are signed out and this
    session's token is rotated."""
    await _guard(limiter, settings, meta)
    token, message = await identity.change_password(
        db,
        settings,
        auth.user,
        auth.session,
        current_password=body.current_password,
        new_password=body.new_password,
        meta=meta,
    )
    await db.commit()
    set_session_cookies(response, settings, token, auth.session)
    await identity.send_email(resources.email, message)
    return await _session_out(db, settings, auth.user, auth.session)
