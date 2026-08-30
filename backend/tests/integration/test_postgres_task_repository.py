import os
from uuid import uuid4

import pytest
from sector_pulse.domain.task import TaskRunKey
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.postgres_task_repository import PostgresTaskRepository


@pytest.mark.postgres
def test_postgres_task_repository_round_trip() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")
    database = PostgresDatabase(url)
    database.initialize()
    key = TaskRunKey(
        schedule_id=None, trading_date=None, planned_slot=None,
        input_fingerprint=f"postgres-test-{uuid4()}",
    )
    repository = PostgresTaskRepository(database)
    run_id = repository.create_or_get_run(key, "postgres-test", {})
    assert repository.count_runs() >= 1
    detail = repository.get_task_detail(run_id)
    assert detail is not None
    assert detail["run_id"] == str(run_id)
    database.close()
