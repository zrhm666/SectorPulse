from uuid import UUID

from sector_pulse.application.schedule_service import ScheduleView
from sector_pulse.domain.real_data_run import RealDataRunRequest, RealDataRunStatus
from sector_pulse.storage.real_data_run_repository import SQLiteRealDataRunRepository
from sector_pulse.storage.task_repository import SQLiteTaskRepository


class ScheduledDataRunBridge:
    """把调度任务映射到真实数据运行，并在可归因后启动 Phase 1D-2。"""

    def __init__(
        self,
        task_repository: SQLiteTaskRepository,
        real_repository: SQLiteRealDataRunRepository,
        data_run_service: object,
        writing_service: object,
    ) -> None:
        self._tasks = task_repository
        self._real_runs = real_repository
        self._data_runs = data_run_service
        self._writing = writing_service

    def start(self, task_run_id: UUID, schedule: ScheduleView) -> UUID:
        values = schedule.input_template
        request = RealDataRunRequest(
            mode=schedule.mode if schedule.mode in {"intraday", "post_close"} else "intraday",
            lookback_hours=values.get("lookback_hours"),
            precandidate_limit=values.get("precandidate_limit", 30),
            final_candidate_limit=values.get("final_candidate_limit", 12),
        )
        data_run_id = self._data_runs.create(request, "live")
        self._tasks.link_data_run(task_run_id, data_run_id)
        return data_run_id

    def advance(self) -> int:
        started = 0
        for _task_run_id, data_run_id in self._tasks.list_linked_runs():
            data_run = self._real_runs.get_run(data_run_id)
            if data_run is None or data_run.status is not RealDataRunStatus.READY_FOR_ATTRIBUTION:
                continue
            self._writing.generate(data_run_id)
            started += 1
        return started
