import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from sector_pulse.application.tasks.schedule_service import ScheduleService, ScheduleView
from sector_pulse.domain.task import TaskRunKey, TaskRunStatus
from sector_pulse.storage.ports import RuntimeTaskRepositoryPort

logger = logging.getLogger(__name__)


class Executor(Protocol):
    async def execute(self, run_id: UUID, provider: str, worker_id: str) -> None: ...


class ScheduledRunBridge(Protocol):
    def start(self, task_run_id: UUID, schedule: ScheduleView) -> UUID: ...

    def advance(self) -> int: ...

    def reconcile_finished(self) -> int: ...


class ScheduledRunCoordinator(Protocol):
    def start_scheduled(self, schedule: ScheduleView, now: datetime) -> UUID: ...


class EmbeddedScheduler:
    """单进程调度循环；到期计算与任务幂等创建均落在数据库边界内。"""

    def __init__(
        self,
        repository: RuntimeTaskRepositoryPort,
        schedules: ScheduleService,
        executor: Executor | None,
        *,
        poll_seconds: int = 10,
        bridge: ScheduledRunBridge | None = None,
        coordinator: ScheduledRunCoordinator | None = None,
        dispatch_enabled: bool = True,
    ) -> None:
        self._repository = repository
        self._schedules = schedules
        self._executor = executor
        self._poll_seconds = poll_seconds
        self._bridge = bridge
        self._coordinator = coordinator
        self._dispatch_enabled = dispatch_enabled
        self._task: asyncio.Task[None] | None = None
        self._healthy = False

    async def poll_once(self, now: datetime | None = None) -> None:
        current = now or datetime.now(UTC)
        for stored in self._repository.list_due_schedules(current):
            schedule = self._schedules.from_stored(stored)
            due = schedule.next_run_at
            if due is None:
                continue
            trading_date = due.astimezone(ZoneInfo(schedule.timezone)).date().isoformat()
            run_id: UUID | None = None
            try:
                if self._coordinator is not None:
                    self._coordinator.start_scheduled(schedule, current)
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
            except Exception:
                self._repository.record_schedule_trigger(
                    schedule.schedule_id,
                    current,
                    self._schedules.next_after(schedule, current),
                )
                continue
            self._repository.record_schedule_trigger(
                schedule.schedule_id, current, self._schedules.next_after(schedule, current)
            )
            if run_id is None:
                continue
            try:
                if self._bridge is not None:
                    self._bridge.start(run_id, schedule)
                else:
                    if self._executor is None:
                        raise RuntimeError("scheduled executor is not configured")
                    await self._executor.execute(run_id, "live", "embedded-scheduler")
            except Exception:
                self._repository.transition(
                    run_id,
                    TaskRunStatus.QUEUED,
                    TaskRunStatus.FAILED,
                    source="scheduler",
                    summary="scheduled execution failed",
                    error_code="SCHEDULE_EXECUTION_FAILED",
                )

    def recover(self, now: datetime | None = None) -> int:
        return self._repository.recover_expired_leases(now)

    def advance_bridged_runs(self) -> int:
        if self._bridge is None:
            return 0
        return self._bridge.advance()

    def reconcile_finished(self) -> int:
        return self._bridge.reconcile_finished() if self._bridge is not None else 0

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._healthy = False
            self._task = asyncio.create_task(self._loop())

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def is_healthy(self) -> bool:
        return self.is_running and self._healthy

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("scheduler stopped after failure: error_type=%s", type(exc).__name__)
        finally:
            self._task = None
            self._healthy = False

    async def _loop(self) -> None:
        while True:
            healthy = True
            if self._dispatch_enabled:
                try:
                    await self.poll_once()
                except Exception as exc:
                    healthy = False
                    logger.warning(
                        "scheduler cycle failed: stage=dispatch error_type=%s", type(exc).__name__
                    )
            try:
                self.advance_bridged_runs()
            except Exception as exc:
                healthy = False
                logger.warning(
                    "scheduler cycle failed: stage=maintenance error_type=%s", type(exc).__name__
                )
            self._healthy = healthy
            await asyncio.sleep(self._poll_seconds)
