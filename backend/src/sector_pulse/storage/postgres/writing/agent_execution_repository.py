import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from sector_pulse.domain.writing.attribution import AttributionContext
from sector_pulse.storage.postgres.database import PostgresDatabase


class PostgresAgentExecutionRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def save(self, context: AttributionContext, step: int, event: dict[str, Any]) -> None:
        with self._database.start().begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO attribution_agent_steps VALUES (:run, :kind, :sector, :step, "
                    ":event, :at, :payload) ON CONFLICT "
                    "(run_id, sector_kind, sector_id, step_index, event_type) DO NOTHING"
                ),
                dict(
                    run=str(context.run_id),
                    kind=context.sector_kind.value,
                    sector=context.sector_id,
                    step=step,
                    event=event["type"],
                    at=datetime.now(UTC).isoformat(),
                    payload=json.dumps(event, ensure_ascii=False),
                ),
            )

    def list_for_run(self, run_id: UUID) -> list[dict[str, Any]]:
        with self._database.start().connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT sector_kind, sector_id, step_index, recorded_at, payload_json "
                    "FROM attribution_agent_steps WHERE run_id = :run "
                    "ORDER BY recorded_at, sector_kind, sector_id, step_index"
                ),
                {"run": str(run_id)},
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
