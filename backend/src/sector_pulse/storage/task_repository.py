import hashlib
import json
from collections.abc import Mapping
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
        self,
        key: TaskRunKey,
        provider: str,
        input_json: dict[str, object],
        *,
        retry_of_run_id: UUID | None = None,
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
                 input_fingerprint, status, requested_at, retry_of_run_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""",
                (
                    str(run_id),
                    str(key.schedule_id) if key.schedule_id else None,
                    key.trading_date,
                    key.planned_slot,
                    provider,
                    key.input_fingerprint,
                    TaskRunStatus.QUEUED.value,
                    requested_at,
                    str(retry_of_run_id) if retry_of_run_id else None,
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
                       started_at = COALESCE(started_at, ?), heartbeat_at = ?
                   WHERE run_id = ?
                     AND status IN (?, ?, ?)
                     AND (lease_until IS NULL OR lease_until <= ? OR worker_id = ?)""",
                (
                    TaskRunStatus.RUNNING.value,
                    worker_id,
                    lease_until.isoformat(),
                    current.isoformat(),
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
                       finished_at = CASE WHEN ? IN (?, ?, ?, ?, ?) THEN ? ELSE finished_at END
                   WHERE run_id = ? AND status = ?""",
                (
                    target.value,
                    error_code,
                    target.value,
                    TaskRunStatus.DEGRADED.value,
                    TaskRunStatus.READY_FOR_HUMAN_REVIEW.value,
                    TaskRunStatus.FAILED.value,
                    TaskRunStatus.CANCELLED.value,
                    TaskRunStatus.INTERRUPTED.value,
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

    def record_task_event(
        self,
        run_id: UUID,
        *,
        source: str,
        event_type: str,
        summary: str,
        idempotency_key: str | None,
        created_at: datetime,
    ) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                """INSERT INTO task_events
                (event_id, run_id, source, event_type, idempotency_key, summary, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid4()), str(run_id), source, event_type,
                    idempotency_key, summary, created_at.isoformat(),
                ),
            )

    def count_runs(self) -> int:
        with self._database.connection() as connection:
            row = connection.execute("SELECT COUNT(*) FROM task_runs").fetchone()
        return int(row[0]) if row else 0

    def get_task_detail(self, run_id: UUID) -> dict[str, object] | None:
        with self._database.connection() as connection:
            row = connection.execute(
                """SELECT run_id, status, provider, input_fingerprint, requested_at,
                          started_at, finished_at, error_code, downgrade_reasons_json,
                          retry_of_run_id, cancel_requested_at, interrupted_reason,
                          heartbeat_at, data_run_id
                   FROM task_runs WHERE run_id = ?""",
                (str(run_id),),
            ).fetchone()
            if row is None:
                return None
            attempts = connection.execute(
                """SELECT stage, attempt_no, status, input_fingerprint, provider,
                          error_code, started_at, finished_at
                   FROM run_stage_attempts WHERE run_id = ?
                   ORDER BY started_at, stage, attempt_no""",
                (str(run_id),),
            ).fetchall()
        return {
            "run_id": row[0], "status": row[1], "provider": row[2],
            "input_fingerprint": row[3], "requested_at": row[4],
            "started_at": row[5], "finished_at": row[6], "error_code": row[7],
            "downgrade_reasons": json.loads(row[8]),
            "retry_of_run_id": row[9], "cancel_requested_at": row[10],
            "interrupted_reason": row[11], "heartbeat_at": row[12],
            "data_run_id": row[13],
            "stages": [
                {
                    "stage": item[0], "attempt_no": item[1], "status": item[2],
                    "input_fingerprint": item[3], "provider": item[4],
                    "error_code": item[5], "started_at": item[6], "finished_at": item[7],
                }
                for item in attempts
            ],
            "events": [event.__dict__ for event in self.list_events(run_id)],
        }

    def recover_expired_leases(self, now: datetime | None = None) -> int:
        current = (now or datetime.now(UTC)).isoformat()
        with self._database.transaction() as connection:
            cursor = connection.execute(
                """UPDATE task_runs SET status = ?, worker_id = NULL, lease_until = NULL
                   WHERE status = ? AND lease_until IS NOT NULL AND lease_until <= ?""",
                (TaskRunStatus.RETRY_WAITING.value, TaskRunStatus.RUNNING.value, current),
            )
        return cursor.rowcount

    def request_cancel(self, run_id: UUID, requested_at: datetime) -> bool:
        terminal = tuple(status.value for status in TaskRunStatus if status.is_terminal)
        placeholders = ",".join("?" for _ in terminal)
        with self._database.transaction() as connection:
            cursor = connection.execute(
                f"""UPDATE task_runs SET cancel_requested_at = ?
                    WHERE run_id = ? AND status NOT IN ({placeholders})""",
                (requested_at.isoformat(), str(run_id), *terminal),
            )
            if cursor.rowcount != 1:
                return False
            connection.execute(
                """INSERT INTO task_events
                (event_id, run_id, source, event_type, summary, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid4()),
                    str(run_id),
                    "api",
                    "CANCEL_REQUESTED",
                    "cancel requested",
                    requested_at.isoformat(),
                ),
            )
        return True

    def recover_interrupted(self, now: datetime, reason: str) -> int:
        timestamp = now.isoformat()
        with self._database.transaction() as connection:
            rows = connection.execute(
                "SELECT run_id FROM task_runs WHERE status = ?",
                (TaskRunStatus.RUNNING.value,),
            ).fetchall()
            if not rows:
                return 0
            connection.execute(
                """UPDATE task_runs
                   SET status = ?, worker_id = NULL, lease_until = NULL,
                       heartbeat_at = ?, interrupted_reason = ?, finished_at = ?
                   WHERE status = ?""",
                (
                    TaskRunStatus.INTERRUPTED.value,
                    timestamp,
                    reason,
                    timestamp,
                    TaskRunStatus.RUNNING.value,
                ),
            )
            connection.executemany(
                """INSERT INTO task_events
                (event_id, run_id, source, event_type, old_status, new_status,
                 summary, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        str(uuid4()),
                        row[0],
                        "startup-recovery",
                        "STATUS_TRANSITION",
                        TaskRunStatus.RUNNING.value,
                        TaskRunStatus.INTERRUPTED.value,
                        reason,
                        timestamp,
                    )
                    for row in rows
                ],
            )
        return len(rows)

    def link_data_run(self, run_id: UUID, data_run_id: UUID) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "UPDATE task_runs SET data_run_id = ? WHERE run_id = ?",
                (str(data_run_id), str(run_id)),
            )

    def list_linked_runs(self) -> list[tuple[UUID, UUID]]:
        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT run_id, data_run_id FROM task_runs WHERE data_run_id IS NOT NULL"
            ).fetchall()
        return [(UUID(row[0]), UUID(row[1])) for row in rows]

    def claim_ready_linked_run(self, run_id: UUID, data_run_id: UUID) -> bool:
        now = datetime.now(UTC)
        with self._database.transaction() as connection:
            cursor = connection.execute(
                """UPDATE task_runs
                   SET status = ?, started_at = COALESCE(started_at, ?), heartbeat_at = ?
                   WHERE run_id = ? AND data_run_id = ? AND status = ?""",
                (
                    TaskRunStatus.RUNNING.value,
                    now.isoformat(),
                    now.isoformat(),
                    str(run_id),
                    str(data_run_id),
                    TaskRunStatus.QUEUED.value,
                ),
            )
            if cursor.rowcount != 1:
                return False
            connection.execute(
                """INSERT INTO task_events
                (event_id, run_id, source, event_type, old_status, new_status,
                 summary, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid4()), str(run_id), "scheduled-data-bridge",
                    "STATUS_TRANSITION", TaskRunStatus.QUEUED.value,
                    TaskRunStatus.RUNNING.value, "ready data run claimed",
                    now.isoformat(),
                ),
            )
        return True

    def fail_claimed_run(self, run_id: UUID, error_code: str) -> bool:
        return self.transition(
            run_id,
            TaskRunStatus.RUNNING,
            TaskRunStatus.FAILED,
            source="scheduled-data-bridge",
            summary="content generation start failed",
            error_code=error_code,
        )

    def mark_content_started(self, run_id: UUID, created_at: datetime) -> None:
        self.record_task_event(
            run_id,
            source="scheduled-data-bridge",
            event_type="CONTENT_GENERATION_STARTED",
            summary="content generation started",
            idempotency_key=None,
            created_at=created_at,
        )

    def insert_schedule(self, values: Mapping[str, object]) -> None:
        enabled = values["enabled"]
        if not isinstance(enabled, bool):
            raise TypeError("schedule enabled must be boolean")
        version = values.get("version", 1)
        if not isinstance(version, int) or isinstance(version, bool):
            raise TypeError("schedule version must be an integer")
        with self._database.transaction() as connection:
            connection.execute(
                """INSERT INTO schedules
                (schedule_id, name, mode, timezone, local_time, trading_days,
                 schedule_spec_json, input_template_json, enabled, version,
                 next_run_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    values["schedule_id"], values["name"], values["mode"],
                    values["timezone"], values["local_time"], values["trading_days"],
                    json.dumps(values.get("schedule_spec", {}), sort_keys=True),
                    json.dumps(
                        values.get("input_template", {}), ensure_ascii=False, sort_keys=True
                    ),
                    int(enabled), version,
                    values.get("next_run_at"), values["created_at"], values["updated_at"],
                ),
            )

    def list_schedules(self) -> list[dict[str, object]]:
        with self._database.connection() as connection:
            rows = connection.execute(
                """SELECT schedule_id, name, mode, timezone, local_time, trading_days,
                          schedule_spec_json, input_template_json, enabled, version,
                          next_run_at, last_triggered_at, created_at, updated_at
                   FROM schedules ORDER BY created_at, schedule_id"""
            ).fetchall()
        return [
            {
                "schedule_id": row[0], "name": row[1], "mode": row[2],
                "timezone": row[3], "local_time": row[4], "trading_days": row[5],
                "schedule_spec": json.loads(row[6]), "input_template": json.loads(row[7]),
                "enabled": bool(row[8]), "version": row[9], "next_run_at": row[10],
                "last_triggered_at": row[11], "created_at": row[12], "updated_at": row[13],
            }
            for row in rows
        ]

    def get_schedule(self, schedule_id: UUID) -> dict[str, object] | None:
        return next(
            (item for item in self.list_schedules() if item["schedule_id"] == str(schedule_id)),
            None,
        )

    def list_due_schedules(self, now: datetime) -> list[dict[str, object]]:
        due_at = now.isoformat()
        return [
            item
            for item in self.list_schedules()
            if item["enabled"]
            and item["next_run_at"] is not None
            and str(item["next_run_at"]) <= due_at
        ]

    def record_schedule_trigger(
        self,
        schedule_id: UUID,
        triggered_at: datetime,
        next_run_at: datetime | None,
    ) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                """UPDATE schedules
                   SET last_triggered_at = ?, next_run_at = ?, updated_at = ?
                   WHERE schedule_id = ?""",
                (
                    triggered_at.isoformat(),
                    next_run_at.isoformat() if next_run_at is not None else None,
                    triggered_at.isoformat(),
                    str(schedule_id),
                ),
            )

    def update_schedule_next_run(self, schedule_id: UUID, next_run_at: datetime) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "UPDATE schedules SET next_run_at = ?, updated_at = ? WHERE schedule_id = ?",
                (next_run_at.isoformat(), datetime.now(UTC).isoformat(), str(schedule_id)),
            )
