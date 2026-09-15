from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sector_pulse.domain.market.candidate_selection import CandidateSelection
from sector_pulse.domain.orchestration.models import ArtifactRef
from sector_pulse.ports.orchestration import SnapshotRepository
from sector_pulse.storage.ports.market import CandidateSelectionRepositoryPort

ALLOWED_CONTEXT_ARTIFACT_KINDS = frozenset(
    {
        "market_snapshot",
        "data_quality",
        "candidate_batch",
        "news_batch",
        "candidate_proposal",
        "evidence_pack",
        "sector_analysis",
    }
)


class ContextReferenceRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_ids: tuple[UUID, ...] = Field(min_length=1)
    selection_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_unique_artifacts(self) -> "ContextReferenceRequest":
        if len(set(self.artifact_ids)) != len(self.artifact_ids):
            raise ValueError("context artifact references must be unique")
        return self


class ReferencedResearchContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID
    artifacts: tuple[ArtifactRef, ...]
    selection: CandidateSelection | None = None


class ReferencedContextReader:
    """Resolve only caller-pinned versions; never substitutes a newer artifact."""

    def __init__(
        self,
        orchestration: SnapshotRepository,
        selections: CandidateSelectionRepositoryPort,
        run_id: UUID,
    ) -> None:
        self._orchestration = orchestration
        self._selections = selections
        self._run_id = run_id

    def read(self, request: ContextReferenceRequest) -> ReferencedResearchContext:
        state = self._orchestration.load(self._run_id)
        if state is None:
            raise KeyError("orchestration run not found")
        by_id = {item.artifact_id: item for item in state.artifacts}
        try:
            artifacts = tuple(by_id[item] for item in request.artifact_ids)
        except KeyError as exc:
            raise ValueError("context references an unknown artifact") from exc
        forbidden = {item.kind for item in artifacts} - ALLOWED_CONTEXT_ARTIFACT_KINDS
        if forbidden:
            raise ValueError("context contains a forbidden artifact kind")
        selection = None
        if request.selection_version is not None:
            selection = next(
                (
                    item
                    for item in self._selections.list_versions(self._run_id)
                    if item.version == request.selection_version
                ),
                None,
            )
            if selection is None:
                raise ValueError("context selection version is unavailable")
        return ReferencedResearchContext(
            run_id=self._run_id,
            artifacts=artifacts,
            selection=selection,
        )


__all__ = [
    "ContextReferenceRequest",
    "ReferencedContextReader",
    "ReferencedResearchContext",
]
