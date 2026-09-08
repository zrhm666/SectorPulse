from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from sqlalchemy.engine import Engine


def test_default_migrations_apply_all_versions(tmp_path: Path) -> None:
    from sector_pulse.storage.sqlite.database import SQLiteDatabase

    database = SQLiteDatabase(tmp_path / "database.sqlite3")
    database.initialize()
    database.initialize()
    with database.connection() as connection:
        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    assert versions == [(n,) for n in range(1, 19)]


class RecordingEngine:
    """No server: record only the SQL boundary of the real migration runner."""

    def __init__(self) -> None:
        self.versions: list[int] = []
        self.statements: list[str] = []

    @contextmanager
    def begin(self) -> Iterator["RecordingEngine"]:
        yield self

    def exec_driver_sql(self, statement: str) -> "RecordingEngine":
        self.statements.append(statement)
        return self

    def fetchall(self) -> list[tuple[int]]:
        return [(version,) for version in self.versions]

    def execute(self, statement: Any, parameters: dict[str, int]) -> None:
        assert ":version" in str(statement)
        self.versions.append(parameters["version"])


def test_postgres_default_resources_include_all_versions_and_dialect() -> None:
    from sector_pulse.storage.postgres.database import PostgresDatabase

    engine = RecordingEngine()
    database = PostgresDatabase(
        "postgresql+psycopg://unused:unused@localhost/unused", cast(Engine, engine)
    )
    database.initialize()
    assert engine.versions == list(range(1, 19))
    assert any("INTERRUPTED" in statement for statement in engine.statements)
    assert all("PRAGMA" not in statement.upper() for statement in engine.statements)
    count = len(engine.statements)
    database.initialize()
    assert engine.versions == list(range(1, 19))
    assert len(engine.statements) == count + 2


def test_postgres_explicit_migration_directory_is_preserved(tmp_path: Path) -> None:
    from sector_pulse.storage.postgres.database import PostgresDatabase

    (tmp_path / "001_custom.sql").write_text("SELECT 42;", encoding="utf-8")
    engine = RecordingEngine()
    PostgresDatabase(
        "postgresql+psycopg://unused:unused@localhost/unused", cast(Engine, engine)
    ).initialize(tmp_path)
    assert engine.versions == [1]
    assert engine.statements[-1] == "SELECT 42"
