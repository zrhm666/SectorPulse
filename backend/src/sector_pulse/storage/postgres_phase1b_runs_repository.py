import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from sector_pulse.storage.phase1b_runs_repository import Phase1BRunRow
from sector_pulse.storage.postgres import PostgresDatabase


class PostgresPhase1BRunsRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    async def insert(self, run: Phase1BRunRow) -> None:
        async with self._database.engine.begin() as connection:
            await connection.execute(
                text(
                    """INSERT INTO phase1b_runs
                    (run_id, requested_at, provider, status, elapsed_ms, total_cost_cny,
                     input_json_hash, draft_id, error_message, finished_at, input_json)
                    VALUES (:run_id, :requested_at, :provider, :status, :elapsed_ms,
                     :total_cost_cny, :input_json_hash, :draft_id, :error_message,
                     :finished_at, :input_json)"""
                ),
                self._values(run),
            )

    async def get_run(self, run_id: UUID) -> Phase1BRunRow | None:
        async with self._database.engine.connect() as connection:
            result = await connection.execute(
                text("SELECT * FROM phase1b_runs WHERE run_id = :run_id"),
                {"run_id": str(run_id)},
            )
            row = result.first()
        return self._row_to_model(row) if row else None

    @staticmethod
    def _values(run: Phase1BRunRow) -> dict[str, object]:
        return {
            "run_id": str(run.run_id), "requested_at": run.requested_at.isoformat(),
            "provider": run.provider, "status": run.status, "elapsed_ms": run.elapsed_ms,
            "total_cost_cny": run.total_cost_cny, "input_json_hash": run.input_json_hash,
            "draft_id": str(run.draft_id) if run.draft_id else None,
            "error_message": run.error_message,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "input_json": json.dumps(run.input_json, ensure_ascii=False, sort_keys=True)
            if run.input_json is not None else None,
        }

    @staticmethod
    def _row_to_model(row: object) -> Phase1BRunRow:
        values = tuple(row)  # type: ignore[arg-type]
        return Phase1BRunRow(
            run_id=UUID(values[0]), requested_at=datetime.fromisoformat(values[1]),
            provider=values[2], status=values[3], elapsed_ms=values[4],
            total_cost_cny=values[5], input_json_hash=values[6],
            draft_id=UUID(values[7]) if values[7] else None, error_message=values[8],
            finished_at=datetime.fromisoformat(values[9]) if values[9] else None,
            input_json=json.loads(values[10]) if values[10] else None,
        )
