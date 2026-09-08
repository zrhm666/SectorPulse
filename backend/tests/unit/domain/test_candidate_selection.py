from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sector_pulse.domain.market.candidate_selection import (
    CandidateSelection,
    CandidateSelectionMethod,
    candidate_data_version,
)
from sector_pulse.domain.market.market import SectorKind
from sector_pulse.domain.runs.real_data_run import RealDataCandidate


def candidates() -> tuple[RealDataCandidate, ...]:
    return (
        RealDataCandidate(
            sector_id="881101", sector_kind=SectorKind.INDUSTRY, rank=1, score=Decimal("9.5")
        ),
        RealDataCandidate(
            sector_id="881102", sector_kind=SectorKind.INDUSTRY, rank=2, score=Decimal("8.2")
        ),
        RealDataCandidate(
            sector_id="309001", sector_kind=SectorKind.CONCEPT, rank=3, score=Decimal("7.9")
        ),
    )


def test_candidate_data_version_is_stable_for_the_same_ranked_candidates() -> None:
    first = candidate_data_version(candidates())
    second = candidate_data_version(tuple(reversed(candidates())))

    assert first == second
    assert len(first) == 64


def test_candidate_selection_accepts_an_immutable_confirmed_version() -> None:
    selection = CandidateSelection(
        run_id=uuid4(),
        version=1,
        selected_sector_ids=("881101", "881102", "309001"),
        method=CandidateSelectionMethod.DEFAULT,
        confirmed_at=datetime.now(UTC),
        data_version=candidate_data_version(candidates()),
        edit_count=0,
    )

    assert selection.version == 1
    assert selection.selected_sector_ids == ("881101", "881102", "309001")


@pytest.mark.parametrize(
    "sector_ids",
    [
        ("881101", "881102"),
        ("881101", "881101", "309001"),
        tuple(str(index) for index in range(13)),
    ],
)
def test_candidate_selection_rejects_invalid_candidate_sets(sector_ids: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError):
        CandidateSelection(
            run_id=uuid4(),
            version=1,
            selected_sector_ids=sector_ids,
            method=CandidateSelectionMethod.MANUAL,
            confirmed_at=datetime.now(UTC),
            data_version="a" * 64,
            edit_count=1,
        )


def test_candidate_selection_requires_utc_confirmation_time() -> None:
    with pytest.raises(ValidationError, match="UTC"):
        CandidateSelection(
            run_id=uuid4(),
            version=1,
            selected_sector_ids=("881101", "881102", "309001"),
            method=CandidateSelectionMethod.MANUAL,
            confirmed_at=datetime(2026, 8, 27, 12, 0),
            data_version="a" * 64,
            edit_count=1,
        )
