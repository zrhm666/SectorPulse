from datetime import UTC, datetime

import pytest
from sector_pulse.domain.real_data_run import RealDataRun, RealDataRunRequest, RealDataRunStatus
from sector_pulse.storage.postgres_real_data_run_repository import PostgresRealDataRunRepository

from backend.tests.comparison_support import (
    comparison_postgres as comparison_postgres_fixture,  # noqa: F401
)

pytestmark = pytest.mark.postgres


def test_postgres_history_pages_and_terminal_filters(comparison_postgres) -> None:
    repo = PostgresRealDataRunRepository(comparison_postgres)
    before = repo.list_comparison_runs(provider="fixture", mode="post_close")[1]
    now = datetime.now(UTC)
    runs = [
        RealDataRun(
            provider="fixture",
            request=RealDataRunRequest(mode="post_close", requested_at=now),
            status=RealDataRunStatus.READY_FOR_ATTRIBUTION,
        )
        for _ in range(55)
    ]
    for run in runs:
        repo.insert(run)
    active = RealDataRun(
        provider="fixture",
        request=RealDataRunRequest(mode="post_close"),
        status=RealDataRunStatus.FETCHING_NEWS,
    )
    repo.insert(active)
    _, total = repo.list_comparison_runs(provider="fixture", mode="post_close")
    assert total == before + 55
    seen = []
    for offset in range(0, total, 20):
        items, reported_total = repo.list_comparison_runs(
            provider="fixture", mode="post_close", offset=offset, limit=20
        )
        assert reported_total == total
        seen.extend(item.run_id for item in items)
    own = {run.run_id for run in runs}
    assert [item for item in seen if item in own] == sorted(own, reverse=True)
    assert len(seen) == len(set(seen))
    assert active.run_id not in seen
    assert repo.list_comparison_runs(offset=total + 100_000)[0] == []


@pytest.mark.parametrize("offset,limit", [(-1, 20), (0, 0), (0, 101)])
def test_postgres_invalid_pagination(comparison_postgres, offset, limit) -> None:
    repo = PostgresRealDataRunRepository(comparison_postgres)
    with pytest.raises(ValueError):
        repo.list_comparison_runs(offset=offset, limit=limit)
