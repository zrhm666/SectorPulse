import os
from datetime import UTC, datetime

import pytest
from sector_pulse.domain.real_data_run import RealDataRun, RealDataRunRequest
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.postgres_real_data_run_repository import PostgresRealDataRunRepository


@pytest.mark.asyncio
async def test_postgres_real_data_run_round_trip() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")
    database = PostgresDatabase(url)
    await database.initialize()
    run = RealDataRun(request=RealDataRunRequest(mode="intraday", requested_at=datetime.now(UTC)))
    repository = PostgresRealDataRunRepository(database)
    await repository.insert(run)
    loaded = await repository.get_run(run.run_id)
    assert loaded is not None
    assert loaded.run_id == run.run_id
    assert loaded.request.mode == "intraday"
    await database.engine.dispose()
