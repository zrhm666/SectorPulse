from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from sector_pulse.application.tasks.schedule_service import ScheduleService, ScheduleView
from sector_pulse.application.tasks.task_run_service import TaskRunService
from sector_pulse.domain.task import TaskRunStatus
from sector_pulse.storage.ports import RealDataRunRepositoryPort, RuntimeTaskRepositoryPort


class ScheduleDataRunBridge(Protocol):
    def start(self, task_run_id: UUID, schedule: ScheduleView) -> UUID: ...


class RunCoordinator:
    """Creates one linked task/data run for both manual and scheduled commands."""

    def __init__(
        self,
        repository: RuntimeTaskRepositoryPort,
        task_runs: TaskRunService,
        schedules: ScheduleService,
        bridge: ScheduleDataRunBridge,
        real_runs: RealDataRunRepositoryPort,
    ) -> None:
        self._repository = repository
        self._task_runs = task_runs
        self._schedules = schedules
        self._bridge = bridge
        self._real_runs = real_runs

    def recover_startup(self, now: datetime) -> int:
        real_runs = self._real_runs.mark_interrupted()
        task_runs = self._repository.recover_interrupted(
            now, "process restarted before run completion"
        )
        return real_runs + task_runs

    def start_schedule_now(
        self, schedule_id: UUID, idempotency_key: str | None = None
    ) -> UUID:
        stored = self._repository.get_schedule(schedule_id)
        if stored is None:
            raise ValueError("schedule not found")
        return self._start_schedule(
            self._schedules.from_stored(stored),
            datetime.now(UTC),
            idempotency_key=idempotency_key,
            event_type="MANUAL_TRIGGER_ACCEPTED",
        )

    def start_scheduled(self, schedule: ScheduleView, now: datetime) -> UUID:
        return self._start_schedule(
            schedule,
            now,
            idempotency_key=None,
            event_type="SCHEDULE_TRIGGER_ACCEPTED",
        )

    def _start_schedule(
        self,
        schedule: ScheduleView,
        now: datetime,
        *,
        idempotency_key: str | None,
        event_type: str,
    ) -> UUID:
        slot = schedule.next_run_at or now
        trading_date = slot.astimezone(ZoneInfo(schedule.timezone)).date().isoformat()
        task_run_id = self._task_runs.create_scheduled(
            schedule,
            trading_date=trading_date,
            idempotency_key=idempotency_key,
        )
        detail = self._repository.get_task_detail(task_run_id)
        if detail is not None and detail.get("data_run_id") is not None:
            return task_run_id
        try:
            data_run_id = self._bridge.start(task_run_id, schedule)
            self._repository.link_data_run(task_run_id, data_run_id)
        except Exception:
            self._repository.transition(
                task_run_id,
                TaskRunStatus.QUEUED,
                TaskRunStatus.FAILED,
                source="run-coordinator",
                summary="data run start failed",
                error_code="DATA_RUN_START_FAILED",
            )
            raise
        self._repository.record_task_event(
            task_run_id,
            source="run-coordinator",
            event_type=event_type,
            summary="schedule trigger accepted",
            idempotency_key=idempotency_key,
            created_at=now,
        )
        return task_run_id
