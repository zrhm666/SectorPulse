from pathlib import Path

import pytest
from sector_pulse.config.settings import ApplicationSettings
from sector_pulse.storage.database_config import resolve_database_config
from sector_pulse.storage.database_runtime import (
    build_database,
    close_database,
    initialize_database,
)
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.sqlite import SQLiteDatabase


def test_build_database_defaults_to_sqlite(tmp_path: Path) -> None:
    settings = ApplicationSettings(database_path=tmp_path / "app.db")
    database = build_database(settings, settings.database_path)
    assert isinstance(database, SQLiteDatabase)


def test_build_database_selects_postgres() -> None:
    settings = ApplicationSettings(
        database_url="postgresql+asyncpg://user:pass@localhost/db"
    )
    database = build_database(settings, Path("ignored.db"))
    assert isinstance(database, PostgresDatabase)
    assert database.url == "postgresql+psycopg://user:pass@localhost/db"


@pytest.mark.parametrize(
    "url",
    [
        "postgres://user:pass@localhost/db",
        "postgresql://user:pass@localhost/db",
        "postgresql+asyncpg://user:pass@localhost/db",
    ],
)
def test_legacy_postgres_urls_are_normalized_for_sync_psycopg(url: str) -> None:
    config = resolve_database_config(url, "unused.db")

    assert config.url == "postgresql+psycopg://user:pass@localhost/db"


@pytest.mark.asyncio
async def test_initialize_sqlite_from_async_lifespan(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "app.db")
    await initialize_database(database)
    assert (tmp_path / "app.db").exists()


@pytest.mark.asyncio
async def test_async_lifespan_calls_sync_postgres_boundary(monkeypatch) -> None:
    database = PostgresDatabase("postgresql+psycopg://user:pass@localhost/db")
    calls: list[str] = []
    monkeypatch.setattr(database, "initialize", lambda: calls.append("initialize"))
    monkeypatch.setattr(database, "close", lambda: calls.append("close"))

    await initialize_database(database)
    await close_database(database)

    assert calls == ["initialize", "close"]
