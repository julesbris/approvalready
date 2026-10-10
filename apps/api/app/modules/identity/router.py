"""``/v1/auth``: registration, verification, login/logout, session, passwords."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import (
    AuthDep,
    BreachDep,
    DbDep,
    LimiterDep,
    MetaDep,
    ResourcesDep,
    SettingsDep,
    clear_mfa_challenge_cookie,
    clear_session_cookies,
    set_mfa_challenge_cookie,
    set_session_cookies,
)
from app.core.email import OutgoingEmail
from app.core.errors import ApiError
from app.core.ratelimit import RateLimiter
from app.core.security import csrf_token_for
from app.modules.audit import service as audit
from app.modules.identity import email_change, mfa
from app.modules.identity import service as identity
from app.modules.identity.models import AppUser, AuthSession, UserStatus
from app.modules.identity.schemas import (
    Accepted,
    EmailChangeOut,
    EmailChangeRequest,
    EmailRequest,
    LoginRequest,
    MembershipOut,
    MfaChallengeOut,
    MfaCodeRequest,
    MfaDisableRequest,
    MfaSetupOut,
    MfaSetupRequest,
    MfaStatusOut,
    PasswordChangeRequest,
    PasswordResetConfirm,
    RecoveryCodesOut,
    RegisterRequest,
    SessionOut,
    SwitchOrganisationRequest,
    TokenRequest,
    UserOut,
)
from app.modules.privacy import acceptance
from app.modules.privacy.schemas import PolicyOut
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
    # Platform permissions only count for a session that passed two-step sign-in.
    staff_mfa_required = (
        active is not None
        and active.organisation.kind == "PLATFORM_ADMIN"
        and not await mfa.staff_mfa_satisfied(db, settings, user.id, session)
    )
    return SessionOut(
        user=UserOut(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            email_verified=user.email_verified_at is not None,
            mfa_enabled=await mfa.is_enabled(db, user.id),
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
        permissions=sorted(active.permissions) if active and not staff_mfa_required else [],
        csrf_token=csrf_token_for(settings.secret_key.get_secret_value(), session.id),
        expires_at=session.expires_at,
        idle_expires_at=session.idle_expires_at,
        staff_mfa_required=staff_mfa_required,
        policies_to_accept=[
            PolicyOut(document=p.document, title=p.title, path=p.path, version=p.version)
            for p in await acceptance.outstanding(db, user.id)
        ],
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
    breach: BreachDep,
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
        breach=breach,
        accept_terms=body.accept_terms,
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


@router.post("/login", response_model=SessionOut | MfaChallengeOut)
async def login(
    body: LoginRequest,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    limiter: LimiterDep,
    meta: MetaDep,
    limits: GuardDep,
) -> SessionOut | MfaChallengeOut:
    """Check the password. With two-step sign-in on, the answer is ``mfa_required`` and a
    short-lived challenge cookie instead of a session: send a code to ``/login/mfa``."""
    user = await identity.authenticate(
        db, limiter, limits, email=body.email, password=body.password, meta=meta
    )
    if await mfa.is_enabled(db, user.id):
        await audit.record(
            db,
            "auth.login.mfa_challenged",
            actor_user_id=user.id,
            meta=meta,
            target_type="app_user",
            target_id=user.id,
        )
        await db.commit()
        token = await mfa.start_challenge(limiter.redis, settings, user.id)
        set_mfa_challenge_cookie(response, settings, token)
        return MfaChallengeOut()
    issued = await identity.create_session(db, settings, user, meta)
    await db.commit()
    set_session_cookies(response, settings, issued.token, issued.session)
    return await _session_out(db, settings, user, issued.session)


def _challenge_expired() -> ApiError:
    return ApiError(
        status.HTTP_401_UNAUTHORIZED,
        "mfa_challenge_expired",
        "Your sign-in timed out. Enter your email and password again.",
    )


@router.post("/login/mfa", response_model=SessionOut)
async def login_mfa(
    body: MfaCodeRequest,
    request: Request,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    resources: ResourcesDep,
    limiter: LimiterDep,
    meta: MetaDep,
    _: GuardDep,
) -> SessionOut:
    """The second step of signing in: a code from the authenticator app or a recovery
    code. A challenge allows a few tries, then the password is needed again."""
    token = request.cookies.get(settings.mfa_cookie_name)
    user_id = await mfa.challenge_attempt(limiter.redis, token) if token else None
    user = await db.get(AppUser, user_id) if user_id else None
    if (
        token is None
        or user is None
        or user.deleted_at is not None
        or user.status != UserStatus.ACTIVE
    ):
        raise _challenge_expired()
    check = await mfa.check_code(db, settings, limiter, user, body.code, meta)
    await mfa.end_challenge(limiter.redis, token)
    issued = await identity.create_session(db, settings, user, meta, mfa_method=check.method)
    await db.commit()
    clear_mfa_challenge_cookie(response, settings)
    set_session_cookies(response, settings, issued.token, issued.session)
    notice = mfa.recovery_email(settings, user, check)
    if notice:
        await identity.send_email(resources.email, notice)
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
    breach: BreachDep,
    _: GuardDep,
) -> Accepted:
    """Set a new password from an emailed link. Signs the user out everywhere."""
    message = await identity.confirm_password_reset(
        db, settings, body.token, body.password, meta, breach
    )
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
    breach: BreachDep,
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
        breach=breach,
    )
    await db.commit()
    set_session_cookies(response, settings, token, auth.session)
    await identity.send_email(resources.email, message)
    return await _session_out(db, settings, auth.user, auth.session)


# --- Two-step sign-in (Milestone 18) ----------------------------------------------------


async def _mfa_status(db: DbDep, settings: SettingsDep, user: AppUser) -> MfaStatusOut:
    row = await mfa.get_totp(db, user.id)
    enabled = row is not None and row.confirmed_at is not None
    return MfaStatusOut(
        enabled=enabled,
        enabled_at=row.confirmed_at if row and enabled else None,
        recovery_codes_left=await mfa.recovery_codes_left(db, user.id) if enabled else 0,
        required_for_staff=settings.staff_mfa_required,
    )


@router.get("/mfa", response_model=MfaStatusOut)
async def mfa_status(auth: AuthDep, db: DbDep, settings: SettingsDep) -> MfaStatusOut:
    return await _mfa_status(db, settings, auth.user)


@router.post("/mfa/totp/setup", response_model=MfaSetupOut)
async def mfa_setup(
    body: MfaSetupRequest,
    auth: AuthDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: LimiterDep,
    meta: MetaDep,
) -> MfaSetupOut:
    """Start setting up an authenticator app (needs the password): the secret as text, an
    ``otpauth://`` link and a QR code. Nothing changes at sign-in until it is confirmed."""
    await _guard(limiter, settings, meta)
    setup = await mfa.begin_setup(db, settings, auth.user, body.password, meta)
    await db.commit()
    return MfaSetupOut(secret=setup.secret, otpauth_uri=setup.otpauth_uri, qr_svg=setup.qr_svg)


