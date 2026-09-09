from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sector_pulse.domain.runs.real_data_run import (
    RealDataRun,
    RealDataRunRequest,
    RealDataRunStatus,
)
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.runs.real_data_run_repository import SQLiteRealDataRunRepository


def test_history_beyond_fifty_and_same_timestamp_order(tmp_path: Path) -> None:
    repo = SQLiteRealDataRunRepository(SQLiteDatabase(tmp_path / "comparison.sqlite"))
    now = datetime(2026, 9, 7, tzinfo=UTC)
    for number in range(1, 56):
        repo.insert(
            RealDataRun(
                run_id=UUID(int=number),
                provider="fixture",
                request=RealDataRunRequest(mode="post_close", requested_at=now),
                status=RealDataRunStatus.READY_FOR_ATTRIBUTION,
            )
        )
    repo.insert(
        RealDataRun(
            provider="fixture",
            request=RealDataRunRequest(mode="post_close"),
            status=RealDataRunStatus.FETCHING_MARKET,
        )
    )
    items, total = repo.list_comparison_runs(
        provider="fixture", mode="post_close", offset=50, limit=20
    )
    assert total == 55
    assert [item.run_id for item in items] == [UUID(int=n) for n in range(5, 0, -1)]
    assert repo.list_comparison_runs(offset=100) == ([], 55)


def test_all_terminal_states_and_optional_filters(tmp_path: Path) -> None:
    repo = SQLiteRealDataRunRepository(SQLiteDatabase(tmp_path / "states.sqlite"))
    for state in RealDataRunStatus:
        repo.insert(
            RealDataRun(
                provider="fixture", request=RealDataRunRequest(mode="intraday"), status=state
            )
        )
    repo.insert(
        RealDataRun(
            provider="live",
            request=RealDataRunRequest(mode="post_close"),
            status=RealDataRunStatus.FAILED,
        )
    )
    items, total = repo.list_comparison_runs(provider="fixture", mode="intraday")
    assert total == 6
    assert {item.status for item in items} == {
        RealDataRunStatus.READY_FOR_ATTRIBUTION,
        RealDataRunStatus.DEGRADED,
        RealDataRunStatus.BLOCKED,
        RealDataRunStatus.FAILED,
        RealDataRunStatus.CANCELLED,
        RealDataRunStatus.INTERRUPTED,
    }
    assert repo.list_comparison_runs(provider="live")[1] == 1
    assert repo.list_comparison_runs(mode="post_close")[1] == 1
    assert repo.list_comparison_runs(provider="live", mode="intraday") == ([], 0)


@pytest.mark.parametrize("offset,limit", [(-1, 20), (0, 0), (0, 101)])
def test_invalid_pagination_rejected(tmp_path: Path, offset: int, limit: int) -> None:
    repo = SQLiteRealDataRunRepository(SQLiteDatabase(tmp_path / "range.sqlite"))
    with pytest.raises(ValueError):
        repo.list_comparison_runs(offset=offset, limit=limit)
