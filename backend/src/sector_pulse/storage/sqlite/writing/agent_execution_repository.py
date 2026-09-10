import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sector_pulse.domain.writing.attribution import AttributionContext
from sector_pulse.storage.sqlite.database import SQLiteDatabase


class SQLiteAgentExecutionRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def save(self, context: AttributionContext, step: int, event: dict[str, Any]) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "INSERT INTO attribution_agent_steps VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (run_id, sector_kind, sector_id, step_index, event_type) DO NOTHING",
                (
                    str(context.run_id),
                    context.sector_kind.value,
                    context.sector_id,
                    step,
                    event["type"],
                    datetime.now(UTC).isoformat(),
                    json.dumps(event, ensure_ascii=False),
                ),
            )

    def list_for_run(self, run_id: UUID) -> list[dict[str, Any]]:
        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT sector_kind, sector_id, step_index, recorded_at, payload_json "
                "FROM attribution_agent_steps WHERE run_id = ? "
                "ORDER BY recorded_at, sector_kind, sector_id, step_index",
                (str(run_id),),
            ).fetchall()
        return [
            dict(
                sector_kind=r[0],
                sector_id=r[1],
                step=r[2],
                recorded_at=r[3],
                event=json.loads(r[4]),
            )
            for r in rows
        ]
