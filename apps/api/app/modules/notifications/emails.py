"""Notification emails (plain text, en-AU). They carry the notification's title and a link
to the page, never answers, findings, file names or anyone's contact details."""

from __future__ import annotations

from app.core.config import Settings
from app.core.email import OutgoingEmail


def notification(
    settings: Settings, to: str, name: str, title: str, body: str | None, link_path: str | None
) -> OutgoingEmail:
    base = settings.web_base_url.rstrip("/")
    link = f"{base}{link_path or '/notifications'}"
    preferences = f"{base}/notifications"
    text = f"Hi {name},\n\n{title}\n\n"
    if body:
        text += f"{body}\n\n"
    text += (
        f"Open ApprovalReady: {link}\n\n"
        f"You're getting this because a reminder or alert was set up in ApprovalReady. "
        f"See all your notifications: {preferences}\n"
    )
    return OutgoingEmail(
        to=to,
        kind="notification",
        subject=title,
        text=text,
        links={"open": link},
    )
