"""Server-bound, version-pinned context for A3 editorial work."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from sector_pulse.application.orchestration.data_tools import require_live_task_owner
from sector_pulse.domain.market.candidate_selection import CandidateSelection
from sector_pulse.domain.orchestration.models import ArtifactRef, TaskStatus
from sector_pulse.domain.review.review import ReviewDecision
from sector_pulse.domain.writing.editorial import (
    EditorialDraftArtifact,
    IndependentReviewArtifact,
)
from sector_pulse.domain.writing.research import SectorAnalysisArtifact
from sector_pulse.ports.orchestration import SnapshotRepository
from sector_pulse.storage.ports.market import CandidateSelectionRepositoryPort
from sector_pulse.storage.ports.writing import (
    EditorialDraftRepositoryPort,
    EditorialOutlineRepositoryPort,
    IndependentReviewRepositoryPort,
    SectorAnalysisRepositoryPort,
)


class BoundEditorialContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    task_id: UUID
    attempt: int
    worker_id: str
    selection: CandidateSelection
    analyses: tuple[SectorAnalysisArtifact, ...]
    input_artifacts: tuple[ArtifactRef, ...]


class BoundEditorialContextReader:
    def __init__(
        self,
        *,
        orchestration: SnapshotRepository,
        selections: CandidateSelectionRepositoryPort,
        analyses: SectorAnalysisRepositoryPort,
        run_id: UUID,
    ) -> None:
        self._orchestration = orchestration
        self._selections = selections
        self._analyses = analyses
        self._run_id = run_id

    def read(
        self,
        *,
        task_id: UUID,
        attempt: int,
        worker_id: str,
        now: datetime | None = None,
    ) -> BoundEditorialContext:
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
        if task.role != "A3":
            raise ValueError("editorial context requires an A3 task")
        if task.scope != f"article:{self._run_id}":
            raise ValueError("A3 scope must identify this run")
        if task.selection_version is None:
            raise ValueError("editorial task has no pinned selection version")
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

        artifacts_by_id = {artifact.artifact_id: artifact for artifact in state.artifacts}
        try:
            input_artifacts = tuple(
                artifacts_by_id[artifact_id] for artifact_id in task.input_artifact_ids
            )
        except KeyError as exc:
            raise ValueError("editorial task references an unknown artifact") from exc
        selection_artifacts = tuple(
            item for item in input_artifacts if item.kind == "candidate_selection"
        )
        analysis_artifacts = tuple(
            item for item in input_artifacts if item.kind == "sector_analysis"
        )
        if len(selection_artifacts) != 1:
            raise ValueError("editorial task requires one candidate selection artifact")
        if set(item.kind for item in input_artifacts) - {
            "candidate_selection",
            "sector_analysis",
        }:
            raise ValueError("editorial task contains an unsupported input artifact")
        tasks = {item.task_id: item for item in state.tasks}
        loaded_by_sector: dict[str, SectorAnalysisArtifact] = {}
        for artifact in analysis_artifacts:
            owner = tasks[artifact.task_id]
            if (
                owner.role != "A2"
                or owner.status is not TaskStatus.COMPLETED
                or artifact.attempt != owner.attempt
            ):
                raise ValueError("analysis artifact is not from the current task attempt")
            prefix = "sector-analysis:"
            if not artifact.reference.startswith(prefix):
                raise ValueError("analysis artifact reference is invalid")
            try:
                analysis_id = UUID(artifact.reference[len(prefix) :])
            except ValueError as exc:
                raise ValueError("analysis artifact reference is invalid") from exc
            analysis = self._analyses.get(analysis_id)
            if analysis is None:
                raise ValueError("analysis is unavailable")
            if analysis.analysis_id != artifact.artifact_id:
                raise ValueError("analysis artifact identity mismatch")
            if analysis.run_id != self._run_id:
                raise ValueError("analysis is outside this run")
            if (
                analysis.task_id != artifact.task_id
                or analysis.attempt != artifact.attempt
            ):
                raise ValueError("analysis artifact ownership mismatch")
            sector_id = analysis.card.sector_id
            if sector_id in loaded_by_sector:
                raise ValueError("editorial context contains duplicate sector analysis")
            loaded_by_sector[sector_id] = analysis
        if set(loaded_by_sector) != set(selection.selected_sector_ids):
            raise ValueError("editorial context must contain every selected sector analysis")
        ordered = tuple(loaded_by_sector[item] for item in selection.selected_sector_ids)
        return BoundEditorialContext(
            run_id=self._run_id,
            task_id=task_id,
            attempt=attempt,
            worker_id=worker_id,
            selection=selection,
            analyses=ordered,
            input_artifacts=input_artifacts,
        )


class BoundReviewContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    task_id: UUID
    attempt: int
    worker_id: str
    role: str
    draft: EditorialDraftArtifact
    analyses: tuple[SectorAnalysisArtifact, ...]
    input_artifacts: tuple[ArtifactRef, ...]


class BoundReviewContextReader:
    def __init__(
        self,
        *,
        orchestration: SnapshotRepository,
        drafts: EditorialDraftRepositoryPort,
        outlines: EditorialOutlineRepositoryPort,
        analyses: SectorAnalysisRepositoryPort,
        run_id: UUID,
    ) -> None:
        self._orchestration = orchestration
        self._drafts = drafts
        self._outlines = outlines
        self._analyses = analyses
        self._run_id = run_id

    def read(
        self,
        *,
        task_id: UUID,
        attempt: int,
        worker_id: str,
        now: datetime | None = None,
    ) -> BoundReviewContext:
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
        if task.role != "A4":
            raise ValueError("review context requires an A4 task")
        artifacts_by_id = {item.artifact_id: item for item in state.artifacts}
        try:
            input_artifacts = tuple(
                artifacts_by_id[identity] for identity in task.input_artifact_ids
            )
        except KeyError as exc:
            raise ValueError("review task references an unknown artifact") from exc
        if len(input_artifacts) != 1 or input_artifacts[0].kind != "article_draft":
            raise ValueError("review task requires one explicit draft artifact")
        draft_ref = input_artifacts[0]
        draft = self._drafts.get(draft_ref.artifact_id)
        if draft is None or draft.artifact_id != draft_ref.artifact_id:
            raise ValueError("pinned draft artifact is unavailable")
        if draft.run_id != self._run_id or draft.draft.run_id != self._run_id:
            raise ValueError("pinned draft is outside this run")
        if task.scope != f"review:{draft.draft.draft_id}:{draft.draft.version}":
            raise ValueError("A4 scope must match the pinned draft version")
        owner = next(
            (item for item in state.tasks if item.task_id == draft_ref.task_id), None
        )
        if owner is None or draft_ref.attempt != owner.attempt:
            raise ValueError("draft artifact is not from the current task attempt")
        if draft.task_id != draft_ref.task_id or draft.attempt != draft_ref.attempt:
            raise ValueError("draft artifact ownership mismatch")
        outline = self._outlines.get(draft.outline_id)
        if outline is None or outline.run_id != self._run_id:
            raise ValueError("draft outline is unavailable")
        loaded_analyses = []
        for analysis_id in outline.input_analysis_ids:
            analysis = self._analyses.get(analysis_id)
            if analysis is None or analysis.analysis_id != analysis_id:
                raise ValueError("draft analysis is unavailable")
            if analysis.run_id != self._run_id:
                raise ValueError("draft analysis is outside this run")
            loaded_analyses.append(analysis)
        if {item.card.sector_id for item in loaded_analyses} != {
            item.sector_id for item in draft.draft.sections
        }:
            raise ValueError("draft analyses do not match its sections")
        return BoundReviewContext(
            run_id=self._run_id,
            task_id=task_id,
            attempt=attempt,
            worker_id=worker_id,
            role="A4",
            draft=draft,
            analyses=tuple(loaded_analyses),
            input_artifacts=input_artifacts,
        )


class BoundRevisionContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    task_id: UUID
    attempt: int
    worker_id: str
    role: str
    draft: EditorialDraftArtifact
    review: IndependentReviewArtifact
    analyses: tuple[SectorAnalysisArtifact, ...]
    input_artifacts: tuple[ArtifactRef, ...]


class BoundRevisionContextReader:
    def __init__(
        self,
        *,
        orchestration: SnapshotRepository,
        drafts: EditorialDraftRepositoryPort,
        reviews: IndependentReviewRepositoryPort,
        outlines: EditorialOutlineRepositoryPort,
        analyses: SectorAnalysisRepositoryPort,
        run_id: UUID,
    ) -> None:
        self._orchestration = orchestration
        self._drafts = drafts
        self._reviews = reviews
        self._outlines = outlines
        self._analyses = analyses
        self._run_id = run_id

    def read(
        self,
        *,
        task_id: UUID,
        attempt: int,
        worker_id: str,
        now: datetime | None = None,
    ) -> BoundRevisionContext:
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
        if task.role != "A3":
            raise ValueError("revision context requires an A3 task")
        artifacts_by_id = {item.artifact_id: item for item in state.artifacts}
        try:
            inputs = tuple(artifacts_by_id[item] for item in task.input_artifact_ids)
        except KeyError as exc:
            raise ValueError("revision task references an unknown artifact") from exc
        draft_refs = tuple(item for item in inputs if item.kind == "article_draft")
        review_refs = tuple(item for item in inputs if item.kind == "independent_review")
        if len(inputs) != 2 or len(draft_refs) != 1 or len(review_refs) != 1:
            raise ValueError("revision task requires one draft and one independent review")
        draft_ref, review_ref = draft_refs[0], review_refs[0]
        draft = self._drafts.get(draft_ref.artifact_id)
        review = self._reviews.get(review_ref.artifact_id)
        if draft is None or draft.artifact_id != draft_ref.artifact_id:
            raise ValueError("revision base draft is unavailable")
        if review is None or review.artifact_id != review_ref.artifact_id:
            raise ValueError("revision review is unavailable")
        if draft.run_id != self._run_id or review.run_id != self._run_id:
            raise ValueError("revision inputs are outside this run")
        if task.scope != f"revision:{draft.draft.draft_id}:{draft.draft.version}":
            raise ValueError("A3 revision scope must match the base draft version")
        if (
            review.draft_artifact_id != draft.artifact_id
            or review.report.draft_id != str(draft.draft.draft_id)
            or review.report.draft_version != draft.draft.version
            or review.report.decision is not ReviewDecision.REVISE
        ):
            raise ValueError("review does not authorize this base draft")
        tasks = {item.task_id: item for item in state.tasks}
        for reference, payload_task_id, payload_attempt in (
            (draft_ref, draft.task_id, draft.attempt),
            (review_ref, review.task_id, review.attempt),
        ):
            owner = tasks.get(reference.task_id)
            if owner is None or owner.status is not TaskStatus.COMPLETED:
                raise ValueError("revision input owner is not completed")
            if reference.attempt != owner.attempt:
                raise ValueError("revision input is from a stale task attempt")
            if payload_task_id != reference.task_id or payload_attempt != reference.attempt:
                raise ValueError("revision input ownership mismatch")
        outline = self._outlines.get(draft.outline_id)
        if outline is None or outline.run_id != self._run_id:
            raise ValueError("revision outline is unavailable")
        loaded = []
        for analysis_id in outline.input_analysis_ids:
            analysis = self._analyses.get(analysis_id)
            if analysis is None or analysis.run_id != self._run_id:
                raise ValueError("revision analysis is unavailable")
            loaded.append(analysis)
        if {item.card.sector_id for item in loaded} != {
            item.sector_id for item in draft.draft.sections
        }:
            raise ValueError("revision analyses do not match draft sections")
        return BoundRevisionContext(
            run_id=self._run_id,
            task_id=task_id,
            attempt=attempt,
            worker_id=worker_id,
            role="A3",
            draft=draft,
            review=review,
            analyses=tuple(loaded),
            input_artifacts=inputs,
        )


__all__ = [
    "BoundEditorialContext",
    "BoundEditorialContextReader",
    "BoundReviewContext",
    "BoundReviewContextReader",
    "BoundRevisionContext",
    "BoundRevisionContextReader",
]
