"""Notification emails (plain text, en-AU). They carry the notification's title and a link
to the page, never answers, findings, file names or anyone's contact details."""

from __future__ import annotations

from app.core.config import Settings
from app.core.email import OutgoingEmail

PREFERENCES_PATH = "/account#notifications"


def notification(
    settings: Settings,
    to: str,
    name: str,
    title: str,
    body: str | None,
    link_path: str | None,
    *,
    unsubscribe: tuple[str, str] | None = None,
) -> OutgoingEmail:
    """``unsubscribe`` is (page, one-click URL) from ``preferences.unsubscribe_links``; ops
    alerts, which can't be turned off, have none."""
    base = settings.web_base_url.rstrip("/")
    link = f"{base}{link_path or '/notifications'}"
    preferences = f"{base}{PREFERENCES_PATH}"
    text = f"Hi {name},\n\n{title}\n\n"
    if body:
        text += f"{body}\n\n"
    text += (
        f"Open ApprovalReady: {link}\n\n"
        f"You're getting this because a reminder or alert was set up in ApprovalReady.\n"
    )
    links = {"open": link}
    headers: dict[str, str] = {}
    if unsubscribe is not None:
        page, one_click = unsubscribe
        text += f"Stop emails like this: {page}\nChoose which emails you get: {preferences}\n"
        links["unsubscribe"] = page
        headers = {
            "List-Unsubscribe": f"<{one_click}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }
    else:
        text += f"See all your notifications: {base}/notifications\n"
    return OutgoingEmail(
        to=to,
        kind="notification",
        subject=title,
        text=text,
        links=links,
        headers=headers,
    )
