from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from sector_pulse.domain.market.candidate_batch import CandidateBatch
from sector_pulse.domain.market.candidate_proposal import CandidateProposal
from sector_pulse.domain.market.candidate_selection import CandidateSelection
from sector_pulse.domain.market.market import SectorKind, SectorUniverseSnapshot
from sector_pulse.domain.provider import ProviderResult
from sector_pulse.domain.runs.time import AnalysisRun


@runtime_checkable
class MarketSnapshotRepositoryPort(Protocol):
    def save(
        self, run: AnalysisRun, result: ProviderResult[SectorUniverseSnapshot]
    ) -> None: ...

    def get(self, run_id: UUID, kind: SectorKind) -> SectorUniverseSnapshot | None: ...

    def get_run(self, run_id: UUID) -> AnalysisRun | None: ...


@runtime_checkable
class CandidateBatchRepositoryPort(Protocol):
    def get(self, batch_id: UUID) -> CandidateBatch | None: ...


@runtime_checkable
class CandidateProposalRepositoryPort(Protocol):
    def get(self, proposal_id: UUID) -> CandidateProposal | None: ...



@runtime_checkable
class CandidateSelectionRepositoryPort(Protocol):
    def append(self, selection: CandidateSelection, *, expected_version: int) -> None: ...

    def latest(self, run_id: UUID) -> CandidateSelection | None: ...

    def list_versions(self, run_id: UUID) -> list[CandidateSelection]: ...


@runtime_checkable
class OrchestrationSelectionRepositoryPort(Protocol):
    def latest(self, run_id: UUID) -> CandidateSelection | None: ...

    def list_versions(self, run_id: UUID) -> list[CandidateSelection]: ...
