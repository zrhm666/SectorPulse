"""Atomic business artifact persistence and orchestration indexing."""

from datetime import UTC, datetime
from uuid import UUID

from sector_pulse.application.orchestration.tasks import TaskOwnershipError
from sector_pulse.domain.orchestration.models import ArtifactRef, TaskStatus
from sector_pulse.ports.orchestration import (
    ArtifactPersistence,
    SnapshotRepository,
    TransactionSession,
)


class ArtifactPersistenceError(RuntimeError):
    """The business artifact was not verifiably persisted in the transaction."""


class AtomicArtifactCommitter:
    def __init__(self, repository: SnapshotRepository, run_id: UUID) -> None:
        self.repository = repository
        self.run_id = run_id

    def commit(
        self,
        artifact: ArtifactRef,
        *,
        worker_id: str,
        persistence: ArtifactPersistence,
        now: datetime | None = None,
    ) -> ArtifactRef:
        observed_at = now or datetime.now(UTC)
        state = self.repository.load(self.run_id)
        if state is None:
            raise KeyError("orchestration run not found")
        task = next((item for item in state.tasks if item.task_id == artifact.task_id), None)
        if task is None:
            raise KeyError("orchestration task not found")
        if task.attempt != artifact.attempt:
            raise TaskOwnershipError("stale task attempt")
        if task.status is not TaskStatus.RUNNING or task.worker_id != worker_id:
            raise TaskOwnershipError("worker does not own task")
        if task.lease_expires_at is None or task.lease_expires_at <= observed_at:
            raise TaskOwnershipError("worker lease expired")
        if any(item.artifact_id == artifact.artifact_id for item in state.artifacts):
            raise ValueError("duplicate artifact ID")
        changed = state.model_copy(
            update={
                "revision": state.revision + 1,
                "artifacts": (*state.artifacts, artifact),
            }
        )

        def persist_and_verify(session: TransactionSession) -> None:
            persistence.write(session, artifact)
            if not persistence.exists(session, artifact):
                raise ArtifactPersistenceError("business artifact is not visible in transaction")

        self.repository.save_atomic(
            changed,
            state.revision,
            f"artifact.committed:{artifact.artifact_id}",
            persist_and_verify,
        )
        return artifact
