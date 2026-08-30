from typing import Protocol
from uuid import UUID

from sector_pulse.application.schedule_service import ScheduleView
from sector_pulse.domain.real_data_run import RealDataRunRequest, RealDataRunStatus
from sector_pulse.storage.real_data_run_repository import SQLiteRealDataRunRepository
from sector_pulse.storage.task_repository import SQLiteTaskRepository


class DataRunStarter(Protocol):
    def create(self, request: RealDataRunRequest, provider: str) -> UUID: ...


class WritingStarter(Protocol):
    def generate(
        self, run_id: UUID, sector_ids: tuple[str, ...] | None = None
    ) -> UUID: ...


class SelectionResult(Protocol):
    selected_sector_ids: tuple[str, ...]


class DefaultSelectionService(Protocol):
    def confirm_default(self, run_id: UUID) -> SelectionResult: ...


class ScheduledDataRunBridge:
    """把调度任务映射到真实数据运行，并在可归因后启动 Phase 1D-2。"""

    def __init__(
        self,
        task_repository: SQLiteTaskRepository,
        real_repository: SQLiteRealDataRunRepository,
        data_run_service: DataRunStarter,
        writing_service: WritingStarter,
        selection_service: DefaultSelectionService | None = None,
    ) -> None:
        self._tasks = task_repository
        self._real_runs = real_repository
        self._data_runs = data_run_service
        self._writing = writing_service
        self._selections = selection_service

    def start(self, task_run_id: UUID, schedule: ScheduleView) -> UUID:
        values = schedule.input_template
        request = RealDataRunRequest.model_validate(
            {
                "mode": (
                    schedule.mode
                    if schedule.mode in {"intraday", "post_close"}
                    else "intraday"
                ),
                "lookback_hours": values.get("lookback_hours"),
                "precandidate_limit": values.get("precandidate_limit", 30),
                "final_candidate_limit": values.get("final_candidate_limit", 12),
            }
        )
        return self._data_runs.create(request, "live")

    def advance(self) -> int:
        started = 0
        for _task_run_id, data_run_id in self._tasks.list_linked_runs():
            data_run = self._real_runs.get_run(data_run_id)
            if data_run is None or data_run.status is not RealDataRunStatus.READY_FOR_ATTRIBUTION:
                continue
            if self._selections is None:
                self._writing.generate(data_run_id)
            else:
                selection = self._selections.confirm_default(data_run_id)
                self._writing.generate(data_run_id, selection.selected_sector_ids)
            started += 1
        return started
