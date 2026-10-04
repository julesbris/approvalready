from __future__ import annotations

from typing import Any, ClassVar

import pytest
from pydantic import SecretStr, ValidationError

from app.core import email as email_module
from app.core.config import EmailProviderKind, Environment
from app.core.email import (
    ConsoleEmailProvider,
    MemoryEmailProvider,
    OutgoingEmail,
    SmtpEmailProvider,
    create_email_provider,
)
from tests.conftest import make_settings

MESSAGE = OutgoingEmail(to="a@example.com", subject="Hi", text="Body", kind="test")


class FakeSMTP:
    instances: ClassVar[list[FakeSMTP]] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host, self.port = host, port
        self.calls: list[tuple[str, Any]] = []
        FakeSMTP.instances.append(self)

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def starttls(self, context: Any = None) -> None:
        self.calls.append(("starttls", context))

    def login(self, user: str, password: str) -> None:
        self.calls.append(("login", (user, password)))

    def send_message(self, msg: Any) -> None:
        self.calls.append(("send", msg))


async def test_smtp_provider_uses_verified_tls_and_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(email_module.smtplib, "SMTP", FakeSMTP)
    settings = make_settings(
        email_provider=EmailProviderKind.SMTP,
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_starttls=True,
        smtp_username="user",
        smtp_password=SecretStr("pw"),
    )
    provider = create_email_provider(settings)
    assert isinstance(provider, SmtpEmailProvider)
    await provider.send(MESSAGE)
    smtp = FakeSMTP.instances[-1]
    assert (smtp.host, smtp.port) == ("smtp.example.com", 587)
    kinds = [c[0] for c in smtp.calls]
    assert kinds == ["starttls", "login", "send"]
    context = smtp.calls[0][1]
    assert context is not None and context.check_hostname  # certificate is verified
    sent = smtp.calls[2][1]
    assert sent["To"] == "a@example.com" and sent["Subject"] == "Hi"


async def test_memory_and_console_providers() -> None:
    memory = create_email_provider(make_settings(email_provider=EmailProviderKind.MEMORY))
    assert isinstance(memory, MemoryEmailProvider)
    await memory.send(MESSAGE)
    assert memory.outbox == [MESSAGE]
    console = create_email_provider(make_settings(email_provider=EmailProviderKind.CONSOLE))
    assert isinstance(console, ConsoleEmailProvider)
    await console.send(MESSAGE)


def test_production_rejects_memory_email() -> None:
    with pytest.raises(ValidationError, match="EMAIL_PROVIDER"):
        make_settings(
            app_env=Environment.PRODUCTION,
            secret_key=SecretStr("z" * 48),
            cors_origins=["https://app.approvalready.com.au"],
            email_provider=EmailProviderKind.MEMORY,
        )
