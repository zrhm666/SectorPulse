import hashlib
import json
from typing import Any
from uuid import UUID

from sector_pulse.domain.task import TaskRunKey
from sector_pulse.storage.task_repository import SQLiteTaskRepository


class TaskRunService:
    """任务命令入口；调度器和 Web handler 不直接拼接任务存储 SQL。"""

    def __init__(self, repository: SQLiteTaskRepository) -> None:
        self._repository = repository

    def create_manual(
        self,
        input_json: dict[str, Any],
        provider: str,
        idempotency_key: str | None = None,
    ) -> UUID:
        fingerprint_payload = {
            "idempotency_key": idempotency_key,
            "input": input_json,
            "provider": provider,
        }
        serialized = json.dumps(
            fingerprint_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        fingerprint = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return self._repository.create_or_get_run(
            TaskRunKey(input_fingerprint=fingerprint), provider, input_json
        )

    def trigger_schedule(
        self, schedule_id: UUID, idempotency_key: str | None = None
    ) -> UUID:
        schedule = self._repository.get_schedule(schedule_id)
        if schedule is None:
            raise ValueError("schedule not found")
        request = {
            "schedule_id": str(schedule_id),
            "idempotency_key": idempotency_key,
            "input_template": schedule["input_template"],
        }
        fingerprint = hashlib.sha256(
            json.dumps(request, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return self._repository.create_or_get_run(
            TaskRunKey(input_fingerprint=fingerprint), "live", schedule["input_template"]
        )
