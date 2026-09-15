import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sector_pulse.storage.orchestration.repository import OrchestrationRepository, Session
from sector_pulse.storage.sqlite.database import SQLiteDatabase


class SQLiteSession:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def execute(self, sql: str, params: dict[str, Any]) -> int:
        return self.connection.execute(sql, params).rowcount

    def rows(self, sql: str, params: dict[str, Any]) -> list[tuple[Any, ...]]:
        return self.connection.execute(sql, params).fetchall()


class SQLiteOrchestrationRepository(OrchestrationRepository):
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        with self.database.transaction() as connection:
            yield SQLiteSession(connection)
