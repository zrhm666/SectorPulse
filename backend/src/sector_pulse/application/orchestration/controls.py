"""Server-bound read, interaction, and finalization controls for A0-A4."""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from sector_pulse.application.orchestration.tasks import TaskCoordinator, TaskOwnershipError
from sector_pulse.domain.orchestration.models import (
    ArtifactRef,
    RunSnapshot,
    TaskRecord,
    TaskStatus,
)
from sector_pulse.ports.orchestration import SnapshotRepository


class ArtifactAccessDenied(RuntimeError):
    """The bound role cannot read the requested artifact."""


class FinalizationRejected(RuntimeError):
    """Persisted state does not satisfy the server-owned completion policy."""


@dataclass(frozen=True)
class ArtifactContent:
    summary: str
    data: Mapping[str, object] | None = None

    def bounded(self, max_chars: int) -> "ArtifactContent":
        data = self.data
        if data is not None:
            try:
                encoded = json.dumps(data, ensure_ascii=False, sort_keys=True)
            except (TypeError, ValueError):
                data = None
            else:
                if len(encoded) > max_chars:
                    data = None
        return ArtifactContent(summary=self.summary[:max_chars], data=data)


class ArtifactReader(Protocol):
    def read(self, artifact: ArtifactRef, *, max_chars: int) -> ArtifactContent: ...


@dataclass(frozen=True)
class ArtifactInspection:
    artifact_id: UUID
    kind: str
    reference: str
    summary: str
    data: Mapping[str, object] | None


@dataclass(frozen=True)
class TaskInspection:
    task_id: UUID
    parent_id: UUID | None
    role: str
    scope: str
    attempt: int
    status: TaskStatus
    artifact_ids: tuple[UUID, ...]
    artifacts: tuple[ArtifactRef, ...]
    public_error_code: str | None = None


_READABLE_KINDS: dict[str, frozenset[str]] = {
    "A1": frozenset(
        {"market_snapshot", "data_quality", "candidate_proposal", "candidate_selection"}
    ),
    "A2": frozenset(
        {
            "market_snapshot",
            "candidate_selection",
            "news",
            "evidence",
            "research_search",
            "news_detail",
            "evidence_inspection",
            "sector_analysis",
        }
    ),
    "A3": frozenset(
        {
            "candidate_selection",
            "sector_analysis",
            "evidence",
            "outline",
            "draft",
            "review",
            "governance",
            "article_outline",
            "article_draft",
            "draft_rules",
            "independent_review",
        }
    ),
    "A4": frozenset(
        {
            "candidate_selection",
            "sector_analysis",
            "news",
            "evidence",
            "draft",
            "review",
            "governance",
            "article_draft",
            "draft_rules",
            "independent_review",
        }
    ),
}


def _load_bound_task(
    repository: SnapshotRepository,
    run_id: UUID,
    task_id: UUID,
    attempt: int,
) -> tuple[RunSnapshot, TaskRecord]:
    state = repository.load(run_id)
    if state is None:
        raise KeyError("orchestration run not found")
    task = next((item for item in state.tasks if item.task_id == task_id), None)
    if task is None:
        raise KeyError("orchestration task not found")
    if task.attempt != attempt:
        raise TaskOwnershipError("stale task attempt")
    if task.status is not TaskStatus.RUNNING:
        raise TaskOwnershipError("agent task is not running")
    return state, task


