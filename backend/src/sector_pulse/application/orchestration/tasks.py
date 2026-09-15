"""CAS-backed task lifecycle, worker leases, recovery, and artifact admission."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from sector_pulse.domain.orchestration.models import (
    ArtifactRef,
    RunSnapshot,
    TaskRecord,
    TaskStatus,
)
from sector_pulse.ports.orchestration import RevisionConflict, SnapshotRepository


class InvalidTaskTransition(RuntimeError):
    """The requested lifecycle edge is not part of the task state machine."""


class TaskOwnershipError(RuntimeError):
    """The caller does not own the current live task attempt."""


class DelegationLimitExceeded(RuntimeError):
    """A parent attempted to exceed a server-owned child task limit."""


_TERMINAL = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
_TRANSITIONS = {
    TaskStatus.CREATED: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.INTERRUPTED,
        TaskStatus.WAITING,
        TaskStatus.WAITING_USER_SELECTION,
        TaskStatus.WAITING_USER_REVIEW,
    },
    TaskStatus.WAITING: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.WAITING_USER_SELECTION: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.WAITING_USER_REVIEW: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.INTERRUPTED: {TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
}


class TaskCoordinator:
    """Persist task decisions with optimistic concurrency across worker processes."""

    def __init__(self, repository: SnapshotRepository, run_id: UUID) -> None:
        self.repository = repository
        self.run_id = run_id

    def _change(
        self,
        transform: Callable[[RunSnapshot], tuple[RunSnapshot, TaskRecord]],
        event: str,
    ) -> TaskRecord:
        for _ in range(32):
            current = self.repository.load(self.run_id)
            if current is None:
                raise KeyError("orchestration run not found")
            changed, result = transform(current)
            if changed == current:
                return result
            changed = changed.model_copy(update={"revision": current.revision + 1})
            try:
                self.repository.save(changed, current.revision, event)
                return result
            except RevisionConflict:
                continue
        raise RevisionConflict("task contention exceeded retry limit")

    @staticmethod
    def _task(state: RunSnapshot, task_id: UUID) -> TaskRecord:
        task = next((item for item in state.tasks if item.task_id == task_id), None)
        if task is None:
            raise KeyError("orchestration task not found")
        return task

    @staticmethod
    def _replace(state: RunSnapshot, updated: TaskRecord) -> RunSnapshot:
        return state.model_copy(
            update={
                "tasks": tuple(
                    updated if task.task_id == updated.task_id else task for task in state.tasks
                )
            }
        )

    @staticmethod
    def _stamp_run_finish(
        state: RunSnapshot, task: TaskRecord, target: TaskStatus, observed_at: datetime
    ) -> RunSnapshot:
        """Track when the root stopped or resumed owning the run.

        Only the root decides this; a child finishing never ends the run. The
        timestamp is cleared again when the root resumes, so it always answers
        "when did this run last stop working".
        """
        if task.parent_id is not None:
            return state
        return state.model_copy(
            update={"finished_at": None if target is TaskStatus.RUNNING else observed_at}
        )

    @staticmethod
    def _ensure_transition(source: TaskStatus, target: TaskStatus) -> None:
        if target not in _TRANSITIONS[source]:
            raise InvalidTaskTransition(f"cannot transition {source.value} to {target.value}")

    @staticmethod
    def _ensure_attempt(task: TaskRecord, attempt: int) -> None:
        if task.attempt != attempt:
            raise TaskOwnershipError("stale task attempt")

    @staticmethod
    def _ensure_live_owner(task: TaskRecord, worker_id: str, now: datetime) -> None:
        if task.worker_id != worker_id:
            raise TaskOwnershipError("worker does not own task")
        if task.lease_expires_at is None or task.lease_expires_at <= now:
            raise TaskOwnershipError("worker lease expired")

    def start(
        self,
        task_id: UUID,
        *,
        attempt: int,
        worker_id: str,
        lease_expires_at: datetime,
        now: datetime | None = None,
    ) -> TaskRecord:
        observed_at = now or datetime.now(UTC)
        if not worker_id.strip():
            raise ValueError("worker ID is required")
        if lease_expires_at.tzinfo is None or lease_expires_at <= observed_at:
            raise ValueError("lease must expire in the future")

        def apply(state: RunSnapshot) -> tuple[RunSnapshot, TaskRecord]:
            task = self._task(state, task_id)
            self._ensure_attempt(task, attempt)
            self._ensure_transition(task.status, TaskStatus.RUNNING)
            updated = task.model_copy(
                update={
                    "status": TaskStatus.RUNNING,
                    "worker_id": worker_id,
                    "lease_expires_at": lease_expires_at,
                }
            )
            return (
                self._stamp_run_finish(
                    self._replace(state, updated), task, TaskStatus.RUNNING, observed_at
                ),
                updated,
            )

        return self._change(apply, f"task.started:{task_id}:{attempt}")

    def transition(
        self,
        task_id: UUID,
        *,
        attempt: int,
        worker_id: str,
        target: TaskStatus,
        now: datetime | None = None,
    ) -> TaskRecord:
        return self.transition_guarded(
            task_id,
            attempt=attempt,
            worker_id=worker_id,
            target=target,
            now=now,
        )

    def transition_guarded(
        self,
        task_id: UUID,
        *,
        attempt: int,
        worker_id: str,
        target: TaskStatus,
        guard: Callable[[RunSnapshot], None] | None = None,
        public_error_code: str | None = None,
        now: datetime | None = None,
    ) -> TaskRecord:
        observed_at = now or datetime.now(UTC)
        if public_error_code is not None and target is not TaskStatus.FAILED:
            raise ValueError("public error code requires a failed transition")

        def apply(state: RunSnapshot) -> tuple[RunSnapshot, TaskRecord]:
            task = self._task(state, task_id)
            self._ensure_attempt(task, attempt)
            self._ensure_live_owner(task, worker_id, observed_at)
            self._ensure_transition(task.status, target)
            if guard is not None:
                guard(state)
            ownership = (
                {}
                if target is TaskStatus.INTERRUPTED
                else {"worker_id": None, "lease_expires_at": None}
            )
            updated = task.model_copy(
                update={
                    "status": target,
                    "public_error_code": public_error_code,
                    **ownership,
                }
            )
            return (
                self._stamp_run_finish(self._replace(state, updated), task, target, observed_at),
                updated,
            )

        return self._change(apply, f"task.{target.value}:{task_id}:{attempt}")

    def fail(
        self,
        task_id: UUID,
        *,
        attempt: int,
        worker_id: str,
        public_error_code: str,
        now: datetime | None = None,
    ) -> TaskRecord:
        return self.transition_guarded(
            task_id,
            attempt=attempt,
            worker_id=worker_id,
            target=TaskStatus.FAILED,
            public_error_code=public_error_code,
            now=now,
        )

    def renew_lease(
        self,
        task_id: UUID,
        *,
        attempt: int,
        worker_id: str,
        lease_expires_at: datetime,
        now: datetime | None = None,
    ) -> TaskRecord:
        observed_at = now or datetime.now(UTC)
        if lease_expires_at.tzinfo is None or lease_expires_at <= observed_at:
            raise ValueError("lease must expire in the future")

        def apply(state: RunSnapshot) -> tuple[RunSnapshot, TaskRecord]:
            task = self._task(state, task_id)
            self._ensure_attempt(task, attempt)
            self._ensure_live_owner(task, worker_id, observed_at)
            if task.status is not TaskStatus.RUNNING:
                raise InvalidTaskTransition(f"cannot renew task in {task.status.value} state")
            if task.lease_expires_at is not None and lease_expires_at <= task.lease_expires_at:
                raise ValueError("lease renewal must extend the current lease")
            updated = task.model_copy(update={"lease_expires_at": lease_expires_at})
            return self._replace(state, updated), updated

        return self._change(apply, f"task.lease_renewed:{task_id}:{attempt}")

    def recover(
        self,
        task_id: UUID,
        *,
        expected_attempt: int,
        worker_id: str,
        lease_expires_at: datetime,
        now: datetime | None = None,
    ) -> TaskRecord:
        observed_at = now or datetime.now(UTC)
        if not worker_id.strip():
            raise ValueError("worker ID is required")
        if lease_expires_at.tzinfo is None or lease_expires_at <= observed_at:
            raise ValueError("lease must expire in the future")

        def apply(state: RunSnapshot) -> tuple[RunSnapshot, TaskRecord]:
            task = self._task(state, task_id)
            self._ensure_attempt(task, expected_attempt)
            if task.status not in {TaskStatus.RUNNING, TaskStatus.INTERRUPTED}:
                raise InvalidTaskTransition(
                    f"cannot recover task in {task.status.value} state"
                )
            if task.lease_expires_at is None:
                raise TaskOwnershipError("recovery requires an expired lease")
            if task.lease_expires_at > observed_at:
                raise TaskOwnershipError("task still has an active lease")
            updated = task.model_copy(
                update={
                    "attempt": task.attempt + 1,
                    "status": TaskStatus.RUNNING,
                    "worker_id": worker_id,
                    "lease_expires_at": lease_expires_at,
                }
            )
            return (
                self._stamp_run_finish(
                    self._replace(state, updated), task, TaskStatus.RUNNING, observed_at
                ),
                updated,
            )

        return self._change(apply, f"task.recovered:{task_id}:{expected_attempt + 1}")

    def delegate_child(
        self,
        parent_id: UUID,
        *,
        parent_attempt: int,
        parent_worker_id: str,
        child_id: UUID,
        child_worker_id: str,
        child_lease_expires_at: datetime,
        role: str,
        scope: str,
        input_artifact_ids: tuple[UUID, ...] = (),
        selection_version: int | None = None,
        now: datetime | None = None,
    ) -> TaskRecord:
        observed_at = now or datetime.now(UTC)
        if role not in {"A1", "A2", "A3", "A4"}:
            raise ValueError("unregistered child role")
        if not scope.strip() or not child_worker_id.strip():
            raise ValueError("child scope and worker ID are required")
        if len(set(input_artifact_ids)) != len(input_artifact_ids):
            raise ValueError("child input artifact IDs must be unique")
        if selection_version is not None and selection_version < 1:
            raise ValueError("selection version must be positive")
        if (
            child_lease_expires_at.tzinfo is None
            or child_lease_expires_at <= observed_at
        ):
            raise ValueError("child lease must expire in the future")

        def apply(state: RunSnapshot) -> tuple[RunSnapshot, TaskRecord]:
            parent = self._task(state, parent_id)
            self._ensure_attempt(parent, parent_attempt)
            self._ensure_live_owner(parent, parent_worker_id, observed_at)
            if parent.parent_id is not None or parent.role != "A0":
                raise TaskOwnershipError("only the A0 root task may delegate")
            if any(task.task_id == child_id for task in state.tasks):
                raise ValueError("duplicate task ID")
            known_artifact_ids = {artifact.artifact_id for artifact in state.artifacts}
            if not set(input_artifact_ids).issubset(known_artifact_ids):
                raise ValueError("child references an unknown artifact")
            active = [task for task in state.tasks if task.status not in _TERMINAL]
            if role == "A2":
                active_research = [task for task in active if task.role == "A2"]
                if any(task.scope == scope for task in active_research):
                    raise DelegationLimitExceeded("an active A2 task already owns this scope")
                if len(active_research) >= 2:
                    raise DelegationLimitExceeded("active A2 task limit reached")
            child = TaskRecord(
                task_id=child_id,
                parent_id=parent_id,
                role=role,
                scope=scope,
                status=TaskStatus.RUNNING,
                worker_id=child_worker_id,
                lease_expires_at=child_lease_expires_at,
                input_artifact_ids=input_artifact_ids,
                selection_version=selection_version,
            )
            return state.model_copy(update={"tasks": (*state.tasks, child)}), child

        return self._change(apply, f"task.delegated:{parent_id}:{child_id}:{role}")

    def cancel(self, task_id: UUID, now: datetime | None = None) -> TaskRecord:
        observed_at = now or datetime.now(UTC)

        def apply(state: RunSnapshot) -> tuple[RunSnapshot, TaskRecord]:
            selected = self._task(state, task_id)
            if selected.status in _TERMINAL:
                return state, selected
            self._ensure_transition(selected.status, TaskStatus.CANCELLED)
            affected = {task_id}
            if selected.parent_id is None:
                affected.update(
                    task.task_id
                    for task in state.tasks
                    if task.parent_id == task_id and task.status not in _TERMINAL
                )
            tasks = tuple(
                task.model_copy(
                    update={
                        "status": TaskStatus.CANCELLED,
                        "worker_id": None,
                        "lease_expires_at": None,
                    }
                )
                if task.task_id in affected
                else task
                for task in state.tasks
            )
            updated = next(task for task in tasks if task.task_id == task_id)
            changed = self._stamp_run_finish(
                state.model_copy(update={"tasks": tasks}),
                selected,
                TaskStatus.CANCELLED,
                observed_at,
            )
            return changed, updated

        return self._change(apply, f"task.cancelled:{task_id}")

    def submit_artifact(
        self,
        artifact: ArtifactRef,
        *,
        worker_id: str,
        now: datetime | None = None,
    ) -> ArtifactRef:
        observed_at = now or datetime.now(UTC)

        def apply(state: RunSnapshot) -> tuple[RunSnapshot, TaskRecord]:
            task = self._task(state, artifact.task_id)
            self._ensure_attempt(task, artifact.attempt)
            self._ensure_live_owner(task, worker_id, observed_at)
            if any(item.artifact_id == artifact.artifact_id for item in state.artifacts):
                raise ValueError("duplicate artifact ID")
            changed = state.model_copy(update={"artifacts": (*state.artifacts, artifact)})
            return changed, task

        self._change(apply, f"artifact.submitted:{artifact.artifact_id}")
        return artifact
