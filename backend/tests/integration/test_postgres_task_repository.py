import os
from uuid import uuid4

import pytest
from sector_pulse.domain.task import TaskRunKey
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.postgres_task_repository import PostgresTaskRepository


@pytest.mark.asyncio
async def test_postgres_task_repository_round_trip() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")
    database = PostgresDatabase(url)
    await database.initialize()
    key = TaskRunKey(
        schedule_id=None, trading_date=None, planned_slot=None,
        input_fingerprint=f"postgres-test-{uuid4()}",
    )
    repository = PostgresTaskRepository(database)
    run_id = await repository.create_or_get_run(key, "postgres-test", {})
    assert await repository.count_runs() >= 1
    detail = await repository.get_task_detail(run_id)
    assert detail is not None
    assert detail["run_id"] == str(run_id)
    await database.engine.dispose()
