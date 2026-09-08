from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sector_pulse.domain.market.candidate_selection import (
    CandidateSelection,
    CandidateSelectionMethod,
    candidate_data_version,
)
from sector_pulse.domain.runs.real_data_run import RealDataCandidate, RealDataRun


class CandidateSelectionNotFound(ValueError):
    pass


class CandidateSelectionInvalid(ValueError):
    pass


class CandidateSelectionRequired(ValueError):
    pass


class RunReader(Protocol):
    def get_run(self, run_id: UUID) -> RealDataRun | None: ...

    def get_candidates(self, run_id: UUID) -> list[RealDataCandidate]: ...


class SelectionRepository(Protocol):
    def latest(self, run_id: UUID) -> CandidateSelection | None: ...

    def append(self, selection: CandidateSelection, *, expected_version: int) -> None: ...


@dataclass(frozen=True)
class CandidateSelectionView:
    run_id: UUID
    confirmed: bool
    version: int
    selected_sector_ids: tuple[str, ...]
    method: CandidateSelectionMethod | None
    confirmed_at: datetime | None
    data_version: str
    edit_count: int


class CandidateSelectionService:
    def __init__(
        self,
        runs: RunReader,
        selections: SelectionRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._runs = runs
        self._selections = selections
        self._clock = clock or (lambda: datetime.now(UTC))

    def view(self, run_id: UUID) -> CandidateSelectionView:
        candidates = self._require_candidates(run_id)
        latest = self._selections.latest(run_id)
        if latest is not None:
            return self._view(latest)
        return CandidateSelectionView(
            run_id=run_id,
            confirmed=False,
            version=0,
            selected_sector_ids=tuple(item.sector_id for item in candidates),
            method=None,
            confirmed_at=None,
            data_version=candidate_data_version(tuple(candidates)),
            edit_count=0,
        )

    def confirm(
        self,
        run_id: UUID,
        sector_ids: tuple[str, ...],
        *,
        expected_version: int,
    ) -> CandidateSelection:
        candidates = self._require_candidates(run_id)
        if not 3 <= len(sector_ids) <= 12 or len(set(sector_ids)) != len(sector_ids):
            raise CandidateSelectionInvalid("CANDIDATE_SELECTION_INVALID")
        selected = set(sector_ids)
        available = {item.sector_id for item in candidates}
        if not selected.issubset(available):
            raise CandidateSelectionInvalid("CANDIDATE_SELECTION_INVALID")
        ordered = tuple(item.sector_id for item in candidates if item.sector_id in selected)
        all_candidates = tuple(item.sector_id for item in candidates)
        method = (
            CandidateSelectionMethod.DEFAULT
            if ordered == all_candidates
            else CandidateSelectionMethod.MANUAL
        )
        current = self._selections.latest(run_id)
        edit_count = (current.edit_count if current else 0) + (
            1 if method is CandidateSelectionMethod.MANUAL else 0
        )
        selection = CandidateSelection(
            run_id=run_id,
            version=expected_version + 1,
            selected_sector_ids=ordered,
            method=method,
            confirmed_at=self._clock(),
            data_version=candidate_data_version(tuple(candidates)),
            edit_count=edit_count,
        )
        self._selections.append(selection, expected_version=expected_version)
        return selection

    def confirm_default(self, run_id: UUID) -> CandidateSelection:
        current = self._selections.latest(run_id)
        if current is not None:
            return current
        view = self.view(run_id)
        return self.confirm(run_id, view.selected_sector_ids, expected_version=0)

    def require_confirmed(self, run_id: UUID) -> CandidateSelection:
        self._require_run(run_id)
        selection = self._selections.latest(run_id)
        if selection is None:
            raise CandidateSelectionRequired("CANDIDATE_SELECTION_REQUIRED")
        return selection

    def _require_run(self, run_id: UUID) -> RealDataRun:
        run = self._runs.get_run(run_id)
        if run is None:
            raise CandidateSelectionNotFound("REAL_DATA_RUN_NOT_FOUND")
        return run

    def _require_candidates(self, run_id: UUID) -> list[RealDataCandidate]:
        self._require_run(run_id)
        candidates = self._runs.get_candidates(run_id)
        return sorted(candidates, key=lambda item: (item.rank, item.sector_id))

    @staticmethod
    def _view(selection: CandidateSelection) -> CandidateSelectionView:
        return CandidateSelectionView(
            run_id=selection.run_id,
            confirmed=True,
            version=selection.version,
            selected_sector_ids=selection.selected_sector_ids,
            method=selection.method,
            confirmed_at=selection.confirmed_at,
            data_version=selection.data_version,
            edit_count=selection.edit_count,
        )
