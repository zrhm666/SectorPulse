from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.exc import IntegrityError

from sector_pulse.domain.runs.task import Checkpoint, TaskRunKey, TaskRunStatus, TaskStage
from sector_pulse.storage.postgres.database import PostgresDatabase
from sector_pulse.storage.sqlite.runs.task_repository import TaskEvent


def _as_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise TypeError(f"expected datetime-compatible value, got {type(value).__name__}")


class PostgresTaskRepository:
    """Synchronous PostgreSQL task and schedule persistence."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def create_or_get_run(
        self,
        key: TaskRunKey,
        provider: str,
        input_json: dict[str, object],
        *,
        retry_of_run_id: UUID | None = None,
    ) -> UUID:
        del input_json
        run_id = uuid4()
        requested_at = datetime.now(UTC).isoformat()
        with self._database.start().begin() as connection:
            if key.schedule_id is None:
                existing = connection.execute(
                    text(
                        "SELECT run_id FROM task_runs WHERE schedule_id IS NULL "
                        "AND trading_date IS NULL AND planned_slot IS NULL "
                        "AND input_fingerprint = :fingerprint"
                    ),
                    {"fingerprint": key.input_fingerprint},
                ).first()
                if existing:
                    return UUID(existing[0])
            connection.execute(
                text(
                    """INSERT INTO task_runs
                    (run_id, schedule_id, trading_date, planned_slot, provider,
                     input_fingerprint, status, requested_at, retry_of_run_id)
                    VALUES (:run_id, :schedule_id, :trading_date, :planned_slot,
                     :provider, :fingerprint, :status, :requested_at, :retry_of_run_id)
                    ON CONFLICT DO NOTHING"""
                ),
                {
                    "run_id": str(run_id),
                    "schedule_id": str(key.schedule_id) if key.schedule_id else None,
                    "trading_date": key.trading_date,
                    "planned_slot": key.planned_slot,
                    "provider": provider,
                    "fingerprint": key.input_fingerprint,
                    "status": TaskRunStatus.QUEUED.value,
                    "requested_at": requested_at,
                    "retry_of_run_id": str(retry_of_run_id) if retry_of_run_id else None,
                },
            )
            row = connection.execute(
                text(
                    "SELECT run_id FROM task_runs "
                    "WHERE schedule_id IS NOT DISTINCT FROM :schedule_id "
                    "AND trading_date IS NOT DISTINCT FROM :trading_date "
                    "AND planned_slot IS NOT DISTINCT FROM :planned_slot "
                    "AND input_fingerprint = :fingerprint"
                ),
                {
                    "schedule_id": str(key.schedule_id) if key.schedule_id else None,
                    "trading_date": key.trading_date,
                    "planned_slot": key.planned_slot,
                    "fingerprint": key.input_fingerprint,
                },
            ).first()
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
        current = (now or datetime.now(UTC)).isoformat()
        with self._database.start().begin() as connection:
            result = connection.execute(
                text(
                    """UPDATE task_runs
                    SET status = :running, worker_id = :worker_id, lease_until = :lease_until,
                        started_at = COALESCE(started_at, :current), heartbeat_at = :current
                    WHERE run_id = :run_id AND status IN (:queued, :retry, :running)
                      AND (lease_until IS NULL OR lease_until <= :current
                           OR worker_id = :worker_id)"""
                ),
                {
                    "running": TaskRunStatus.RUNNING.value,
                    "worker_id": worker_id,
                    "lease_until": lease_until.isoformat(),
                    "current": current,
                    "run_id": str(run_id),
                    "queued": TaskRunStatus.QUEUED.value,
                    "retry": TaskRunStatus.RETRY_WAITING.value,
                },
            )
        return result.rowcount == 1

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
        with self._database.start().begin() as connection:
            result = connection.execute(
                text(
                    """UPDATE task_runs SET status = :target, error_code = :error_code,
                        finished_at = COALESCE(:finished_at, finished_at)
                    WHERE run_id = :run_id AND status = :expected"""
                ),
                {
                    "target": target.value,
                    "error_code": error_code,
                    "finished_at": now if target.is_terminal else None,
                    "run_id": str(run_id),
                    "expected": expected.value,
                },
            )
            if result.rowcount != 1:
                return False
            connection.execute(
                text(
                    """INSERT INTO task_events
                    (event_id, run_id, source, event_type, old_status, new_status,
                     idempotency_key, summary, created_at)
                    VALUES (:event_id, :run_id, :source, 'STATUS_TRANSITION', :old_status,
                     :new_status, :idempotency_key, :summary, :created_at)"""
                ),
                {
                    "event_id": str(uuid4()), "run_id": str(run_id), "source": source,
                    "old_status": expected.value, "new_status": target.value,
                    "idempotency_key": idempotency_key, "summary": summary,
                    "created_at": now,
                },
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
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        checkpoint = Checkpoint(
            checkpoint_id=uuid4(), run_id=run_id, stage=stage,
            input_fingerprint=input_fingerprint,
            implementation_version=implementation_version, payload=payload,
            payload_sha256=digest, created_at=datetime.now(UTC),
        )
        try:
            with self._database.start().begin() as connection:
                connection.execute(
                    text(
                        """INSERT INTO run_checkpoints
                        (checkpoint_id, run_id, stage, schema_version, input_fingerprint,
                         implementation_version, payload_json, payload_sha256, created_at)
                        VALUES (:checkpoint_id, :run_id, :stage, 'phase2a-v1',
                         :input_fingerprint, :implementation_version, :payload_json,
                         :payload_sha256, :created_at)"""
                    ),
                    {
                        "checkpoint_id": str(checkpoint.checkpoint_id),
                        "run_id": str(run_id), "stage": stage.value,
                        "input_fingerprint": input_fingerprint,
                        "implementation_version": implementation_version,
                        "payload_json": serialized, "payload_sha256": digest,
                        "created_at": checkpoint.created_at.isoformat(),
                    },
                )
        except IntegrityError as exc:
            raise ValueError("checkpoint already exists") from exc
        return checkpoint

    def get_latest_valid_checkpoint(
        self,
        run_id: UUID,
        stage: TaskStage,
        input_fingerprint: str,
        implementation_version: str,
    ) -> Checkpoint | None:
        with self._database.start().connect() as connection:
            row = connection.execute(
                text(
                    """SELECT checkpoint_id, run_id, stage, input_fingerprint,
                              implementation_version, payload_json, payload_sha256, created_at
                    FROM run_checkpoints
                    WHERE run_id = :run_id AND stage = :stage
                      AND input_fingerprint = :input_fingerprint
                      AND implementation_version = :implementation_version
                    ORDER BY created_at DESC LIMIT 1"""
                ),
                {
                    "run_id": str(run_id), "stage": stage.value,
                    "input_fingerprint": input_fingerprint,
                    "implementation_version": implementation_version,
                },
            ).first()
        if row is None:
            return None
        payload = json.loads(row[5])
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if hashlib.sha256(serialized.encode("utf-8")).hexdigest() != row[6]:
            return None
        return Checkpoint(
            checkpoint_id=UUID(row[0]), run_id=UUID(row[1]), stage=TaskStage(row[2]),
            input_fingerprint=row[3], implementation_version=row[4], payload=payload,
            payload_sha256=row[6], created_at=_as_datetime(row[7]),
        )

    def list_events(self, run_id: UUID) -> list[TaskEvent]:
        with self._database.start().connect() as connection:
            rows = connection.execute(
                text(
                    """SELECT event_id, run_id, source, event_type, old_status,
                              new_status, idempotency_key, summary, created_at
                    FROM task_events WHERE run_id = :run_id ORDER BY created_at, event_id"""
                ),
                {"run_id": str(run_id)},
            ).fetchall()
        return [
            TaskEvent(
                event_id=UUID(row[0]), run_id=UUID(row[1]), source=row[2],
                event_type=row[3], old_status=TaskRunStatus(row[4]) if row[4] else None,
                new_status=TaskRunStatus(row[5]) if row[5] else None,
                idempotency_key=row[6], summary=row[7], created_at=_as_datetime(row[8]),
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
        with self._database.start().begin() as connection:
            connection.execute(
                text(
                    """INSERT INTO task_events
                    (event_id, run_id, source, event_type, idempotency_key, summary, created_at)
                    VALUES (:event_id, :run_id, :source, :event_type, :idempotency_key,
                     :summary, :created_at)"""
                ),
                {
                    "event_id": str(uuid4()), "run_id": str(run_id), "source": source,
                    "event_type": event_type, "idempotency_key": idempotency_key,
                    "summary": summary, "created_at": created_at.isoformat(),
                },
            )

    def count_runs(self) -> int:
        with self._database.start().connect() as connection:
            return int(connection.execute(text("SELECT COUNT(*) FROM task_runs")).scalar_one())

    def get_task_detail(self, run_id: UUID) -> dict[str, object] | None:
        with self._database.start().connect() as connection:
            row = connection.execute(
                text(
                    """SELECT run_id, status, provider, input_fingerprint, requested_at,
                              started_at, finished_at, error_code, downgrade_reasons_json,
                              retry_of_run_id, cancel_requested_at, interrupted_reason,
                              heartbeat_at, data_run_id
                    FROM task_runs WHERE run_id = :run_id"""
                ),
                {"run_id": str(run_id)},
            ).first()
            if row is None:
                return None
            attempts = connection.execute(
                text(
                    """SELECT stage, attempt_no, status, input_fingerprint, provider,
                              error_code, started_at, finished_at
                    FROM run_stage_attempts WHERE run_id = :run_id
                    ORDER BY started_at, stage, attempt_no"""
                ),
                {"run_id": str(run_id)},
            ).fetchall()
        return {
            "run_id": row[0], "status": row[1], "provider": row[2],
            "input_fingerprint": row[3], "requested_at": row[4],
            "started_at": row[5], "finished_at": row[6], "error_code": row[7],
            "downgrade_reasons": json.loads(row[8] or "[]"),
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
        with self._database.start().begin() as connection:
            result = connection.execute(
                text(
                    """UPDATE task_runs SET status = :retry, worker_id = NULL, lease_until = NULL
                    WHERE status = :running AND lease_until IS NOT NULL AND lease_until <= :now"""
                ),
                {
                    "retry": TaskRunStatus.RETRY_WAITING.value,
                    "running": TaskRunStatus.RUNNING.value,
                    "now": current,
                },
            )
        return result.rowcount

    def request_cancel(self, run_id: UUID, requested_at: datetime) -> bool:
        statement = text(
            """UPDATE task_runs SET cancel_requested_at = :requested_at
            WHERE run_id = :run_id AND status NOT IN :terminal"""
        ).bindparams(bindparam("terminal", expanding=True))
        with self._database.start().begin() as connection:
            result = connection.execute(
                statement,
                {
                    "requested_at": requested_at.isoformat(),
                    "run_id": str(run_id),
                    "terminal": [status.value for status in TaskRunStatus if status.is_terminal],
                },
            )
            if result.rowcount != 1:
                return False
            connection.execute(
                text(
                    """INSERT INTO task_events
                    (event_id, run_id, source, event_type, summary, created_at)
                    VALUES (:event_id, :run_id, 'api', 'CANCEL_REQUESTED',
                     'cancel requested', :created_at)"""
                ),
                {
                    "event_id": str(uuid4()), "run_id": str(run_id),
                    "created_at": requested_at.isoformat(),
                },
            )
        return True

    def recover_interrupted(self, now: datetime, reason: str) -> int:
        timestamp = now.isoformat()
        with self._database.start().begin() as connection:
            run_ids = [
                row[0]
                for row in connection.execute(
                    text("SELECT run_id FROM task_runs WHERE status = :running FOR UPDATE"),
                    {"running": TaskRunStatus.RUNNING.value},
                ).fetchall()
            ]
            if not run_ids:
                return 0
            connection.execute(
                text(
                    """UPDATE task_runs
                    SET status = :interrupted, worker_id = NULL, lease_until = NULL,
                        heartbeat_at = :timestamp, interrupted_reason = :reason,
                        finished_at = :timestamp
                    WHERE status = :running"""
                ),
                {
                    "interrupted": TaskRunStatus.INTERRUPTED.value,
                    "timestamp": timestamp, "reason": reason,
                    "running": TaskRunStatus.RUNNING.value,
                },
            )
            connection.execute(
                text(
                    """INSERT INTO task_events
                    (event_id, run_id, source, event_type, old_status, new_status,
                     summary, created_at)
                    VALUES (:event_id, :run_id, 'startup-recovery', 'STATUS_TRANSITION',
                     :old_status, :new_status, :summary, :created_at)"""
                ),
                [
                    {
                        "event_id": str(uuid4()), "run_id": run_id,
                        "old_status": TaskRunStatus.RUNNING.value,
                        "new_status": TaskRunStatus.INTERRUPTED.value,
                        "summary": reason, "created_at": timestamp,
                    }
                    for run_id in run_ids
                ],
            )
        return len(run_ids)

    def link_data_run(self, run_id: UUID, data_run_id: UUID) -> None:
        with self._database.start().begin() as connection:
            connection.execute(
                text("UPDATE task_runs SET data_run_id = :data_run_id WHERE run_id = :run_id"),
                {"data_run_id": str(data_run_id), "run_id": str(run_id)},
            )

    def list_linked_runs(self) -> list[tuple[UUID, UUID]]:
        with self._database.start().connect() as connection:
            rows = connection.execute(
                text("SELECT run_id, data_run_id FROM task_runs WHERE data_run_id IS NOT NULL")
            ).fetchall()
        return [(UUID(row[0]), UUID(row[1])) for row in rows]

    def claim_ready_linked_run(self, run_id: UUID, data_run_id: UUID) -> bool:
        now = datetime.now(UTC).isoformat()
        with self._database.start().begin() as connection:
            result = connection.execute(
                text(
                    """UPDATE task_runs
                    SET status = :running, started_at = COALESCE(started_at, :now),
                        heartbeat_at = :now
                    WHERE run_id = :run_id AND data_run_id = :data_run_id
                      AND status = :queued"""
                ),
                {
                    "running": TaskRunStatus.RUNNING.value, "now": now,
                    "run_id": str(run_id), "data_run_id": str(data_run_id),
                    "queued": TaskRunStatus.QUEUED.value,
                },
            )
            if result.rowcount != 1:
                return False
            connection.execute(
                text(
                    """INSERT INTO task_events
                    (event_id, run_id, source, event_type, old_status, new_status,
                     summary, created_at)
                    VALUES (:event_id, :run_id, 'scheduled-data-bridge', 'STATUS_TRANSITION',
                     :queued, :running, 'ready data run claimed', :created_at)"""
                ),
                {
                    "event_id": str(uuid4()), "run_id": str(run_id),
                    "queued": TaskRunStatus.QUEUED.value,
                    "running": TaskRunStatus.RUNNING.value, "created_at": now,
                },
            )
        return True

    def fail_claimed_run(self, run_id: UUID, error_code: str) -> bool:
        return self.transition(
            run_id, TaskRunStatus.RUNNING, TaskRunStatus.FAILED,
            source="scheduled-data-bridge", summary="content generation start failed",
            error_code=error_code,
        )

    def mark_content_started(self, run_id: UUID, created_at: datetime) -> None:
        self.record_task_event(
            run_id, source="scheduled-data-bridge",
            event_type="CONTENT_GENERATION_STARTED",
            summary="content generation started", idempotency_key=None,
            created_at=created_at,
        )

    def insert_schedule(self, values: Mapping[str, object]) -> None:
        enabled = values["enabled"]
        if not isinstance(enabled, bool):
            raise TypeError("schedule enabled must be boolean")
        version = values.get("version", 1)
        if not isinstance(version, int) or isinstance(version, bool):
            raise TypeError("schedule version must be an integer")
        with self._database.start().begin() as connection:
            connection.execute(
                text(
                    """INSERT INTO schedules
                    (schedule_id, name, mode, timezone, local_time, trading_days,
                     schedule_spec_json, input_template_json, enabled, version,
                     next_run_at, created_at, updated_at)
                    VALUES (:schedule_id, :name, :mode, :timezone, :local_time,
                     :trading_days, :schedule_spec, :input_template, :enabled, :version,
                     :next_run_at, :created_at, :updated_at)"""
                ),
                {
                    "schedule_id": values["schedule_id"], "name": values["name"],
                    "mode": values["mode"], "timezone": values["timezone"],
                    "local_time": values["local_time"],
                    "trading_days": values["trading_days"],
                    "schedule_spec": json.dumps(values.get("schedule_spec", {}), sort_keys=True),
                    "input_template": json.dumps(
                        values.get("input_template", {}), ensure_ascii=False, sort_keys=True
                    ),
                    "enabled": int(enabled), "version": version,
                    "next_run_at": values.get("next_run_at"),
                    "created_at": values["created_at"], "updated_at": values["updated_at"],
                },
            )

    def list_schedules(self) -> list[dict[str, object]]:
        with self._database.start().connect() as connection:
            rows = connection.execute(
                text(
                    """SELECT schedule_id, name, mode, timezone, local_time, trading_days,
                              schedule_spec_json, input_template_json, enabled, version,
                              next_run_at, last_triggered_at, created_at, updated_at
                    FROM schedules ORDER BY created_at, schedule_id"""
                )
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
        with self._database.start().connect() as connection:
            rows = connection.execute(
                text(
                    """SELECT schedule_id FROM schedules
                    WHERE enabled = 1 AND next_run_at IS NOT NULL
                      AND CAST(next_run_at AS TIMESTAMPTZ) <= :now
                    ORDER BY CAST(next_run_at AS TIMESTAMPTZ), schedule_id"""
                ),
                {"now": now},
            ).fetchall()
        due_ids = {row[0] for row in rows}
        return [item for item in self.list_schedules() if item["schedule_id"] in due_ids]

    def record_schedule_trigger(
        self,
        schedule_id: UUID,
        triggered_at: datetime,
        next_run_at: datetime | None,
    ) -> None:
        with self._database.start().begin() as connection:
            connection.execute(
                text(
                    """UPDATE schedules
                    SET last_triggered_at = :triggered_at, next_run_at = :next_run_at,
                        updated_at = :triggered_at WHERE schedule_id = :schedule_id"""
                ),
                {
                    "triggered_at": triggered_at.isoformat(),
                    "next_run_at": next_run_at.isoformat() if next_run_at else None,
                    "schedule_id": str(schedule_id),
                },
            )

    def update_schedule_next_run(self, schedule_id: UUID, next_run_at: datetime) -> None:
        with self._database.start().begin() as connection:
            connection.execute(
                text(
                    """UPDATE schedules SET next_run_at = :next_run_at,
                        updated_at = :updated_at WHERE schedule_id = :schedule_id"""
                ),
                {
                    "next_run_at": next_run_at.isoformat(),
                    "updated_at": datetime.now(UTC).isoformat(),
                    "schedule_id": str(schedule_id),
                },
            )
