"""Billing emails (plain text, en-AU). Transactional: they are about the customer's own
money, so they are always sent."""

from __future__ import annotations

import uuid

from app.core.config import Settings
from app.core.email import OutgoingEmail


def money(cents: int, currency: str) -> str:
    symbol = "$" if currency.upper() in ("AUD", "USD", "NZD") else ""
    return f"{symbol}{cents / 100:,.2f} {currency.upper()}"


def refund_sent(
    settings: Settings,
    to: str,
    name: str,
    organisation_id: uuid.UUID,
    amount_cents: int,
    currency: str,
) -> OutgoingEmail:
    link = f"{settings.web_base_url.rstrip('/')}/account/organisations/{organisation_id}/billing"
    amount = money(amount_cents, currency)
    return OutgoingEmail(
        to=to,
        kind="billing.refund_sent",
        subject=f"Your refund of {amount} is on its way",
        text=(
            f"Hi {name},\n\n"
            f"We have refunded {amount} for your professional review on ApprovalReady.\n\n"
            "It goes back to the card or account you paid with. Most banks show it within "
            "5 to 10 business days.\n\n"
            f"See your payments: {link}\n\n"
            "If it hasn't arrived after 10 business days, reply to this email.\n"
        ),
        links={"billing": link},
    )
