"""Email provider interface with console, SMTP and in-memory implementations.

Development uses Mailpit over SMTP (see docker-compose.yml). Production points SMTP at a
transactional provider's relay; a provider-specific HTTP API can implement the same
protocol later without touching callers.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

from app.core.config import EmailProviderKind, Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutgoingEmail:
    to: str
    subject: str
    text: str
    # Machine-readable kind (e.g. "auth.verify_email") for logs and tests; never shown.
    kind: str
    # Links carried by the message, so tests and the console provider can surface them.
    links: dict[str, str] = field(default_factory=dict)
    # Extra message headers (``List-Unsubscribe`` on notification emails).
    headers: dict[str, str] = field(default_factory=dict)


class EmailProvider(Protocol):
    async def send(self, message: OutgoingEmail) -> None: ...


class ConsoleEmailProvider:
    """Logs emails instead of sending them. Development only: links appear in the log."""

    async def send(self, message: OutgoingEmail) -> None:
        logger.info(
            "email (console provider)",
            extra={
                "to": message.to,
                "kind": message.kind,
                "subject": message.subject,
                "links": message.links,
            },
        )


class MemoryEmailProvider:
    def __init__(self) -> None:
        self.outbox: list[OutgoingEmail] = []

    async def send(self, message: OutgoingEmail) -> None:
        self.outbox.append(message)


class SmtpEmailProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _send_sync(self, message: OutgoingEmail) -> None:
        s = self.settings
        msg = EmailMessage()
        msg["From"] = s.email_from
        msg["To"] = message.to
        msg["Subject"] = message.subject
        for name, value in message.headers.items():
            msg[name] = value
        msg.set_content(message.text)
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
            if s.smtp_starttls:
                # Explicit context: smtplib's default does not verify the certificate.
                smtp.starttls(context=ssl.create_default_context())
            if s.smtp_username and s.smtp_password:
                smtp.login(s.smtp_username, s.smtp_password.get_secret_value())
            smtp.send_message(msg)

    async def send(self, message: OutgoingEmail) -> None:
        await asyncio.to_thread(self._send_sync, message)


def create_email_provider(settings: Settings) -> EmailProvider:
    match settings.email_provider:
        case EmailProviderKind.SMTP:
            return SmtpEmailProvider(settings)
        case EmailProviderKind.MEMORY:
            return MemoryEmailProvider()
        case _:
            return ConsoleEmailProvider()
