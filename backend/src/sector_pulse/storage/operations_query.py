from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sector_pulse.application.operations.operations_summary import OperationalRun
from sector_pulse.storage.sqlite import SQLiteDatabase

_UNIFIED_OPERATIONS_SQL = """
SELECT run_id, kind, mode, status, provider, requested_at, finished_at,
       elapsed_ms, total_cost_cny, candidate_count
FROM (
    SELECT content.run_id AS run_id,
           'content' AS kind,
           '内容生成' AS mode,
           content.status AS status,
           content.provider AS provider,
           content.requested_at AS requested_at,
           content.finished_at AS finished_at,
           content.elapsed_ms AS elapsed_ms,
           content.total_cost_cny AS total_cost_cny,
           (SELECT COUNT(*) FROM sector_analysis_cards AS cards
            WHERE cards.run_id = content.run_id) AS candidate_count
    FROM phase1b_runs AS content
    UNION ALL
    SELECT data.run_id AS run_id,
           'data' AS kind,
           CASE data.mode
               WHEN 'post_close' THEN '盘后复盘'
               ELSE '盘中分析'
           END AS mode,
           data.status AS status,
           data.provider AS provider,
           data.requested_at AS requested_at,
           data.finished_at AS finished_at,
           NULL AS elapsed_ms,
           NULL AS total_cost_cny,
           (SELECT COUNT(*) FROM real_data_candidates AS candidates
            WHERE candidates.run_id = data.run_id) AS candidate_count
    FROM real_data_runs AS data
    WHERE NOT EXISTS (
        SELECT 1 FROM phase1b_runs AS content
        WHERE content.run_id = data.run_id
    )
) AS operations
"""


class SQLiteOperationsQuery:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database
        self._database.initialize()

    def list_records(
        self, *, since: datetime | None = None, limit: int | None = None
    ) -> list[OperationalRun]:
        if limit is not None and limit < 1:
            raise ValueError("limit must be at least 1")
        statement = _UNIFIED_OPERATIONS_SQL
        parameters: list[object] = []
        if since is not None:
            statement += " WHERE requested_at >= ?"
            parameters.append(since.isoformat())
        statement += " ORDER BY requested_at DESC"
        if limit is not None:
            statement += " LIMIT ?"
            parameters.append(limit)
        with self._database.connection() as connection:
            rows = connection.execute(statement, parameters).fetchall()
        return [_row_to_operational_run(row) for row in rows]


def _row_to_operational_run(row: Any) -> OperationalRun:
    values = tuple(row)
    return OperationalRun(
        run_id=str(values[0]),
        kind=values[1],
        mode=values[2],
        status=values[3],
        provider=values[4],
        requested_at=_parse_datetime(values[5]),
        finished_at=_parse_datetime(values[6]) if values[6] else None,
        elapsed_ms=values[7],
        total_cost_cny=Decimal(str(values[8])) if values[8] is not None else None,
        candidate_count=int(values[9]) if values[9] is not None else None,
    )


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
