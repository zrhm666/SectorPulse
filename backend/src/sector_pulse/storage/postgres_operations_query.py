from __future__ import annotations

from datetime import datetime

from sqlalchemy import text

from sector_pulse.application.operations_summary import OperationalRun
from sector_pulse.storage.operations_query import (
    _UNIFIED_OPERATIONS_SQL,
    _row_to_operational_run,
)
from sector_pulse.storage.postgres import PostgresDatabase


class PostgresOperationsQuery:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def list_records(
        self, *, since: datetime | None = None, limit: int | None = None
    ) -> list[OperationalRun]:
        if limit is not None and limit < 1:
            raise ValueError("limit must be at least 1")
        statement = _UNIFIED_OPERATIONS_SQL
        parameters: dict[str, object] = {}
        if since is not None:
            statement += " WHERE CAST(requested_at AS TIMESTAMPTZ) >= :since"
            parameters["since"] = since
        statement += " ORDER BY CAST(requested_at AS TIMESTAMPTZ) DESC"
        if limit is not None:
            statement += " LIMIT :limit"
            parameters["limit"] = limit
        engine = self._database.start()
        with engine.connect() as connection:
            result = connection.execute(text(statement), parameters)
            rows = result.fetchall()
        return [_row_to_operational_run(row) for row in rows]
