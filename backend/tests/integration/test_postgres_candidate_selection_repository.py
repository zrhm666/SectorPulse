import os
from datetime import UTC, datetime

import pytest
from sector_pulse.domain.candidate_selection import CandidateSelection, CandidateSelectionMethod
from sector_pulse.domain.real_data_run import RealDataRun, RealDataRunRequest
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.postgres_candidate_selection_repository import (
    PostgresCandidateSelectionRepository,
)
from sector_pulse.storage.postgres_real_data_run_repository import PostgresRealDataRunRepository


@pytest.mark.asyncio
async def test_postgres_candidate_selection_repository_matches_sqlite_contract() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")
    database = PostgresDatabase(url)
    await database.initialize()
    runs = PostgresRealDataRunRepository(database)
    run = RealDataRun(request=RealDataRunRequest(mode="post_close"), provider="fixture")
    await runs.insert(run)
    repository = PostgresCandidateSelectionRepository(database)
    first = CandidateSelection(
        run_id=run.run_id,
        version=1,
        selected_sector_ids=("881101", "881102", "309001"),
        method=CandidateSelectionMethod.DEFAULT,
        confirmed_at=datetime.now(UTC),
        data_version="a" * 64,
        edit_count=0,
    )

    await repository.append(first, expected_version=0)

    assert await repository.latest(run.run_id) == first
    assert await repository.list_versions(run.run_id) == [first]
    await database.close()
