import pytest
from sector_pulse.storage.database_config import resolve_database_config


def test_database_config_defaults_to_sqlite() -> None:
    config = resolve_database_config(None, "data/test.db")
    assert config.backend == "sqlite"
    assert config.url == "data/test.db"


def test_database_config_recognizes_asyncpg_url() -> None:
    config = resolve_database_config("postgresql+asyncpg://user:pass@localhost/db", "ignored.db")
    assert config.backend == "postgresql"


def test_database_config_rejects_unknown_scheme() -> None:
    with pytest.raises(ValueError, match="unsupported database URL scheme"):
        resolve_database_config("mysql://localhost/db", "ignored.db")