class ArtifactInspector:
    def __init__(
        self,
        repository: SnapshotRepository,
        run_id: UUID,
        reader: ArtifactReader,
    ) -> None:
        self.repository = repository
        self.run_id = run_id
        self.reader = reader

    def inspect(
        self,
        task_id: UUID,
        *,
        attempt: int,
        artifact_ids: Sequence[UUID] = (),
        kinds: Sequence[str] = (),
        max_chars: int = 2000,
    ) -> tuple[ArtifactInspection, ...]:
        if not 1 <= max_chars <= 4000:
            raise ValueError("artifact detail limit must be between 1 and 4000")
        state, requester = _load_bound_task(
            self.repository, self.run_id, task_id, attempt
        )
        requested = set(artifact_ids)
        if len(requested) != len(artifact_ids) or len(requested) > 20:
            raise ValueError("artifact request must contain at most 20 unique IDs")
        selected = tuple(
            artifact
            for artifact in state.artifacts
            if (not requested or artifact.artifact_id in requested)
            and (not kinds or artifact.kind in kinds)
        )
        if requested - {artifact.artifact_id for artifact in selected}:
            raise KeyError("requested artifact was not found")
        tasks = {task.task_id: task for task in state.tasks}
        results: list[ArtifactInspection] = []
        for artifact in selected:
            owner = tasks[artifact.task_id]
            try:
                self._ensure_readable(requester, owner, artifact)
            except ArtifactAccessDenied:
                if requested:
                    raise
                continue
            content = self.reader.read(artifact, max_chars=max_chars).bounded(max_chars)
            results.append(
                ArtifactInspection(
                    artifact_id=artifact.artifact_id,
                    kind=artifact.kind,
                    reference=artifact.reference,
                    summary=content.summary,
                    data=content.data,
                )
            )
            if len(results) == 20:
                break
        return tuple(results)

    @staticmethod
    def _ensure_readable(
        requester: TaskRecord, owner: TaskRecord, artifact: ArtifactRef
    ) -> None:
        if requester.role == "A0":
            return
        if requester.role == "A2" and owner.role == "A2" and owner.task_id != requester.task_id:
            raise ArtifactAccessDenied("A2 cannot inspect another research scope")
        private_editorial_kinds = {
            "article_outline",
            "article_draft",
            "draft_rules",
            "independent_review",
        }
        if (
            requester.role in {"A3", "A4"}
            and artifact.kind in private_editorial_kinds
            and artifact.task_id != requester.task_id
            and artifact.artifact_id not in requester.input_artifact_ids
        ):
            raise ArtifactAccessDenied("editorial artifact is private to another task")
        if artifact.kind not in _READABLE_KINDS.get(requester.role, frozenset()):
            raise ArtifactAccessDenied(
                f"artifact kind is not readable by {requester.role}: {artifact.kind}"
            )


class TaskInspector:
    def __init__(self, repository: SnapshotRepository, run_id: UUID) -> None:
        self.repository = repository
        self.run_id = run_id

    def inspect(self, task_id: UUID, *, attempt: int) -> tuple[TaskInspection, ...]:
        state, requester = _load_bound_task(
            self.repository, self.run_id, task_id, attempt
        )
        if requester.parent_id is not None or requester.role != "A0":
            raise TaskOwnershipError("only the A0 root may inspect tasks")
        return tuple(
            TaskInspection(
                task_id=task.task_id,
                parent_id=task.parent_id,
                role=task.role,
                scope=task.scope,
                attempt=task.attempt,
                status=task.status,
                artifact_ids=tuple(
                    artifact.artifact_id
                    for artifact in state.artifacts
                    if artifact.task_id == task.task_id and artifact.attempt == task.attempt
                ),
                artifacts=tuple(
                    artifact
                    for artifact in state.artifacts
                    if artifact.task_id == task.task_id and artifact.attempt == task.attempt
                ),
                public_error_code=task.public_error_code,
            )
            for task in state.tasks
        )


def _ensure_root(state: RunSnapshot, task_id: UUID, attempt: int) -> TaskRecord:
    task = next((item for item in state.tasks if item.task_id == task_id), None)
    if task is None:
        raise KeyError("orchestration task not found")
    if task.attempt != attempt:
        raise TaskOwnershipError("stale task attempt")
    if task.parent_id is not None or task.role != "A0":
        raise TaskOwnershipError("only the A0 root may request this transition")
    return task


class SelectionController:
    def __init__(self, repository: SnapshotRepository, run_id: UUID) -> None:
        self.repository = repository
        self.run_id = run_id

    def request(
        self,
        task_id: UUID,
        *,
        attempt: int,
        worker_id: str,
        proposal_id: UUID,
    ) -> TaskRecord:
        def guard(state: RunSnapshot) -> None:
            _ensure_root(state, task_id, attempt)
            proposal = next(
                (item for item in state.artifacts if item.artifact_id == proposal_id), None
            )
            if proposal is None or proposal.kind != "candidate_proposal":
                raise ValueError("a candidate proposal artifact is required")

        return TaskCoordinator(self.repository, self.run_id).transition_guarded(
            task_id,
            attempt=attempt,
            worker_id=worker_id,
            target=TaskStatus.WAITING_USER_SELECTION,
            guard=guard,
        )


