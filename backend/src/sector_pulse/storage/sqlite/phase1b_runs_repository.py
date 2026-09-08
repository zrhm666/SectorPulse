import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sector_pulse.storage.sqlite.database import SQLiteDatabase


@dataclass
class Phase1BRunRow:
    run_id: UUID
    requested_at: datetime
    provider: str
    status: str
    elapsed_ms: int | None = None
    total_cost_cny: str | None = None
    input_json_hash: str | None = None
    draft_id: UUID | None = None
    error_message: str | None = None
    finished_at: datetime | None = None
    input_json: dict[str, object] | None = None
    retry_of_run_id: UUID | None = None


class SQLitePhase1BRunsRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database
        self._database.initialize()

    def insert(self, run: Phase1BRunRow) -> None:
        with self._database.transaction() as conn:
            conn.execute(
                """INSERT INTO phase1b_runs
                (run_id, requested_at, provider, status, elapsed_ms, total_cost_cny,
                 input_json_hash, draft_id, error_message, finished_at, input_json, retry_of_run_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(run.run_id), run.requested_at.isoformat(), run.provider,
                    run.status, run.elapsed_ms, run.total_cost_cny,
                    run.input_json_hash, str(run.draft_id) if run.draft_id else None,
                    run.error_message, run.finished_at.isoformat() if run.finished_at else None,
                    json.dumps(run.input_json, ensure_ascii=False, sort_keys=True)
                    if run.input_json is not None else None,
                    str(run.retry_of_run_id) if run.retry_of_run_id else None,
                ),
            )

    def update_status(
        self, run_id: UUID, status: str, elapsed_ms: int | None = None,
        total_cost_cny: str | None = None, draft_id: UUID | None = None,
        error_message: str | None = None, finished_at: datetime | None = None,
    ) -> None:
        with self._database.transaction() as conn:
            conn.execute(
                """UPDATE phase1b_runs
                SET status = ?, elapsed_ms = ?, total_cost_cny = ?, draft_id = ?,
                    error_message = ?, finished_at = ? WHERE run_id = ?""",
                (status, elapsed_ms, total_cost_cny, str(draft_id) if draft_id else None,
                 error_message, finished_at.isoformat() if finished_at else None, str(run_id)),
            )

    def list_runs(self, limit: int = 50) -> list[Phase1BRunRow]:
        with self._database.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM phase1b_runs ORDER BY requested_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_model(r) for r in rows]

    def mark_interrupted(self, now: datetime) -> int:
        with self._database.transaction() as connection:
            result = connection.execute(
                """UPDATE phase1b_runs
                   SET status = 'INTERRUPTED', finished_at = ?,
                       error_message = 'process restarted before content completion'
                   WHERE status = 'RUNNING'""",
                (now.isoformat(),),
            )
        return result.rowcount

    def get_run(self, run_id: UUID) -> Phase1BRunRow | None:
        with self._database.connection() as conn:
            row = conn.execute(
                "SELECT * FROM phase1b_runs WHERE run_id = ?", (str(run_id),)
            ).fetchone()
        return self._row_to_model(row) if row else None

    @staticmethod
    def _row_to_model(row: object) -> Phase1BRunRow:
        r: tuple[Any, ...] = tuple(row)  # type: ignore[arg-type]
        return Phase1BRunRow(
            run_id=UUID(r[0]), requested_at=datetime.fromisoformat(r[1]), provider=r[2],
            status=r[3], elapsed_ms=r[4], total_cost_cny=r[5], input_json_hash=r[6],
            draft_id=UUID(r[7]) if r[7] else None, error_message=r[8],
            finished_at=datetime.fromisoformat(r[9]) if r[9] else None,
            input_json=json.loads(r[10]) if r[10] else None,
            retry_of_run_id=UUID(r[11]) if r[11] else None,
        )
