import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from sector_pulse.storage.phase1b_runs_repository import Phase1BRunRow
from sector_pulse.storage.postgres import PostgresDatabase


class PostgresPhase1BRunsRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def insert(self, run: Phase1BRunRow) -> None:
        with self._database.start().begin() as connection:
            connection.execute(
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

    def get_run(self, run_id: UUID) -> Phase1BRunRow | None:
        with self._database.start().connect() as connection:
            result = connection.execute(
                text("SELECT * FROM phase1b_runs WHERE run_id = :run_id"),
                {"run_id": str(run_id)},
            )
            row = result.first()
        return self._row_to_model(row) if row else None

    def update_status(
        self,
        run_id: UUID,
        status: str,
        elapsed_ms: int | None = None,
        total_cost_cny: str | None = None,
        draft_id: UUID | None = None,
        error_message: str | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        with self._database.start().begin() as connection:
            connection.execute(
                text(
                    "UPDATE phase1b_runs SET status = :status, elapsed_ms = :elapsed_ms, "
                    "total_cost_cny = :total_cost_cny, draft_id = :draft_id, "
                    "error_message = :error_message, finished_at = :finished_at "
                    "WHERE run_id = :run_id"
                ),
                {
                    "run_id": str(run_id),
                    "status": status,
                    "elapsed_ms": elapsed_ms,
                    "total_cost_cny": total_cost_cny,
                    "draft_id": str(draft_id) if draft_id else None,
                    "error_message": error_message,
                    "finished_at": finished_at.isoformat() if finished_at else None,
                },
            )

    def list_runs(self, limit: int = 50) -> list[Phase1BRunRow]:
        with self._database.start().connect() as connection:
            result = connection.execute(
                text(
                    "SELECT * FROM phase1b_runs ORDER BY requested_at DESC LIMIT :limit"
                ),
                {"limit": limit},
            )
            rows = result.fetchall()
        return [self._row_to_model(row) for row in rows]

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
        values: tuple[object, ...] = tuple(row)  # type: ignore[arg-type]
        return Phase1BRunRow(
            run_id=UUID(str(values[0])),
            requested_at=datetime.fromisoformat(str(values[1])),
            provider=str(values[2]),
            status=str(values[3]),
            elapsed_ms=int(str(values[4])) if values[4] is not None else None,
            total_cost_cny=str(values[5]) if values[5] is not None else None,
            input_json_hash=str(values[6]) if values[6] is not None else None,
            draft_id=UUID(str(values[7])) if values[7] else None,
            error_message=str(values[8]) if values[8] is not None else None,
            finished_at=(
                datetime.fromisoformat(str(values[9])) if values[9] else None
            ),
            input_json=json.loads(str(values[10])) if values[10] else None,
        )
