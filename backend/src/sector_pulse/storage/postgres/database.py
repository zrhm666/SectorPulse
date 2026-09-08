from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


@dataclass
class PostgresDatabase:
    """Synchronous PostgreSQL connection and transactional migration boundary."""

    url: str
    engine: Engine | None = None

    def __post_init__(self) -> None:
        scheme = urlparse(self.url).scheme
        if scheme in {"postgres", "postgresql", "postgresql+asyncpg"}:
            remainder = self.url.split("://", 1)[1]
            self.url = f"postgresql+psycopg://{remainder}"

    def start(self) -> Engine:
        if self.engine is None:
            self.engine = create_engine(self.url, pool_pre_ping=True)
        return self.engine

    def healthcheck(self) -> bool:
        with self.start().connect() as connection:
            return int(connection.execute(text("SELECT 1")).scalar_one()) == 1

    def close(self) -> None:
        if self.engine is not None:
            self.engine.dispose()
            self.engine = None

    def initialize(self, migration_dir: Path | None = None) -> None:
        """Apply each migration version atomically, including its dialect supplement."""
        root = migration_dir or Path(__file__).resolve().parents[1] / "migrations"
        engine = self.start()
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """CREATE TABLE IF NOT EXISTS schema_migrations
                (version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"""
            )
            rows = connection.exec_driver_sql(
                "SELECT version FROM schema_migrations"
            ).fetchall()
            applied = {row[0] for row in rows}

        for path in sorted(root.glob("[0-9][0-9][0-9]_*.sql")):
            version = int(path.name[:3])
            if version in applied:
                continue
            with engine.begin() as connection:
                migration_paths = [path]
                dialect_path = root / "postgres" / path.name
                if dialect_path.is_file():
                    migration_paths.append(dialect_path)
                for migration_path in migration_paths:
                    for statement in self._statements(migration_path):
                        connection.exec_driver_sql(statement)
                connection.execute(
                    text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                    {"version": version},
                )

    @staticmethod
    def _statements(path: Path) -> list[str]:
        return [
            part.strip()
            for part in path.read_text(encoding="utf-8").split(";")
            if part.strip()
        ]
