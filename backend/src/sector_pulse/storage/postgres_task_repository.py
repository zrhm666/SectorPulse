import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from sector_pulse.domain.task import TaskRunKey, TaskRunStatus
from sector_pulse.storage.postgres import PostgresDatabase


class PostgresTaskRepository:
    """Async PostgreSQL task/schedule persistence for Phase 2A."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    async def create_or_get_run(
        self, key: TaskRunKey, provider: str, input_json: dict[str, object]
    ) -> UUID:
        del input_json
        run_id = uuid4()
        requested_at = datetime.now(UTC).isoformat()
        async with self._database.engine.begin() as connection:
            if key.schedule_id is None:
                result = await connection.execute(
                    text(
                        "SELECT run_id FROM task_runs WHERE schedule_id IS NULL "
                        "AND trading_date IS NULL AND planned_slot IS NULL "
                        "AND input_fingerprint = :fingerprint"
                    ),
                    {"fingerprint": key.input_fingerprint},
                )
                existing = result.first()
                if existing:
                    return UUID(existing[0])
            await connection.execute(
                text(
                    """INSERT INTO task_runs
                    (run_id, schedule_id, trading_date, planned_slot, provider,
                     input_fingerprint, status, requested_at)
                    VALUES (:run_id, :schedule_id, :trading_date, :planned_slot,
                     :provider, :fingerprint, :status, :requested_at)
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
                },
            )
            result = await connection.execute(
                text(
                    "SELECT run_id FROM task_runs WHERE schedule_id IS NOT DISTINCT "
                    "FROM :schedule_id "
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
            )
            row = result.first()
        if row is None:
            raise RuntimeError("task run insert did not return a run")
        return UUID(row[0])

    async def count_runs(self) -> int:
        async with self._database.engine.connect() as connection:
            result = await connection.execute(text("SELECT COUNT(*) FROM task_runs"))
            return int(result.scalar_one())

    async def get_task_detail(self, run_id: UUID) -> dict[str, Any] | None:
        async with self._database.engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT run_id, status, provider, input_fingerprint, requested_at, "
                    "started_at, finished_at, error_code, downgrade_reasons_json "
                    "FROM task_runs WHERE run_id = :run_id"
                ),
                {"run_id": str(run_id)},
            )
            row = result.mappings().first()
            if row is None:
                return None
            stages = await connection.execute(
                text(
                    "SELECT stage, attempt_no, status, input_fingerprint, provider, "
                    "error_code, started_at, finished_at FROM run_stage_attempts "
                    "WHERE run_id = :run_id ORDER BY started_at, stage, attempt_no"
                ),
                {"run_id": str(run_id)},
            )
            events = await connection.execute(
                text(
                    "SELECT event_id, run_id, source, event_type, old_status, new_status, "
                    "idempotency_key, summary, created_at FROM task_events "
                    "WHERE run_id = :run_id ORDER BY created_at, event_id"
                ),
                {"run_id": str(run_id)},
            )
        return {
            "run_id": row["run_id"], "status": row["status"], "provider": row["provider"],
            "input_fingerprint": row["input_fingerprint"], "requested_at": row["requested_at"],
            "started_at": row["started_at"], "finished_at": row["finished_at"],
            "error_code": row["error_code"],
            "downgrade_reasons": json.loads(row["downgrade_reasons_json"] or "[]"),
            "stages": [dict(item) for item in stages.mappings().all()],
            "events": [dict(item) for item in events.mappings().all()],
        }

    async def list_schedules(self) -> list[dict[str, Any]]:
        async with self._database.engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT schedule_id, name, mode, timezone, local_time, trading_days, "
                    "schedule_spec_json, input_template_json, enabled, version, next_run_at, "
                    "created_at, updated_at FROM schedules ORDER BY created_at, schedule_id"
                )
            )
            rows = result.mappings().all()
        return [
            {
                "schedule_id": row["schedule_id"], "name": row["name"], "mode": row["mode"],
                "timezone": row["timezone"], "local_time": row["local_time"],
                "trading_days": row["trading_days"],
                "schedule_spec": json.loads(row["schedule_spec_json"]),
                "input_template": json.loads(row["input_template_json"]),
                "enabled": bool(row["enabled"]), "version": row["version"],
                "next_run_at": row["next_run_at"], "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
