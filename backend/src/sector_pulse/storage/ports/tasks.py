from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from sector_pulse.domain.runs.task import Checkpoint, TaskRunKey, TaskRunStatus, TaskStage
from sector_pulse.storage.sqlite.runs.task_repository import TaskEvent


@runtime_checkable
class TaskRepositoryPort(Protocol):
    def create_or_get_run(
        self,
        key: TaskRunKey,
        provider: str,
        input_json: dict[str, object],
        *,
        retry_of_run_id: UUID | None = None,
    ) -> UUID: ...

    def claim_run(
        self,
        run_id: UUID,
        worker_id: str,
        lease_until: datetime,
        *,
        now: datetime | None = None,
    ) -> bool: ...

    def transition(
        self,
        run_id: UUID,
        expected: TaskRunStatus,
        target: TaskRunStatus,
        *,
        source: str,
        summary: str,
        idempotency_key: str | None = None,
        error_code: str | None = None,
    ) -> bool: ...

    def save_checkpoint(
        self,
        run_id: UUID,
        stage: TaskStage,
        input_fingerprint: str,
        implementation_version: str,
        payload: dict[str, object],
    ) -> Checkpoint: ...

    def get_latest_valid_checkpoint(
        self,
        run_id: UUID,
        stage: TaskStage,
        input_fingerprint: str,
        implementation_version: str,
    ) -> Checkpoint | None: ...

    def list_events(self, run_id: UUID) -> list[TaskEvent]: ...

    def record_task_event(
        self,
        run_id: UUID,
        *,
        source: str,
        event_type: str,
        summary: str,
        idempotency_key: str | None,
        created_at: datetime,
    ) -> None: ...

    def count_runs(self) -> int: ...

    def get_task_detail(self, run_id: UUID) -> dict[str, object] | None: ...

    def recover_expired_leases(self, now: datetime | None = None) -> int: ...

    def request_cancel(self, run_id: UUID, requested_at: datetime) -> bool: ...

    def recover_interrupted(self, now: datetime, reason: str) -> int: ...

    def link_data_run(self, run_id: UUID, data_run_id: UUID) -> None: ...

    def list_linked_runs(self) -> list[tuple[UUID, UUID]]: ...

    def claim_ready_linked_run(self, run_id: UUID, data_run_id: UUID) -> bool: ...

    def fail_claimed_run(self, run_id: UUID, error_code: str) -> bool: ...

    def mark_content_started(self, run_id: UUID, created_at: datetime) -> None: ...



@runtime_checkable
class ScheduleRepositoryPort(Protocol):
    def insert_schedule(self, values: Mapping[str, object]) -> None: ...

    def list_schedules(self) -> list[dict[str, object]]: ...

    def get_schedule(self, schedule_id: UUID) -> dict[str, object] | None: ...

    def list_due_schedules(self, now: datetime) -> list[dict[str, object]]: ...

    def record_schedule_trigger(
        self,
        schedule_id: UUID,
        triggered_at: datetime,
        next_run_at: datetime | None,
    ) -> None: ...

    def update_schedule_next_run(self, schedule_id: UUID, next_run_at: datetime) -> None: ...



@runtime_checkable
class RuntimeTaskRepositoryPort(TaskRepositoryPort, ScheduleRepositoryPort, Protocol):
    """Combined task/schedule adapter exposed by the current runtime bundle."""
