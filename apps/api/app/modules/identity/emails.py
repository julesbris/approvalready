"""Transactional email content for identity and tenancy flows (plain text, en-AU)."""

from __future__ import annotations

from urllib.parse import urlencode

from app.core.config import Settings
from app.core.email import OutgoingEmail


def _link(settings: Settings, path: str, token: str) -> str:
    return f"{settings.web_base_url.rstrip('/')}{path}?{urlencode({'token': token})}"


def verify_email(settings: Settings, to: str, name: str, token: str) -> OutgoingEmail:
    link = _link(settings, "/verify-email", token)
    hours = settings.email_verification_ttl_hours
    return OutgoingEmail(
        to=to,
        kind="auth.verify_email",
        subject="Confirm your email address",
        text=(
            f"Hi {name},\n\n"
            f"Confirm your email address to finish setting up your ApprovalReady account:\n\n"
            f"{link}\n\n"
            f"This link expires in {hours} hours. If you did not create an account, you can "
            f"ignore this email.\n"
        ),
        links={"verify": link},
    )


def already_registered(settings: Settings, to: str) -> OutgoingEmail:
    login = f"{settings.web_base_url.rstrip('/')}/login"
    reset = f"{settings.web_base_url.rstrip('/')}/forgot-password"
    return OutgoingEmail(
        to=to,
        kind="auth.already_registered",
        subject="You already have an ApprovalReady account",
        text=(
            "Someone (hopefully you) tried to create an ApprovalReady account with this email "
            "address, but an account already exists.\n\n"
            f"Sign in: {login}\nForgot your password? {reset}\n\n"
            "If this wasn't you, no action is needed.\n"
        ),
        links={"login": login, "reset": reset},
    )


def password_reset(settings: Settings, to: str, name: str, token: str) -> OutgoingEmail:
    link = _link(settings, "/reset-password", token)
    minutes = settings.password_reset_ttl_minutes
    return OutgoingEmail(
        to=to,
        kind="auth.password_reset",
        subject="Reset your ApprovalReady password",
        text=(
            f"Hi {name},\n\n"
            f"Use this link to choose a new password:\n\n{link}\n\n"
            f"It expires in {minutes} minutes and can be used once. Resetting your password "
            f"signs you out on every device. If you did not ask for this, ignore this email.\n"
        ),
        links={"reset": link},
    )


def password_changed(settings: Settings, to: str, name: str) -> OutgoingEmail:
    reset = f"{settings.web_base_url.rstrip('/')}/forgot-password"
    return OutgoingEmail(
        to=to,
        kind="auth.password_changed",
        subject="Your ApprovalReady password was changed",
        text=(
            f"Hi {name},\n\nYour password was just changed and other sessions were signed out.\n"
            f"If this wasn't you, reset your password now: {reset}\n"
        ),
        links={"reset": reset},
    )


def invitation(
    settings: Settings, to: str, organisation_name: str, inviter_name: str, token: str
) -> OutgoingEmail:
    link = _link(settings, "/invitations/accept", token)
    days = settings.invitation_ttl_days
    return OutgoingEmail(
        to=to,
        kind="org.invitation",
        subject=f"{inviter_name} invited you to {organisation_name} on ApprovalReady",
        text=(
            f"{inviter_name} invited you to join {organisation_name} on ApprovalReady.\n\n"
            f"Accept the invitation: {link}\n\n"
            f"You'll need to sign in or create an account with this email address. "
            f"The invitation expires in {days} days.\n"
        ),
        links={"accept": link},
    )


def _security_footer(settings: Settings) -> str:
    reset = f"{settings.web_base_url.rstrip('/')}/forgot-password"
    return f"If this wasn't you, reset your password now ({reset}) and contact support.\n"


