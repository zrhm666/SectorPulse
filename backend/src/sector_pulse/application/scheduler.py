import asyncio
import hashlib
import json
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sector_pulse.application.schedule_service import ScheduleService
from sector_pulse.domain.task import TaskRunKey
from sector_pulse.storage.task_repository import SQLiteTaskRepository


class Executor(Protocol):
    async def execute(self, run_id, provider: str, worker_id: str) -> None: ...


class EmbeddedScheduler:
    """单进程调度循环；到期计算与任务幂等创建均落在数据库边界内。"""

    def __init__(
        self,
        repository: SQLiteTaskRepository,
        schedules: ScheduleService,
        executor: Executor,
        *,
        poll_seconds: int = 10,
    ) -> None:
        self._repository = repository
        self._schedules = schedules
        self._executor = executor
        self._poll_seconds = poll_seconds
        self._task: asyncio.Task[None] | None = None

    async def poll_once(self, now: datetime | None = None) -> None:
        current = now or datetime.now(UTC)
        for schedule in self._schedules.list():
            due = self._schedules.next_due(schedule, current)
            if due is None or due > current:
                continue
            trading_date = due.date().isoformat()
            fingerprint = hashlib.sha256(
                json.dumps(
                    schedule.input_template, ensure_ascii=False, sort_keys=True
                ).encode("utf-8")
            ).hexdigest()
            run_id = self._repository.create_or_get_run(
                TaskRunKey(
                    schedule_id=schedule.schedule_id,
                    trading_date=trading_date,
                    planned_slot=schedule.local_time,
                    input_fingerprint=fingerprint,
                ),
                "live",
                schedule.input_template,
            )
            self._repository.update_schedule_next_run(
                schedule.schedule_id, due + timedelta(days=1)
            )
            await self._executor.execute(run_id, "live", "embedded-scheduler")

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _loop(self) -> None:
        while True:
            await self.poll_once()
            await asyncio.sleep(self._poll_seconds)
