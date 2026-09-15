from __future__ import annotations

from datetime import datetime

from sqlalchemy import text

from sector_pulse.application.operations.operations_summary import (
    OperationalRun,
    as_utc,
    merge_operational_runs,
)
from sector_pulse.application.operations.orchestration_projection import (
    project_multi_agent_runs,
)
from sector_pulse.ports.orchestration import SnapshotRepository
from sector_pulse.storage.postgres.database import PostgresDatabase
from sector_pulse.storage.sqlite.operations_query import (
    _UNIFIED_OPERATIONS_SQL,
    _row_to_operational_run,
)


class PostgresOperationsQuery:
    def __init__(
        self,
        database: PostgresDatabase,
        orchestration: SnapshotRepository,
    ) -> None:
        self._database = database
        self._orchestration = orchestration

    def list_records(
        self, *, since: datetime | None = None, limit: int | None = None
    ) -> list[OperationalRun]:
        if limit is not None and limit < 1:
            raise ValueError("limit must be at least 1")
        return merge_operational_runs(
            self._legacy_records(since),
            self._multi_agent_records(since),
            limit=limit,
        )

    def _legacy_records(self, since: datetime | None) -> list[OperationalRun]:
        statement = _UNIFIED_OPERATIONS_SQL
        parameters: dict[str, object] = {}
        if since is not None:
            statement += " WHERE CAST(requested_at AS TIMESTAMPTZ) >= :since"
            parameters["since"] = since
        statement += " ORDER BY CAST(requested_at AS TIMESTAMPTZ) DESC"
        engine = self._database.start()
        with engine.connect() as connection:
            rows = connection.execute(text(statement), parameters).fetchall()
        return [_row_to_operational_run(row) for row in rows]

    def _multi_agent_records(self, since: datetime | None) -> list[OperationalRun]:
        records = project_multi_agent_runs(self._orchestration.list_snapshots(limit=None))
        if since is None:
            return records
        threshold = as_utc(since)
        return [record for record in records if as_utc(record.requested_at) >= threshold]
