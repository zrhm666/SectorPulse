from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sector_pulse.application.candidate_selection_service import (
    CandidateSelectionInvalid,
    CandidateSelectionRequired,
    CandidateSelectionService,
)
from sector_pulse.domain.candidate_selection import CandidateSelectionVersionConflict
from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.real_data_run import RealDataCandidate, RealDataRun, RealDataRunRequest


class Runs:
    def __init__(self) -> None:
        self.run = RealDataRun(run_id=uuid4(), request=RealDataRunRequest(mode="post_close"))
        self.candidates = [
            RealDataCandidate(
                sector_id=f"sector-{rank}",
                sector_kind=SectorKind.INDUSTRY,
                rank=rank,
                score=Decimal(10 - rank),
            )
            for rank in range(1, 5)
        ]

    def get_run(self, run_id):
        return self.run if run_id == self.run.run_id else None

    def get_candidates(self, run_id):
        return list(self.candidates) if run_id == self.run.run_id else []


class Selections:
    def __init__(self) -> None:
        self.items = []

    def latest(self, run_id):
        matching = [item for item in self.items if item.run_id == run_id]
        return matching[-1] if matching else None

    def append(self, selection, *, expected_version):
        actual = self.latest(selection.run_id)
        actual_version = actual.version if actual else 0
        if expected_version != actual_version:
            raise CandidateSelectionVersionConflict("stale")
        self.items.append(selection)


def test_preview_uses_ranked_candidates_without_confirming_them() -> None:
    runs = Runs()
    service = CandidateSelectionService(runs, Selections(), clock=lambda: datetime.now(UTC))

    view = service.view(runs.run.run_id)

    assert view.confirmed is False
    assert view.version == 0
    assert view.selected_sector_ids == ("sector-1", "sector-2", "sector-3", "sector-4")
    with pytest.raises(CandidateSelectionRequired):
        service.require_confirmed(runs.run.run_id)


def test_manual_confirmation_appends_an_immutable_version() -> None:
    runs = Runs()
    selections = Selections()
    service = CandidateSelectionService(runs, selections, clock=lambda: datetime.now(UTC))

    first = service.confirm(
        runs.run.run_id,
        ("sector-3", "sector-1", "sector-2"),
        expected_version=0,
    )
    second = service.confirm(
        runs.run.run_id,
        ("sector-1", "sector-2", "sector-4"),
        expected_version=1,
    )

    assert first.version == 1
    assert first.selected_sector_ids == ("sector-1", "sector-2", "sector-3")
    assert first.edit_count == 1
    assert second.version == 2
    assert second.edit_count == 2
    assert service.require_confirmed(runs.run.run_id) == second


@pytest.mark.parametrize(
    "sector_ids",
    [
        ("sector-1", "sector-2"),
        ("sector-1", "sector-1", "sector-2"),
        ("sector-1", "sector-2", "missing"),
    ],
)
def test_confirmation_rejects_invalid_membership(sector_ids: tuple[str, ...]) -> None:
    runs = Runs()
    service = CandidateSelectionService(runs, Selections(), clock=lambda: datetime.now(UTC))

    with pytest.raises(CandidateSelectionInvalid):
        service.confirm(runs.run.run_id, sector_ids, expected_version=0)


def test_confirm_default_is_idempotent_for_scheduled_generation() -> None:
    runs = Runs()
    selections = Selections()
    service = CandidateSelectionService(runs, selections, clock=lambda: datetime.now(UTC))

    first = service.confirm_default(runs.run.run_id)
    second = service.confirm_default(runs.run.run_id)

    assert first == second
    assert first.edit_count == 0
    assert len(selections.items) == 1
