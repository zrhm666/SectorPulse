from sector_pulse.storage.postgres import PostgresDatabase
from sqlalchemy.engine import Engine


def test_postgres_database_builds_sync_engine() -> None:
    database = PostgresDatabase("postgresql+psycopg://user:pass@localhost:5432/db")

    engine = database.start()

    assert isinstance(engine, Engine)
    database.close()
    assert database.engine is None


def test_postgres_engine_is_lazy() -> None:
    database = PostgresDatabase("postgresql+psycopg://user:pass@localhost:5432/db")
    assert database.engine is None
    assert database.start() is not None
