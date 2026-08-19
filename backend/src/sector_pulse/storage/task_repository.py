import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sector_pulse.domain.task import Checkpoint, TaskRunKey, TaskRunStatus, TaskStage
from sector_pulse.storage.sqlite import SQLiteDatabase


@dataclass(frozen=True)
class TaskEvent:
    event_id: UUID
    run_id: UUID
    source: str
    event_type: str
    old_status: TaskRunStatus | None
    new_status: TaskRunStatus | None
    idempotency_key: str | None
    summary: str
    created_at: datetime


class SQLiteTaskRepository:
    """Phase 2A 任务持久化：状态迁移和检查点均由 SQLite 事务保护。"""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database
        self._database.initialize()

    def create_or_get_run(
        self, key: TaskRunKey, provider: str, input_json: dict[str, object]
    ) -> UUID:
        run_id = uuid4()
        requested_at = datetime.now(UTC).isoformat()
        with self._database.transaction() as connection:
            if key.schedule_id is None:
                existing = connection.execute(
                    """SELECT run_id FROM task_runs
                       WHERE schedule_id IS NULL AND trading_date IS NULL
                         AND planned_slot IS NULL AND input_fingerprint = ?""",
                    (key.input_fingerprint,),
                ).fetchone()
                if existing:
                    return UUID(existing[0])
            connection.execute(
                """INSERT INTO task_runs
                (run_id, schedule_id, trading_date, planned_slot, provider,
                 input_fingerprint, status, requested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""",
                (
                    str(run_id),
                    str(key.schedule_id) if key.schedule_id else None,
                    key.trading_date,
                    key.planned_slot,
                    provider,
                    key.input_fingerprint,
                    TaskRunStatus.QUEUED.value,
                    requested_at,
                ),
            )
            row = connection.execute(
                """SELECT run_id FROM task_runs
                   WHERE schedule_id IS ? AND trading_date IS ?
                     AND planned_slot IS ? AND input_fingerprint = ?""",
                (
                    str(key.schedule_id) if key.schedule_id else None,
                    key.trading_date,
                    key.planned_slot,
                    key.input_fingerprint,
                ),
            ).fetchone()
        if row is None:
            raise RuntimeError("task run insert did not return a run")
        return UUID(row[0])

    def claim_run(
        self,
        run_id: UUID,
        worker_id: str,
        lease_until: datetime,
        *,
        now: datetime | None = None,
    ) -> bool:
        current = now or datetime.now(UTC)
        with self._database.transaction() as connection:
            cursor = connection.execute(
                """UPDATE task_runs
                   SET status = ?, worker_id = ?, lease_until = ?,
                       started_at = COALESCE(started_at, ?)
                   WHERE run_id = ?
                     AND status IN (?, ?, ?)
                     AND (lease_until IS NULL OR lease_until <= ? OR worker_id = ?)""",
                (
                    TaskRunStatus.RUNNING.value,
                    worker_id,
                    lease_until.isoformat(),
                    current.isoformat(),
                    str(run_id),
                    TaskRunStatus.QUEUED.value,
                    TaskRunStatus.RETRY_WAITING.value,
                    TaskRunStatus.RUNNING.value,
                    current.isoformat(),
                    worker_id,
                ),
            )
        return cursor.rowcount == 1

    def transition(
        self,
        run_id: UUID,
        expected: TaskRunStatus,
        target: TaskRunStatus,
        *,
        source: str,
        summary: str,
        idempotency_key: str | None = None,
        error_code: str | None = None,
    ) -> bool:
        now = datetime.now(UTC).isoformat()
        with self._database.transaction() as connection:
            cursor = connection.execute(
                """UPDATE task_runs SET status = ?, error_code = ?,
                       finished_at = CASE WHEN ? IN (?, ?, ?) THEN ? ELSE finished_at END
                   WHERE run_id = ? AND status = ?""",
                (
                    target.value,
                    error_code,
                    target.value,
                    TaskRunStatus.DEGRADED.value,
                    TaskRunStatus.READY_FOR_HUMAN_REVIEW.value,
                    TaskRunStatus.FAILED.value,
                    now,
                    str(run_id),
                    expected.value,
                ),
            )
            if cursor.rowcount != 1:
                return False
            connection.execute(
                """INSERT INTO task_events
                (event_id, run_id, source, event_type, old_status, new_status,
                 idempotency_key, summary, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid4()), str(run_id), source, "STATUS_TRANSITION",
                    expected.value, target.value, idempotency_key, summary, now,
                ),
            )
        return True

    def save_checkpoint(
        self,
        run_id: UUID,
        stage: TaskStage,
        input_fingerprint: str,
        implementation_version: str,
        payload: dict[str, object],
    ) -> Checkpoint:
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload_sha256 = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        checkpoint = Checkpoint(
            checkpoint_id=uuid4(), run_id=run_id, stage=stage,
            input_fingerprint=input_fingerprint,
            implementation_version=implementation_version, payload=payload,
            payload_sha256=payload_sha256, created_at=datetime.now(UTC),
        )
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    """INSERT INTO run_checkpoints
                    (checkpoint_id, run_id, stage, schema_version, input_fingerprint,
                     implementation_version, payload_json, payload_sha256, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(checkpoint.checkpoint_id), str(run_id), stage.value,
                        "phase2a-v1", input_fingerprint, implementation_version,
                        serialized, payload_sha256, checkpoint.created_at.isoformat(),
                    ),
                )
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise ValueError("checkpoint already exists") from exc
            raise
        return checkpoint

    def get_latest_valid_checkpoint(
        self,
        run_id: UUID,
        stage: TaskStage,
        input_fingerprint: str,
        implementation_version: str,
    ) -> Checkpoint | None:
        with self._database.connection() as connection:
            row = connection.execute(
                """SELECT checkpoint_id, run_id, stage, input_fingerprint,
                          implementation_version, payload_json, payload_sha256, created_at
                   FROM run_checkpoints
                   WHERE run_id = ? AND stage = ? AND input_fingerprint = ?
                     AND implementation_version = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (str(run_id), stage.value, input_fingerprint, implementation_version),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row[5])
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if hashlib.sha256(serialized.encode("utf-8")).hexdigest() != row[6]:
            return None
        return Checkpoint(
            checkpoint_id=UUID(row[0]), run_id=UUID(row[1]), stage=TaskStage(row[2]),
            input_fingerprint=row[3], implementation_version=row[4], payload=payload,
            payload_sha256=row[6], created_at=datetime.fromisoformat(row[7]),
        )

    def list_events(self, run_id: UUID) -> list[TaskEvent]:
        with self._database.connection() as connection:
            rows = connection.execute(
                """SELECT event_id, run_id, source, event_type, old_status,
                          new_status, idempotency_key, summary, created_at
                   FROM task_events WHERE run_id = ? ORDER BY created_at, event_id""",
                (str(run_id),),
            ).fetchall()
        return [
            TaskEvent(
                event_id=UUID(row[0]), run_id=UUID(row[1]), source=row[2],
                event_type=row[3], old_status=TaskRunStatus(row[4]) if row[4] else None,
                new_status=TaskRunStatus(row[5]) if row[5] else None,
                idempotency_key=row[6], summary=row[7],
                created_at=datetime.fromisoformat(row[8]),
            )
            for row in rows
        ]

    def count_runs(self) -> int:
        with self._database.connection() as connection:
            return connection.execute("SELECT COUNT(*) FROM task_runs").fetchone()[0]
