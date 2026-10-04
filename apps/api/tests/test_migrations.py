import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text

from app.db.base import Base
from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.integration


def _config() -> Config:
    cfg = Config("alembic.ini")
    cfg.attributes["database_url"] = TEST_DATABASE_URL
    return cfg


def _extensions() -> set[str]:
    engine = create_engine(TEST_DATABASE_URL)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT extname FROM pg_extension")).scalars().all()
    engine.dispose()
    return set(rows)


def test_upgrade_downgrade_roundtrip() -> None:
    cfg = _config()
    command.upgrade(cfg, "head")
    assert {"pgcrypto", "citext"} <= _extensions()
    command.downgrade(cfg, "base")
    assert not ({"pgcrypto", "citext"} & _extensions())
    command.upgrade(cfg, "head")
    assert {"pgcrypto", "citext"} <= _extensions()


def test_models_match_migrations() -> None:
    command.upgrade(_config(), "head")
    engine = create_engine(TEST_DATABASE_URL)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == [], f"Models and migrations have drifted: {diff}"


def test_server_is_postgres_18() -> None:
    engine = create_engine(TEST_DATABASE_URL)
    with engine.connect() as conn:
        version = conn.execute(text("SHOW server_version_num")).scalar_one()
    engine.dispose()
    assert int(version) >= 180000
