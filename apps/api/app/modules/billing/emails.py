"""Billing emails (plain text, en-AU). Transactional: they are about the customer's own
money, so they are always sent."""

from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import Settings
from app.core.email import OutgoingEmail

BRISBANE = ZoneInfo("Australia/Brisbane")


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


def _day(value: datetime) -> str:
    """The day in Brisbane time, e.g. Tuesday 11 November 2026."""
    local = value.astimezone(BRISBANE)
    return f"{local:%A} {local.day} {local:%B %Y}"


def _per(interval: str) -> str:
    return {"MONTH": " a month", "YEAR": " a year"}.get(interval, "")


def trial_started(
    settings: Settings,
    to: str,
    name: str,
    organisation_id: uuid.UUID,
    *,
    trial_end: datetime,
    amount_cents: int,
    currency: str,
    interval: str,
    cancelling: bool = False,
) -> OutgoingEmail:
    link = f"{settings.web_base_url.rstrip('/')}/account/organisations/{organisation_id}/billing"
    amount = money(amount_cents, currency)
    day = _day(trial_end)
    after = (
        "You have already cancelled, so nothing will be charged.\n\n"
        if cancelling
        else (
            f"On {day} we will charge {amount} to the card you saved, then {amount}"
            f"{_per(interval)} after that. We will email you a reminder before that first "
            "charge.\n\n"
            f"Don't want to keep it? Cancel any time before {day} and you won't be charged "
            f"anything. Go to Billing and press Manage billing: {link}\n\n"
        )
    )
    return OutgoingEmail(
        to=to,
        kind="billing.trial_started",
        subject="Your free month of ApprovalReady Plus has started",
        text=(
            f"Hi {name},\n\n"
            "Welcome to ApprovalReady Plus. Every project now gets its online project plan "
            "included: every step on a timeline, due dates, your files and notes, reminders "
            "and checked partners in your area.\n\n"
            f"Your free trial runs until {day}.\n\n" + after
        ),
        links={"billing": link},
    )


def trial_ending(
    settings: Settings,
    to: str,
    name: str,
    organisation_id: uuid.UUID,
    *,
    trial_end: datetime,
    amount_cents: int,
    currency: str,
    interval: str,
    cancelling: bool = False,
) -> OutgoingEmail:
    link = f"{settings.web_base_url.rstrip('/')}/account/organisations/{organisation_id}/billing"
    amount = money(amount_cents, currency)
    day = _day(trial_end)
    return OutgoingEmail(
        to=to,
        kind="billing.trial_ending",
        subject=f"Your free month ends on {day}",
        text=(
            f"Hi {name},\n\n"
            f"Your free trial of ApprovalReady Plus ends on {day}. On that day we will charge "
            f"{amount} to the card you saved, then {amount}{_per(interval)} after that, so "
            "your project plans keep going without a break.\n\n"
            f"Nothing to do if you'd like to keep it. To cancel instead, go to Billing and "
            f"press Manage billing before {day}, and you won't be charged: {link}\n"
        ),
        links={"billing": link},
    )
