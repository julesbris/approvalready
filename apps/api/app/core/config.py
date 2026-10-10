"""Application settings, loaded from environment variables (12-factor).

Every deployable value lives here so containers are configured purely by env.
Production-unsafe combinations are rejected at startup rather than discovered later.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import make_url

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


class PropertyFactsProviderKind(StrEnum):
    NONE = "none"  # no lookups: every property fact comes from the customer
    MOCK = "mock"  # canned facts for made-up test addresses (development and tests only)
    # Queensland Government open spatial services: lot and plan, land area, council area
    # and state-mapped overlays for Queensland addresses (app/modules/lookups/qld.py).
    QLD_SPATIAL = "qld_spatial"


class StorageBackendKind(StrEnum):
    LOCAL = "local"  # a directory (a Docker volume in production)
    S3 = "s3"  # any S3-compatible object store


class MalwareScannerKind(StrEnum):
    CLAMAV = "clamav"  # clamd over TCP (the clamav service)
    EICAR = "eicar"  # flags only the EICAR test file (development and tests only)


class AIProviderKind(StrEnum):
    NONE = "none"  # AI features are switched off (the default)
    MOCK = "mock"  # canned, deterministic drafts built from the input (development and tests)
    ANTHROPIC = "anthropic"  # Claude through the Anthropic API (needs ANTHROPIC_API_KEY)


class PaymentsProviderKind(StrEnum):
    NONE = "none"  # payments are switched off: nothing is for sale and no plan limits apply
    STRIPE = "stripe"  # Stripe Checkout, the customer portal and signed webhooks


class JobsMode(StrEnum):
    CELERY = "celery"  # background work goes to the worker
    INLINE = "inline"  # run straight after the request commits (tests, workerless development)


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


def _origin(url: str) -> str:
    """scheme://host[:port] of a base URL (no path)."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _db_user(url: str) -> str | None:
    return make_url(url).username


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "ApprovalReady API"
    app_env: Environment = Environment.DEVELOPMENT
    app_version: str = "0.1.0"
    git_sha: str = "unknown"
    log_level: str = "INFO"

    secret_key: SecretStr = SecretStr(_INSECURE_DEFAULT_SECRET)

    # The application connects as a dedicated non-owner role that is subject to row-level
    # security (see ``python -m app.cli provision-db-role``). Migrations and operator commands
    # that change reference data use the owner role from MIGRATION_DATABASE_URL.
    database_url: str = (
        "postgresql+psycopg://approvalready_app:approvalready_app@localhost:5432/approvalready"
    )
    migration_database_url: str | None = None
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
    # Public origin of the partner portal (Milestone 14), for partner emails and Stripe's
    # return pages. Unset: the partner portal is reached on WEB_BASE_URL.
    partners_base_url: str | None = None
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

    # --- Property facts (Milestone 5) ---
    # Where questionnaire prefill gets facts about a site; see app/modules/property_facts.
    # "qld_spatial" uses the free Queensland Government services; "mock" is refused in
    # production.
    property_facts_provider: PropertyFactsProviderKind = PropertyFactsProviderKind.NONE

    # --- Address, parcel and vessel lookups (app/modules/lookups) ---
    # Free, keyless government sources. Turn off to stop every outbound lookup.
    lookups_enabled: bool = True
    lookup_timeout_seconds: float = Field(default=12.0, gt=0, le=60)
    qld_spatial_base_url: str = "https://spatial-gis.information.qld.gov.au/arcgis/rest/services"
    # The AMSA page that links the current list of domestic commercial vessels with a vessel
    # permission (an Excel file, renamed each update). Set AMSA_VESSEL_LIST_URL to the file
    # itself to skip finding it on the page.
    amsa_vessel_list_page_url: str = (
        "https://www.amsa.gov.au/list-commercial-vessels-vessel-permission"
    )
    amsa_vessel_list_url: str | None = None
    amsa_vessel_list_max_age_hours: int = Field(default=168, ge=1)

    # --- Documents (Milestone 6) ---
    storage_backend: StorageBackendKind = StorageBackendKind.LOCAL
    storage_local_root: str = "/data/uploads"
    storage_s3_bucket: str | None = None
    storage_s3_region: str | None = None
    storage_s3_endpoint_url: str | None = None  # non-AWS providers (Wasabi, B2, MinIO)
    storage_s3_access_key_id: str | None = None
    storage_s3_secret_access_key: SecretStr | None = None
    # How long a download link to the object store stays valid.
    storage_signed_url_seconds: int = Field(default=60, ge=10, le=3600)
    upload_max_mb: int = Field(default=20, ge=1, le=100)
    upload_max_files_per_project: int = Field(default=200, ge=1, le=10_000)
    uploads_per_user_per_hour: int = Field(default=60, ge=1)
    malware_scanner: MalwareScannerKind = MalwareScannerKind.EICAR
    clamav_host: str = "clamav"
    clamav_port: int = 3310
    clamav_timeout_seconds: float = Field(default=60.0, gt=0)
    jobs_mode: JobsMode = JobsMode.CELERY

    # --- AI drafting (Milestone 12, app/modules/ai) ---
    # AI only explains findings and drafts text from data already in the project; it never
    # decides anything. "none" hides the AI buttons; "mock" is refused in production.
    ai_provider: AIProviderKind = AIProviderKind.NONE
    ai_model: str = "claude-opus-5-5"
    ai_effort: str = Field(default="medium", pattern="^(low|medium|high|xhigh|max)$")
    ai_max_output_tokens: int = Field(default=16_000, ge=1024, le=20_000)
    ai_timeout_seconds: float = Field(default=300.0, gt=0, le=600)
    # Ask the API to retry on a fallback model when the first one declines a request.
    ai_refusal_fallback: bool = True
    anthropic_api_key: SecretStr | None = None
    # Prices per million tokens, in US dollars, for the cost column of the provider log.
    ai_input_price_per_mtok_usd: float = Field(default=4.0, ge=0)
    ai_output_price_per_mtok_usd: float = Field(default=20.0, ge=0)
    ai_jobs_per_user_per_hour: int = Field(default=20, ge=1)

    # --- Payments (Milestone 13, app/modules/billing) ---
    # Prices are data that staff set at /admin/billing; nothing is sold while this is "none".
    payments_provider: PaymentsProviderKind = PaymentsProviderKind.NONE
    stripe_secret_key: SecretStr | None = None
    # The signing secret of the webhook endpoint (whsec_...), from the Stripe dashboard.
    stripe_webhook_secret: SecretStr | None = None
    stripe_api_base: str = "https://api.stripe.com"
    stripe_timeout_seconds: float = Field(default=20.0, gt=0, le=60)
    # Webhooks signed longer ago than this are refused (replay protection).
    stripe_webhook_tolerance_seconds: int = Field(default=300, ge=30, le=3600)

    # --- Marketplace analytics (Milestone 16, app/modules/analytics) ---
    # Partners see other partners' figures only as a median over at least this many partners
    # (k-anonymity); below it the figure is withheld.
    analytics_min_partners: int = Field(default=5, ge=3, le=50)

    # --- Operations (Milestone 17, app/modules/ops) ---
    # The ``backup`` service writes nightly database dumps and uploads archives here (the
    # "backups" volume); the worker copies them off the server when BACKUP_S3_BUCKET is set.
    backup_dir: str = "/backups"
    backup_s3_bucket: str | None = None
    backup_s3_region: str | None = None
    backup_s3_endpoint_url: str | None = None  # non-AWS providers (Backblaze B2, Wasabi)
    backup_s3_access_key_id: str | None = None
    backup_s3_secret_access_key: SecretStr | None = None
    backup_s3_prefix: str = Field(default="approvalready/", max_length=200)
    # A backup older than this (or a failed one) raises an alert.
    backup_max_age_hours: int = Field(default=26, ge=2, le=24 * 8)
    # The scheduler's heartbeat (every 5 minutes) older than this means background jobs
    # (reminders, scans, referrals) have stopped.
    heartbeat_max_age_minutes: int = Field(default=15, ge=6, le=24 * 60)
    # Alerts go to platform admins (in the app and by email) and to these addresses.
    ops_alert_emails: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Error tracking (Sentry or a compatible service such as GlitchTip). Off when unset.
    sentry_dsn: SecretStr | None = None

    # --- Source checks (Milestone 24, app/modules/regulatory/fetch.py) ---
    # Every week the worker reads each source document from its official address and keeps
    # a snapshot when the text changes. Only https addresses on these domains (and their
    # subdomains) that resolve to public internet addresses are ever read.
    source_checks_enabled: bool = True
    source_fetch_allowed_domains: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["gov.au", "workcoverqld.com.au"]
    )
    source_fetch_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    source_fetch_max_mb: int = Field(default=10, ge=1, le=50)
    # Pause between documents in the weekly check, to be polite to government websites.
    source_fetch_delay_seconds: float = Field(default=2.0, ge=0, le=60)

    @field_validator(
        "storage_s3_bucket",
        "storage_s3_region",
        "storage_s3_endpoint_url",
        "storage_s3_access_key_id",
        "storage_s3_secret_access_key",
        "anthropic_api_key",
        "stripe_secret_key",
        "stripe_webhook_secret",
        "partners_base_url",
        "backup_s3_bucket",
        "backup_s3_region",
        "backup_s3_endpoint_url",
        "backup_s3_access_key_id",
        "backup_s3_secret_access_key",
        "sentry_dsn",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        # Compose passes unset optional variables as empty strings.
        return None if value == "" else value

    @field_validator(
        "cors_origins",
        "allowed_hosts",
        "internal_hosts",
        "ops_alert_emails",
        "source_fetch_allowed_domains",
        mode="before",
    )
    @classmethod
    def _parse_csv(cls, value: object) -> object:
        return _split_csv(value)

    @field_validator("source_fetch_allowed_domains")
    @classmethod
    def _domains(cls, value: list[str]) -> list[str]:
        domains = [d.lower().strip(".") for d in value]
        for d in domains:
            if "." not in d or "/" in d or ":" in d:
                raise ValueError(f"{d!r} is not a domain name such as gov.au")
        return domains

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
    def partners_url(self) -> str:
        return self.partners_base_url or self.web_base_url

    @property
    def allowed_origins(self) -> list[str]:
        """CORS_ORIGINS plus the web app's own origins (the app and the partner portal), so
        a missing entry in CORS_ORIGINS can't lock users out of their own site."""
        own = [_origin(self.web_base_url), _origin(self.partners_url)]
        return list(dict.fromkeys([*self.cors_origins, *own]))

    @property
    def trusted_hosts(self) -> list[str]:
        return list(dict.fromkeys([*self.allowed_hosts, *self.internal_hosts]))

    @property
    def payments_enabled(self) -> bool:
        return (
            self.payments_provider == PaymentsProviderKind.STRIPE
            and self.stripe_secret_key is not None
            and self.stripe_webhook_secret is not None
        )

    @property
    def offsite_backups_enabled(self) -> bool:
        return self.backup_s3_bucket is not None

    @property
    def upload_max_bytes(self) -> int:
        return self.upload_max_mb * 1024 * 1024

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url

    @property
    def sync_database_url(self) -> str:
        """Same DSN for sync use (Celery). psycopg 3 serves both modes."""
        return self.database_url

    @property
    def owner_database_url(self) -> str:
        """DSN of the schema owner: migrations, role provisioning, reference-data sync."""
        return self.migration_database_url or self.database_url

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
        if self.partners_base_url and not self.partners_base_url.startswith("https://"):
            problems.append("PARTNERS_BASE_URL must use https:// in production")
        if self.migration_database_url and _db_user(self.migration_database_url) == _db_user(
            self.database_url
        ):
            problems.append(
                "DATABASE_URL must use the application role, not the owner in "
                "MIGRATION_DATABASE_URL (row-level security does not apply to the owner)"
            )
        if self.email_provider == EmailProviderKind.MEMORY:
            problems.append("EMAIL_PROVIDER=memory is for tests only")
        if self.property_facts_provider == PropertyFactsProviderKind.MOCK:
            problems.append("PROPERTY_FACTS_PROVIDER=mock returns made-up data and is not allowed")
        if self.malware_scanner == MalwareScannerKind.EICAR:
            problems.append("MALWARE_SCANNER must be clamav (eicar only detects a test file)")
        if self.storage_backend == StorageBackendKind.S3 and not self.storage_s3_bucket:
            problems.append("STORAGE_S3_BUCKET is required when STORAGE_BACKEND=s3")
        if self.ai_provider == AIProviderKind.MOCK:
            problems.append("AI_PROVIDER=mock writes canned text and is not allowed")
        if self.ai_provider == AIProviderKind.ANTHROPIC and not self.anthropic_api_key:
            problems.append("ANTHROPIC_API_KEY is required when AI_PROVIDER=anthropic")
        if self.payments_provider == PaymentsProviderKind.STRIPE and not (
            self.stripe_secret_key and self.stripe_webhook_secret
        ):
            problems.append(
                "STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET are required when "
                "PAYMENTS_PROVIDER=stripe"
            )
        if self.backup_s3_bucket and not (
            self.backup_s3_access_key_id and self.backup_s3_secret_access_key
        ):
            problems.append(
                "BACKUP_S3_ACCESS_KEY_ID and BACKUP_S3_SECRET_ACCESS_KEY are required when "
                "BACKUP_S3_BUCKET is set"
            )
        if problems:
            raise ValueError("Unsafe production configuration: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
