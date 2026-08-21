import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sector_pulse.storage.phase1b_runs_repository import Phase1BRunRow
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.postgres_phase1b_runs_repository import PostgresPhase1BRunsRepository


@pytest.mark.asyncio
async def test_postgres_phase1b_runs_round_trip() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")
    database = PostgresDatabase(url)
    await database.initialize()
    item = Phase1BRunRow(
        run_id=uuid4(), requested_at=datetime.now(UTC), provider="postgres-test",
        status="RUNNING", input_json={"test": True},
    )
    repository = PostgresPhase1BRunsRepository(database)
    await repository.insert(item)
    loaded = await repository.get_run(item.run_id)
    assert loaded is not None
    assert loaded.run_id == item.run_id
    assert loaded.input_json == {"test": True}
    await database.engine.dispose()
