import hashlib
import json
from typing import Any
from uuid import UUID

from sector_pulse.application.tasks.schedule_service import ScheduleView
from sector_pulse.domain.task import TaskRunKey
from sector_pulse.storage.ports import RuntimeTaskRepositoryPort


class TaskRunService:
    """任务命令入口；调度器和 Web handler 不直接拼接任务存储 SQL。"""

    def __init__(self, repository: RuntimeTaskRepositoryPort) -> None:
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

    def create_scheduled(
        self,
        schedule: ScheduleView,
        *,
        trading_date: str | None,
        idempotency_key: str | None = None,
    ) -> UUID:
        input_template = dict(schedule.input_template)
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "idempotency_key": idempotency_key,
                    "input": input_template,
                    "schedule_id": str(schedule.schedule_id),
                    "trading_date": trading_date,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return self._repository.create_or_get_run(
            TaskRunKey(
                schedule_id=schedule.schedule_id,
                trading_date=trading_date,
                planned_slot=schedule.local_time,
                input_fingerprint=fingerprint,
            ),
            "live",
            input_template,
        )