@router.post("/mfa/totp/confirm", response_model=RecoveryCodesOut)
async def mfa_confirm(
    body: MfaCodeRequest,
    auth: AuthDep,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    resources: ResourcesDep,
    limiter: LimiterDep,
    meta: MetaDep,
) -> RecoveryCodesOut:
    """Turn two-step sign-in on with the first code from the app. Returns recovery codes
    (shown once), signs out other sessions and rotates this one."""
    token, codes, message = await mfa.confirm_setup(
        db, settings, limiter, auth.user, auth.session, body.code, meta
    )
    await db.commit()
    set_session_cookies(response, settings, token, auth.session)
    await identity.send_email(resources.email, message)
    return RecoveryCodesOut(recovery_codes=codes)


@router.post("/mfa/disable", response_model=MfaStatusOut)
async def mfa_disable(
    body: MfaDisableRequest,
    auth: AuthDep,
    db: DbDep,
    settings: SettingsDep,
    resources: ResourcesDep,
    limiter: LimiterDep,
    meta: MetaDep,
) -> MfaStatusOut:
    """Turn two-step sign-in off (needs the password and a current or recovery code)."""
    await _guard(limiter, settings, meta)
    message = await mfa.disable(
        db, settings, limiter, auth.user, password=body.password, code=body.code, meta=meta
    )
    await db.commit()
    await identity.send_email(resources.email, message)
    return await _mfa_status(db, settings, auth.user)


@router.post("/mfa/recovery-codes", response_model=RecoveryCodesOut)
async def mfa_recovery_codes(
    body: MfaCodeRequest,
    auth: AuthDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: LimiterDep,
    meta: MetaDep,
) -> RecoveryCodesOut:
    """Replace the recovery codes (the old ones stop working); needs a current code."""
    codes = await mfa.regenerate_recovery_codes(db, settings, limiter, auth.user, body.code, meta)
    await db.commit()
    return RecoveryCodesOut(recovery_codes=codes)


# --- Change of email address (Milestone 28) ----------------------------------------------


async def _email_change_out(db: DbDep, user: AppUser) -> EmailChangeOut:
    waiting = await email_change.pending(db, user.id)
    if waiting is None:
        return EmailChangeOut()
    return EmailChangeOut(pending_email=waiting.new_email, expires_at=waiting.expires_at)


@router.get("/email-change", response_model=EmailChangeOut)
async def email_change_status(auth: AuthDep, db: DbDep) -> EmailChangeOut:
    return await _email_change_out(db, auth.user)


@router.post("/email-change", status_code=status.HTTP_202_ACCEPTED, response_model=EmailChangeOut)
async def request_email_change(
    body: EmailChangeRequest,
    auth: AuthDep,
    db: DbDep,
    settings: SettingsDep,
    resources: ResourcesDep,
    limiter: LimiterDep,
    meta: MetaDep,
) -> EmailChangeOut:
    """Ask to change the account's email address (needs the password, and a code when
    two-step sign-in is on). A link goes to the new address and a notice to the current
    one; the address changes only when the link is opened."""
    limits = await _guard(limiter, settings, meta)
    messages = await email_change.request_change(
        db,
        settings,
        limiter,
        auth.user,
        new_email=str(body.new_email),
        password=body.password,
        code=body.code,
        meta=meta,
    )
    await db.commit()
    for message in messages:
        await _send_capped(limiter, limits, resources, message)
    return await _email_change_out(db, auth.user)


@router.delete("/email-change", response_model=EmailChangeOut)
async def cancel_email_change(auth: AuthDep, db: DbDep, meta: MetaDep) -> EmailChangeOut:
    """Cancel the waiting change: the link sent to the new address stops working."""
    await email_change.cancel(db, auth.user, meta)
    await db.commit()
    return EmailChangeOut()


@router.post("/email-change/confirm", response_model=Accepted)
async def confirm_email_change(
    body: TokenRequest,
    db: DbDep,
    settings: SettingsDep,
    resources: ResourcesDep,
    meta: MetaDep,
    _: GuardDep,
) -> Accepted:
    """Open the emailed link: the account moves to the new address (no sign-in needed; the
    link proves the new inbox, the request proved the password)."""
    message = await email_change.confirm(db, settings, body.token, meta)
    await db.commit()
    await identity.send_email(resources.email, message)
    return Accepted()
