"""Create a server-owned orchestration run from production configuration."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sector_pulse.application.orchestration.tasks import TaskCoordinator
from sector_pulse.config.llm_config import LLMRuntimeConfig
from sector_pulse.domain.orchestration.models import ArtifactRef, RunSnapshot, TaskRecord
from sector_pulse.ports.orchestration import SnapshotRepository


class OrchestrationRunStarter:
    def __init__(
        self,
        repository: SnapshotRepository,
        config: LLMRuntimeConfig,
    ) -> None:
        self.repository = repository
        self.config = config

    def start(
        self,
        *,
        run_id: UUID,
        task_id: UUID,
        worker_id: str,
        goal: str,
        provider: Literal["fixture", "live"] = "fixture",
        selection_policy: Literal["manual", "server_default"] = "manual",
        retry_of_run_id: UUID | None = None,
        initial_artifacts: tuple[ArtifactRef, ...] = (),
        selection_version: int | None = None,
        now: datetime | None = None,
    ) -> TaskRecord:
        observed_at = now or datetime.now(UTC)
        if observed_at.tzinfo is None:
            raise ValueError("run start time must be timezone aware")
        if not goal.strip():
            raise ValueError("run goal is required")
        deadline = observed_at + timedelta(seconds=self.config.orchestration_timeout_seconds)
        root = TaskRecord(
            task_id=task_id,
            role="A0",
            scope=goal,
            input_artifact_ids=tuple(item.artifact_id for item in initial_artifacts),
            selection_version=selection_version,
        )
        snapshot = RunSnapshot(
            run_id=run_id,
            requested_at=observed_at,
            provider=provider,
            selection_policy=selection_policy,
            retry_of_run_id=retry_of_run_id,
            deadline=deadline,
            limits=self.config.orchestration_budget_limits(),
            tasks=(root,),
            artifacts=initial_artifacts,
        )
        self.repository.save(snapshot, -1, "run.created")
        return TaskCoordinator(self.repository, run_id).start(
            task_id,
            attempt=1,
            worker_id=worker_id,
            lease_expires_at=deadline,
            now=observed_at,
        )
