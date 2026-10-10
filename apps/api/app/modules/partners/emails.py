"""Partner account emails (plain text, en-AU). They say what happened and link to the
partner portal; the reason staff gave is in the portal, not the email."""

from __future__ import annotations

from app.core.config import Settings
from app.core.email import OutgoingEmail
from app.modules.partners.models import PartnerStatus

SUBJECTS = {
    PartnerStatus.ACTIVE: "Your ApprovalReady partner account is approved",
    PartnerStatus.REJECTED: "Your ApprovalReady partner application",
    PartnerStatus.SUSPENDED: "Your ApprovalReady partner account is suspended",
}

MESSAGES = {
    PartnerStatus.ACTIVE: (
        "{business} is now an approved ApprovalReady partner. Your dashboard shows which of "
        "your categories and service areas can receive referrals."
    ),
    PartnerStatus.REJECTED: (
        "We couldn't approve the partner application for {business} yet. Your dashboard says "
        "why and what to change; you can resubmit it from there."
    ),
    PartnerStatus.SUSPENDED: (
        "The partner account for {business} has been suspended, so it won't receive referrals. "
        "Your dashboard says why."
    ),
}


def portal_link(settings: Settings) -> str:
    return f"{settings.partners_url.rstrip('/')}/partner"


def applied(settings: Settings, to: str, name: str, business: str) -> OutgoingEmail:
    link = portal_link(settings)
    return OutgoingEmail(
        to=to,
        kind="partner.applied",
        subject="We have your ApprovalReady partner application",
        text=(
            f"Hi {name},\n\n"
            f"Thanks for applying to become an ApprovalReady partner with {business}. We check "
            "your ABN, licences and insurance before approving each category, and email you "
            "when we have decided.\n\n"
            f"Follow your application: {link}\n"
        ),
        links={"portal": link},
    )


def status_changed(
    settings: Settings, to: str, name: str, business: str, new_status: PartnerStatus
) -> OutgoingEmail | None:
    if new_status not in MESSAGES:
        return None
    link = portal_link(settings)
    return OutgoingEmail(
        to=to,
        kind="partner.status_changed",
        subject=SUBJECTS[new_status],
        text=(
            f"Hi {name},\n\n"
            f"{MESSAGES[new_status].format(business=business)}\n\n"
            f"Open your partner dashboard: {link}\n"
        ),
        links={"portal": link},
    )
