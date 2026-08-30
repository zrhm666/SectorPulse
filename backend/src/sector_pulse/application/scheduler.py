import asyncio
import hashlib
import json
from contextlib import suppress
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from sector_pulse.application.schedule_service import ScheduleService, ScheduleView
from sector_pulse.domain.task import TaskRunKey
from sector_pulse.storage.ports import RuntimeTaskRepositoryPort


class Executor(Protocol):
    async def execute(self, run_id: UUID, provider: str, worker_id: str) -> None: ...


class ScheduledRunBridge(Protocol):
    def start(self, task_run_id: UUID, schedule: ScheduleView) -> UUID: ...

    def advance(self) -> int: ...


class ScheduledRunCoordinator(Protocol):
    def start_scheduled(self, schedule: ScheduleView, now: datetime) -> UUID: ...


class EmbeddedScheduler:
    """单进程调度循环；到期计算与任务幂等创建均落在数据库边界内。"""

    def __init__(
        self,
        repository: RuntimeTaskRepositoryPort,
        schedules: ScheduleService,
        executor: Executor,
        *,
        poll_seconds: int = 10,
        bridge: ScheduledRunBridge | None = None,
        coordinator: ScheduledRunCoordinator | None = None,
    ) -> None:
        self._repository = repository
        self._schedules = schedules
        self._executor = executor
        self._poll_seconds = poll_seconds
        self._bridge = bridge
        self._coordinator = coordinator
        self._task: asyncio.Task[None] | None = None

    async def poll_once(self, now: datetime | None = None) -> None:
        current = now or datetime.now(UTC)
        for stored in self._repository.list_due_schedules(current):
            schedule = self._schedules.from_stored(stored)
            due = schedule.next_run_at
            if due is None:
                continue
            trading_date = due.astimezone(ZoneInfo(schedule.timezone)).date().isoformat()
            if self._coordinator is not None:
                self._coordinator.start_scheduled(schedule, current)
                run_id = None
            else:
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
            self._repository.record_schedule_trigger(
                schedule.schedule_id,
                current,
                self._schedules.next_after(schedule, current),
            )
            if run_id is None:
                continue
            if self._bridge is not None:
                self._bridge.start(run_id, schedule)
            else:
                await self._executor.execute(run_id, "live", "embedded-scheduler")

    def recover(self, now: datetime | None = None) -> int:
        return self._repository.recover_expired_leases(now)

    def advance_bridged_runs(self) -> int:
        if self._bridge is None:
            return 0
        return self._bridge.advance()

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
            self.advance_bridged_runs()
            await asyncio.sleep(self._poll_seconds)
