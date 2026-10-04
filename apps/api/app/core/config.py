"""Application settings, loaded from environment variables (12-factor).

Every deployable value lives here so containers are configured purely by env.
Production-unsafe combinations are rejected at startup rather than discovered later.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_INSECURE_DEFAULT_SECRET = "dev-insecure-change-me"  # noqa: S105 - sentinel, rejected in production


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class EmailProviderKind(StrEnum):
    CONSOLE = "console"  # logs the message (development)
    SMTP = "smtp"  # Mailpit in development; a transactional provider's SMTP relay in production
    MEMORY = "memory"  # tests


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "ApprovalReady API"
    app_env: Environment = Environment.DEVELOPMENT
    app_version: str = "0.1.0"
    git_sha: str = "unknown"
    log_level: str = "INFO"

    secret_key: SecretStr = SecretStr(_INSECURE_DEFAULT_SECRET)

    database_url: str = (
        "postgresql+psycopg://approvalready:approvalready@localhost:5432/approvalready"
    )
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_max_overflow: int = Field(default=10, ge=0, le=100)
    database_connect_timeout_seconds: float = Field(default=3.0, gt=0)

    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None

    # Strict CORS: explicit origins only. Wildcards are rejected outside development.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    # Host header allowlist (TrustedHostMiddleware). Internal service names are needed so
    # the web container and health checks can reach the API over the Docker network.
    allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "api", "testserver"]
    )

    # Always accepted in addition to ALLOWED_HOSTS: the container's own loopback (Docker health
    # checks) and the internal service name (server-side calls from the web container). Neither
    # is reachable through the public proxy, which only routes configured hostnames.
    internal_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["127.0.0.1", "api"]
    )

    health_check_timeout_seconds: float = Field(default=2.0, gt=0)

    # --- Authentication (Milestone 2) ---
    # Public origin of the web app; used to build links in emails (verify, reset, invite).
    web_base_url: str = "http://localhost:3000"
    # Secure cookies use the __Host- prefix. Plain-HTTP test clients cannot send Secure
    # cookies, so this may be disabled outside production only.
    cookie_secure: bool = True
    session_idle_minutes: int = Field(default=30, ge=5, le=24 * 60)
    session_absolute_days: int = Field(default=14, ge=1, le=90)
    session_rotation_minutes: int = Field(default=60, ge=1)
    session_rotation_grace_seconds: int = Field(default=60, ge=0, le=600)
    password_min_length: int = Field(default=12, ge=8)
    email_verification_ttl_hours: int = Field(default=48, ge=1)
    password_reset_ttl_minutes: int = Field(default=60, ge=5)
    invitation_ttl_days: int = Field(default=7, ge=1)
    # Login throttling (Redis, fixed window). Failures only; success clears the account key.
    login_window_seconds: int = Field(default=15 * 60, ge=60)
    login_max_failures_per_account: int = Field(default=5, ge=1)
    login_max_failures_per_ip: int = Field(default=30, ge=1)
    # Coarse per-IP limit on unauthenticated auth endpoints (register, reset, resend, login).
    auth_requests_per_ip_per_minute: int = Field(default=30, ge=1)
    # Emails of a given kind sent to one address per hour (stops mail bombing a victim).
    auth_emails_per_address_per_hour: int = Field(default=3, ge=1)

    # --- Email ---
    email_provider: EmailProviderKind = EmailProviderKind.CONSOLE
    email_from: str = "ApprovalReady <no-reply@approvalready.com.au>"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = False

    @field_validator("cors_origins", "allowed_hosts", "internal_hosts", mode="before")
    @classmethod
    def _parse_csv(cls, value: object) -> object:
        return _split_csv(value)

    @property
    def is_production(self) -> bool:
        return self.app_env in {Environment.PRODUCTION, Environment.STAGING}

    @property
    def session_cookie_name(self) -> str:
        return "__Host-ar_session" if self.cookie_secure else "ar_session"

    @property
    def csrf_cookie_name(self) -> str:
        return "__Host-ar_csrf" if self.cookie_secure else "ar_csrf"

    @property
    def trusted_hosts(self) -> list[str]:
        return list(dict.fromkeys([*self.allowed_hosts, *self.internal_hosts]))

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url

    @property
    def sync_database_url(self) -> str:
        """Same DSN for sync use (Alembic, Celery). psycopg 3 serves both modes."""
        return self.database_url

    @model_validator(mode="after")
    def _reject_unsafe_production_config(self) -> Settings:
        if not self.is_production:
            return self
        problems: list[str] = []
        secret = self.secret_key.get_secret_value()
        if secret == _INSECURE_DEFAULT_SECRET or len(secret) < 32:
            problems.append("SECRET_KEY must be set to a random value of at least 32 characters")
        if any(origin == "*" for origin in self.cors_origins):
            problems.append("CORS_ORIGINS must not contain '*'")
        if any(not origin.startswith("https://") for origin in self.cors_origins):
            problems.append("CORS_ORIGINS must use https:// in production")
        if "*" in self.allowed_hosts:
            problems.append("ALLOWED_HOSTS must not contain '*'")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true in production")
        if not self.web_base_url.startswith("https://"):
            problems.append("WEB_BASE_URL must use https:// in production")
        if self.email_provider == EmailProviderKind.MEMORY:
            problems.append("EMAIL_PROVIDER=memory is for tests only")
        if problems:
            raise ValueError("Unsafe production configuration: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
