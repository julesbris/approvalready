import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Environment
from tests.conftest import make_settings

STRONG_SECRET = "x" * 48


def test_csv_env_values_are_split(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, https://b.example")
    monkeypatch.setenv("ALLOWED_HOSTS", "api.example,localhost")
    from app.core.config import Settings

    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.cors_origins == ["https://a.example", "https://b.example"]
    assert settings.allowed_hosts == ["api.example", "localhost"]


def test_development_allows_insecure_defaults() -> None:
    settings = make_settings(app_env=Environment.DEVELOPMENT)
    assert not settings.is_production


def test_production_rejects_default_secret() -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        make_settings(app_env=Environment.PRODUCTION, cors_origins=["https://app.example"])


def test_production_rejects_short_secret() -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        make_settings(
            app_env=Environment.PRODUCTION,
            secret_key=SecretStr("short"),
            cors_origins=["https://app.example"],
        )


@pytest.mark.parametrize("origins", [["*"], ["http://app.example"]])
def test_production_rejects_unsafe_cors(origins: list[str]) -> None:
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        make_settings(
            app_env=Environment.PRODUCTION,
            secret_key=SecretStr(STRONG_SECRET),
            cors_origins=origins,
        )


def test_production_rejects_wildcard_hosts() -> None:
    with pytest.raises(ValidationError, match="ALLOWED_HOSTS"):
        make_settings(
            app_env=Environment.PRODUCTION,
            secret_key=SecretStr(STRONG_SECRET),
            cors_origins=["https://app.example"],
            allowed_hosts=["*"],
        )


def test_production_accepts_safe_config() -> None:
    settings = make_settings(
        app_env=Environment.PRODUCTION,
        secret_key=SecretStr(STRONG_SECRET),
        cors_origins=["https://app.approvalready.com.au"],
        allowed_hosts=["api.approvalready.com.au", "api"],
    )
    assert settings.is_production


def test_celery_urls_default_to_redis() -> None:
    settings = make_settings(redis_url="redis://cache:6379/2")
    assert settings.broker_url == "redis://cache:6379/2"
    assert settings.result_backend == "redis://cache:6379/2"
