"""Server-bound, version-pinned context for one A2 research task."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from sector_pulse.application.orchestration.data_tools import require_live_task_owner
from sector_pulse.domain.market.market import SectorKind
from sector_pulse.domain.orchestration.models import ArtifactRef
from sector_pulse.ports.orchestration import SnapshotRepository
from sector_pulse.storage.ports.market import (
    CandidateBatchRepositoryPort,
    MarketSnapshotRepositoryPort,
    OrchestrationSelectionRepositoryPort,
)


class SectorResearchScope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sector_kind: SectorKind
    sector_id: str

    @classmethod
    def parse(cls, value: str) -> "SectorResearchScope":
        parts = value.split(":", 2)
        if len(parts) != 3 or parts[0] != "sector" or not parts[2].strip():
            raise ValueError("A2 scope must use sector:<kind>:<id>")
        try:
            kind = SectorKind(parts[1])
        except ValueError as exc:
            raise ValueError("A2 scope contains an unknown sector kind") from exc
        return cls(sector_kind=kind, sector_id=parts[2])


class BoundSectorResearchContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    task_id: UUID
    attempt: int
    worker_id: str
    sector_id: str
    sector_kind: SectorKind
    sector_name: str
    selection_version: int
    cutoff_at: datetime
    input_artifacts: tuple[ArtifactRef, ...]


class BoundSectorResearchContextReader:
    def __init__(
        self,
        *,
        orchestration: SnapshotRepository,
        selections: OrchestrationSelectionRepositoryPort,
        candidate_batches: CandidateBatchRepositoryPort,
        market_snapshots: MarketSnapshotRepositoryPort,
        run_id: UUID,
    ) -> None:
        self._orchestration = orchestration
        self._selections = selections
        self._candidate_batches = candidate_batches
        self._market_snapshots = market_snapshots
        self._run_id = run_id

    def read(
        self,
        *,
        task_id: UUID,
        attempt: int,
        worker_id: str,
        now: datetime | None = None,
    ) -> BoundSectorResearchContext:
        observed_at = now or datetime.now(UTC)
        require_live_task_owner(
            self._orchestration,
            self._run_id,
            task_id=task_id,
            attempt=attempt,
            worker_id=worker_id,
            now=observed_at,
        )
        state = self._orchestration.load(self._run_id)
        if state is None:
            raise KeyError("orchestration run not found")
        task = next(item for item in state.tasks if item.task_id == task_id)
        if task.role != "A2":
            raise ValueError("research context requires an A2 task")
        if task.selection_version is None:
            raise ValueError("research task has no pinned selection version")
        scope = SectorResearchScope.parse(task.scope)
        selection = next(
            (
                item
                for item in self._selections.list_versions(self._run_id)
                if item.version == task.selection_version
            ),
            None,
        )
        if selection is None:
            raise ValueError("pinned selection version is unavailable")
        if scope.sector_id not in selection.selected_sector_ids:
            raise ValueError("A2 scope is outside the confirmed selection")
        artifacts_by_id = {artifact.artifact_id: artifact for artifact in state.artifacts}
        try:
            input_artifacts = tuple(
                artifacts_by_id[artifact_id] for artifact_id in task.input_artifact_ids
            )
        except KeyError as exc:
            raise ValueError("research task references an unknown artifact") from exc
        candidate_artifacts = tuple(
            artifact for artifact in input_artifacts if artifact.kind == "candidate_batch"
        )
        if len(candidate_artifacts) != 1:
            raise ValueError("research task requires one candidate batch artifact")
        reference = candidate_artifacts[0].reference
        prefix = "candidate-batch:"
        if not reference.startswith(prefix):
            raise ValueError("candidate batch artifact reference is invalid")
        batch = self._candidate_batches.get(UUID(reference[len(prefix) :]))
        if batch is None or batch.run_id != self._run_id:
            raise ValueError("candidate batch is unavailable for this run")
        candidate = next(
            (
                item
                for item in batch.candidates
                if item.provider_sector_id == scope.sector_id
                and item.kind is scope.sector_kind
            ),
            None,
        )
        if candidate is None:
            raise ValueError("A2 scope is outside the pinned candidate batch")
        run = self._market_snapshots.get_run(self._run_id)
        if run is None or run.run_cutoff_at is None:
            raise ValueError("research context requires a locked cutoff")
        return BoundSectorResearchContext(
            run_id=self._run_id,
            task_id=task_id,
            attempt=attempt,
            worker_id=worker_id,
            sector_id=scope.sector_id,
            sector_kind=scope.sector_kind,
            sector_name=candidate.name,
            selection_version=selection.version,
            cutoff_at=run.run_cutoff_at,
            input_artifacts=input_artifacts,
        )


__all__ = [
    "BoundSectorResearchContext",
    "BoundSectorResearchContextReader",
    "SectorResearchScope",
]
