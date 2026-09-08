from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID

from sector_pulse.application.tasks.schedule_service import ScheduleView
from sector_pulse.domain.real_data_run import RealDataRunRequest, RealDataRunStatus
from sector_pulse.domain.task import TaskRunStatus
from sector_pulse.storage.ports import (
    Phase1BRunsRepositoryPort,
    RealDataRunRepositoryPort,
    RuntimeTaskRepositoryPort,
)


class DataRunStarter(Protocol):
    def create(
        self, request: RealDataRunRequest, provider: Literal["fixture", "live"]
    ) -> UUID: ...


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
        task_repository: RuntimeTaskRepositoryPort,
        real_repository: RealDataRunRepositoryPort,
        data_run_service: DataRunStarter,
        writing_service: WritingStarter,
        selection_service: DefaultSelectionService | None = None,
        *,
        content_runs: Phase1BRunsRepositoryPort | None = None,
    ) -> None:
        self._tasks = task_repository
        self._real_runs = real_repository
        self._data_runs = data_run_service
        self._writing = writing_service
        self._selections = selection_service
        self._content_runs = content_runs

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
        self.reconcile_finished()
        started = 0
        for task_run_id, data_run_id in self._tasks.list_linked_runs():
            data_run = self._real_runs.get_run(data_run_id)
            if data_run is None or data_run.status is not RealDataRunStatus.READY_FOR_ATTRIBUTION:
                continue
            if not self._tasks.claim_ready_linked_run(task_run_id, data_run_id):
                continue
            try:
                if self._selections is None:
                    self._writing.generate(data_run_id)
                else:
                    selection = self._selections.confirm_default(data_run_id)
                    self._writing.generate(data_run_id, selection.selected_sector_ids)
            except Exception:
                self._tasks.fail_claimed_run(task_run_id, "CONTENT_GENERATION_FAILED")
                continue
            self._tasks.mark_content_started(task_run_id, datetime.now(UTC))
            started += 1
        return started

    def reconcile_finished(self) -> int:
        """Copy persisted outcomes into linked tasks without starting new work."""
        reconciled = 0
        for task_run_id, data_run_id in self._tasks.list_linked_runs():
            detail = self._tasks.get_task_detail(task_run_id)
            if detail is None:
                continue
            current = TaskRunStatus(str(detail["status"]))
            if current.is_terminal:
                continue
            data_run = self._real_runs.get_run(data_run_id)
            if data_run is None:
                continue
            target = {
                RealDataRunStatus.FAILED: TaskRunStatus.FAILED,
                RealDataRunStatus.BLOCKED: TaskRunStatus.FAILED,
                RealDataRunStatus.DEGRADED: TaskRunStatus.DEGRADED,
                RealDataRunStatus.CANCELLED: TaskRunStatus.CANCELLED,
                RealDataRunStatus.INTERRUPTED: TaskRunStatus.INTERRUPTED,
            }.get(data_run.status)
            if target is None and self._content_runs is not None:
                content = self._content_runs.get_run(data_run_id)
                if content is not None:
                    target = {
                        "READY_FOR_HUMAN_REVIEW": TaskRunStatus.READY_FOR_HUMAN_REVIEW,
                        "UNREVIEWED": TaskRunStatus.DEGRADED,
                        "REVISE_REQUIRED": TaskRunStatus.DEGRADED,
                        "FAILED": TaskRunStatus.FAILED,
                        "ATTRIBUTION_BLOCKED": TaskRunStatus.FAILED,
                        "BUDGET_EXCEEDED": TaskRunStatus.FAILED,
                        "DRAFT_GENERATION_FAILED": TaskRunStatus.FAILED,
                        "CANCELLED": TaskRunStatus.CANCELLED,
                        "INTERRUPTED": TaskRunStatus.INTERRUPTED,
                    }.get(content.status)
            if target is not None:
                reconciled += self._tasks.transition(
                    task_run_id, current, target,
                    source="scheduled-data-bridge",
                    summary="linked workflow reached a terminal outcome",
                    error_code="LINKED_WORKFLOW_FAILED" if target is TaskRunStatus.FAILED else None,
                )
        return reconciled
