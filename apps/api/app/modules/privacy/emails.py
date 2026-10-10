"""Emails for privacy flows (plain text, en-AU)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.config import Settings
from app.core.email import OutgoingEmail

if TYPE_CHECKING:
    from app.modules.privacy.models import PrivacyRequest


def _url(settings: Settings, path: str) -> str:
    return f"{settings.web_base_url.rstrip('/')}{path}"


def account_closed(settings: Settings, to: str, name: str) -> OutgoingEmail:
    contact = _url(settings, "/contact")
    return OutgoingEmail(
        to=to,
        kind="privacy.account_closed",
        subject="Your ApprovalReady account is closed",
        text=(
            f"Hi {name},\n\n"
            "Your ApprovalReady account is closed. You have been signed out everywhere, and "
            "your name, email address and password have been removed from the account.\n\n"
            "Within 30 days we will delete the projects, answers and files in your personal "
            "workspace, except records the law requires us to keep (such as payment "
            "records). We will email this address once that is done.\n\n"
            f"If you didn't close your account, contact us straight away: {contact}\n"
        ),
        links={"contact": contact},
    )


def request_received(settings: Settings, to: str, request: PrivacyRequest) -> OutgoingEmail:
    link = _url(settings, "/admin/privacy")
    due = request.due_at.date().isoformat()
    return OutgoingEmail(
        to=to,
        kind="privacy.request_received",
        subject=f"New privacy request ({request.kind.lower()}), answer by {due}",
        text=(
            f"A {request.kind.lower()} request arrived from the contact page. Answer it by "
            f"{due} (30 days).\n\nRead and work it at {link}\n"
        ),
        links={"admin": link},
    )
