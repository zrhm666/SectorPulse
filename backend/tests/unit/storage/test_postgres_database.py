from sector_pulse.storage.postgres import PostgresDatabase


def test_postgres_database_keeps_asyncpg_url() -> None:
    database = PostgresDatabase("postgresql+asyncpg://user:pass@localhost:5432/db")
    assert database.url.startswith("postgresql+asyncpg://")


def test_postgres_engine_is_lazy() -> None:
    database = PostgresDatabase("postgresql+asyncpg://user:pass@localhost:5432/db")
    assert database.engine is None
    assert database.start() is not None
