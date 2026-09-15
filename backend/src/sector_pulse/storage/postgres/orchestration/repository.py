from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from sector_pulse.storage.orchestration.repository import OrchestrationRepository, Session
from sector_pulse.storage.postgres.database import PostgresDatabase


class PostgresSession:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def execute(self, sql: str, params: dict[str, Any]) -> int:
        return self.connection.execute(text(sql), params).rowcount

    def rows(self, sql: str, params: dict[str, Any]) -> list[tuple[Any, ...]]:
        return [tuple(row) for row in self.connection.execute(text(sql), params).fetchall()]


class PostgresOrchestrationRepository(OrchestrationRepository):
    def __init__(self, database: PostgresDatabase) -> None:
        self.database = database

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        with self.database.start().begin() as connection:
            yield PostgresSession(connection)
