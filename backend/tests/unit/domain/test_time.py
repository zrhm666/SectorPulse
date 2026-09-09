from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sector_pulse.domain.runs.time import (
    AnalysisMode,
    AnalysisRun,
    CutoffAlreadyLockedError,
    InvalidCutoffError,
)


def test_live_run_locks_actual_cutoff_once() -> None:
    requested = datetime(2026, 8, 13, 6, 0, tzinfo=UTC)
    observed = datetime(2026, 8, 13, 6, 0, 8, tzinfo=UTC)
    locked_at = datetime(2026, 8, 13, 6, 0, 9, tzinfo=UTC)
    locked = AnalysisRun.create_live(requested).lock_live_cutoff(observed, locked_at)
    assert locked.mode is AnalysisMode.LIVE
    assert locked.run_cutoff_at == observed
    with pytest.raises(CutoffAlreadyLockedError):
        locked.lock_live_cutoff(observed, locked_at)


def test_as_of_cutoff_is_locked_at_creation() -> None:
    run = AnalysisRun.create_as_of(
        datetime(2026, 8, 13, 8, 0, tzinfo=UTC),
        datetime(2026, 8, 12, 7, 0, tzinfo=UTC),
    )
    assert run.mode is AnalysisMode.AS_OF
    assert run.run_cutoff_at == run.requested_cutoff_at


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AnalysisRun.create_live(datetime(2026, 8, 13, 6, 0))


def test_live_cutoff_after_lock_time_is_rejected() -> None:
    run = AnalysisRun.create_live(datetime(2026, 8, 13, 6, 0, tzinfo=UTC))
    with pytest.raises(InvalidCutoffError):
        run.lock_live_cutoff(
            datetime(2026, 8, 13, 6, 1, tzinfo=UTC),
            datetime(2026, 8, 13, 6, 0, 59, tzinfo=UTC),
        )


def test_live_run_rejects_half_locked_state() -> None:
    with pytest.raises(ValidationError):
        AnalysisRun(
            run_id="00000000-0000-0000-0000-000000000001",
            mode=AnalysisMode.LIVE,
            requested_at=datetime(2026, 8, 13, 6, 0, tzinfo=UTC),
            run_cutoff_at=datetime(2026, 8, 13, 6, 0, tzinfo=UTC),
        )