def mfa_enabled(settings: Settings, to: str, name: str) -> OutgoingEmail:
    return OutgoingEmail(
        to=to,
        kind="auth.mfa_enabled",
        subject="Two-step sign-in is on for your ApprovalReady account",
        text=(
            f"Hi {name},\n\nTwo-step sign-in was just turned on. From now on you'll enter a "
            "code from your authenticator app after your password, and other sessions were "
            "signed out. Keep your recovery codes somewhere safe.\n\n" + _security_footer(settings)
        ),
    )


def mfa_disabled(settings: Settings, to: str, name: str) -> OutgoingEmail:
    return OutgoingEmail(
        to=to,
        kind="auth.mfa_disabled",
        subject="Two-step sign-in was turned off for your ApprovalReady account",
        text=(
            f"Hi {name},\n\nTwo-step sign-in was just turned off. Your account is now protected "
            "by your password only.\n\n" + _security_footer(settings)
        ),
    )


def mfa_recovery_code_used(settings: Settings, to: str, name: str, left: int) -> OutgoingEmail:
    return OutgoingEmail(
        to=to,
        kind="auth.mfa_recovery_code_used",
        subject="A recovery code was used to sign in to ApprovalReady",
        text=(
            f"Hi {name},\n\nSomeone signed in to your account with one of your recovery codes. "
            f"You have {left} left. If you've lost your authenticator app, make new codes or set "
            "up the app again under Account, Security.\n\n" + _security_footer(settings)
        ),
    )


# --- Change of email address (Milestone 28) ---------------------------------------------


def mask_email(email: str) -> str:
    """``jane@example.com`` -> ``j***@example.com``: enough to recognise, not to copy."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def email_change_confirm(
    settings: Settings, to: str, name: str, token: str, old_email: str
) -> OutgoingEmail:
    link = _link(settings, "/verify-email/change", token)
    hours = settings.email_verification_ttl_hours
    return OutgoingEmail(
        to=to,
        kind="auth.email_change_confirm",
        subject="Confirm your new email address for ApprovalReady",
        text=(
            f"Hi {name},\n\n"
            f"You asked to change the email address of your ApprovalReady account from "
            f"{mask_email(old_email)} to this one. Confirm the change:\n\n{link}\n\n"
            f"This link expires in {hours} hours. Until then you still sign in with your old "
            "address. If you did not ask for this, ignore this email.\n"
        ),
        links={"confirm": link},
    )


def email_change_address_taken(settings: Settings, to: str) -> OutgoingEmail:
    login = f"{settings.web_base_url.rstrip('/')}/login"
    return OutgoingEmail(
        to=to,
        kind="auth.email_change_confirm",
        subject="This address already has an ApprovalReady account",
        text=(
            "Someone asked to move an ApprovalReady account to this email address, but an "
            "account already uses it, so nothing was changed.\n\n"
            f"If that account is yours, sign in to it: {login}\n"
            "If you meant to combine two accounts, contact us. If this wasn't you, no action "
            "is needed.\n"
        ),
        links={"login": login},
    )


def email_change_requested(settings: Settings, to: str, name: str, new_email: str) -> OutgoingEmail:
    return OutgoingEmail(
        to=to,
        kind="auth.email_change_requested",
        subject="A change of email address was asked for on your ApprovalReady account",
        text=(
            f"Hi {name},\n\nSomeone signed in to your account asked to change its email address "
            f"to {mask_email(new_email)}. Nothing changes until the link sent to that address "
            "is opened. You can cancel it under Account, Security.\n\n" + _security_footer(settings)
        ),
    )


def email_changed(settings: Settings, to: str, name: str, new_email: str) -> OutgoingEmail:
    contact = f"{settings.web_base_url.rstrip('/')}/contact"
    return OutgoingEmail(
        to=to,
        kind="auth.email_changed",
        subject="The email address of your ApprovalReady account was changed",
        text=(
            f"Hi {name},\n\nYour ApprovalReady account now uses {mask_email(new_email)}. "
            "This address no longer signs in or receives emails from the account.\n\n"
            f"If this wasn't you, contact us at once: {contact}\n"
        ),
        links={"contact": contact},
    )
