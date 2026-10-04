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

    @field_validator("cors_origins", "allowed_hosts", "internal_hosts", mode="before")
    @classmethod
    def _parse_csv(cls, value: object) -> object:
        return _split_csv(value)

    @property
    def is_production(self) -> bool:
        return self.app_env in {Environment.PRODUCTION, Environment.STAGING}

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
        if problems:
            raise ValueError("Unsafe production configuration: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