class CompletionGoal(StrEnum):
    DATA_PREPARATION = "data_preparation"
    RESEARCH = "research"
    FULL_ANALYSIS = "full_analysis"


ArtifactCurrencyCheck = Callable[[ArtifactRef], bool]


class RequiredArtifactsFinalizationPolicy:
    def __init__(
        self,
        *,
        goal: CompletionGoal,
        is_current: ArtifactCurrencyCheck,
        required_analysis_scopes: Sequence[str] = (),
    ) -> None:
        self.goal = goal
        self.is_current = is_current
        self.required_analysis_scopes = tuple(required_analysis_scopes)

    def validate(self, state: RunSnapshot, artifact_ids: Sequence[UUID]) -> TaskStatus:
        requested = set(artifact_ids)
        if len(requested) != len(artifact_ids) or not requested:
            raise FinalizationRejected("completion requires unique artifact references")
        artifacts = tuple(item for item in state.artifacts if item.artifact_id in requested)
        if len(artifacts) != len(requested):
            raise FinalizationRejected("completion references an unknown artifact")
        current = tuple(item for item in artifacts if self.is_current(item))
        kinds = {item.kind for item in current}
        if self.goal is CompletionGoal.DATA_PREPARATION:
            for kind, label in (
                ("market_snapshot", "current market snapshot"),
                ("data_quality", "current data quality report"),
                ("candidate_proposal", "current candidate proposal"),
            ):
                if kind not in kinds:
                    raise FinalizationRejected(f"missing {label}")
            self._ensure_children_finished(state)
            return TaskStatus.COMPLETED

        if "candidate_selection" not in kinds:
            raise FinalizationRejected("missing current candidate selection")
        tasks = {task.task_id: task for task in state.tasks}
        analysis_scopes = {
            tasks[item.task_id].scope
            for item in current
            if item.kind == "sector_analysis" and tasks[item.task_id].role == "A2"
        }
        missing_scopes = set(self.required_analysis_scopes) - analysis_scopes
        if missing_scopes:
            raise FinalizationRejected(
                "missing current sector analysis: " + ", ".join(sorted(missing_scopes))
            )
        if self.goal is CompletionGoal.RESEARCH:
            self._ensure_research_children_finished(state)
            return TaskStatus.WAITING
        for accepted_kinds, label in (
            ({"draft", "article_draft"}, "current draft"),
            ({"review", "independent_review"}, "current review"),
            ({"governance", "draft_rules"}, "current governance report"),
        ):
            if not accepted_kinds & kinds:
                raise FinalizationRejected(f"missing {label}")
        self._ensure_children_finished(state)
        return TaskStatus.WAITING_USER_REVIEW

    @staticmethod
    def _ensure_children_finished(state: RunSnapshot) -> None:
        unfinished = [
            task
            for task in state.tasks
            if task.parent_id is not None
            and task.status
            not in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
        ]
        if unfinished:
            raise FinalizationRejected("specialist tasks are still active")

    @staticmethod
    def _ensure_research_children_finished(state: RunSnapshot) -> None:
        unfinished = [
            task
            for task in state.tasks
            if task.parent_id is not None
            and task.role == "A2"
            and task.status
            not in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
        ]
        if unfinished:
            raise FinalizationRejected("research specialist tasks are still active")


class FinalizationController:
    def __init__(
        self,
        repository: SnapshotRepository,
        run_id: UUID,
        policy: RequiredArtifactsFinalizationPolicy,
    ) -> None:
        self.repository = repository
        self.run_id = run_id
        self.policy = policy

    def request(
        self,
        task_id: UUID,
        *,
        attempt: int,
        worker_id: str,
        artifact_ids: Sequence[UUID],
    ) -> TaskRecord:
        target: TaskStatus | None = None

        def guard(state: RunSnapshot) -> None:
            nonlocal target
            _ensure_root(state, task_id, attempt)
            target = self.policy.validate(state, artifact_ids)

        # The policy target is deterministic for a server-owned run goal. Validate once to
        # select the transition, then validate again inside the winning CAS transaction.
        state = self.repository.load(self.run_id)
        if state is None:
            raise KeyError("orchestration run not found")
        _ensure_root(state, task_id, attempt)
        target = self.policy.validate(state, artifact_ids)
        return TaskCoordinator(self.repository, self.run_id).transition_guarded(
            task_id,
            attempt=attempt,
            worker_id=worker_id,
            target=target,
            guard=guard,
        )
