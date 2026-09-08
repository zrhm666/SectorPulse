import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sector_pulse.storage.postgres.database import PostgresDatabase
from sector_pulse.storage.postgres.phase1b_runs_repository import PostgresPhase1BRunsRepository
from sector_pulse.storage.sqlite.phase1b_runs_repository import Phase1BRunRow
from sqlalchemy import text


def test_postgres_phase1b_runs_round_trip() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")
    database = PostgresDatabase(url)
    database.initialize()
    item = Phase1BRunRow(
        run_id=uuid4(), requested_at=datetime.now(UTC), provider="postgres-test",
        status="RUNNING", input_json={"test": True}, retry_of_run_id=uuid4(),
    )
    repository = PostgresPhase1BRunsRepository(database)
    repository.insert(item)
    loaded = repository.get_run(item.run_id)
    assert loaded is not None
    assert loaded.run_id == item.run_id
    assert loaded.input_json == {"test": True}
    assert loaded.retry_of_run_id == item.retry_of_run_id
    assert any(run.run_id == item.run_id for run in repository.list_runs())
    database.close()


def test_postgres_phase1b_runs_can_update_failure_status() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")
    database = PostgresDatabase(url)
    database.initialize()
    item = Phase1BRunRow(
        run_id=uuid4(), requested_at=datetime.now(UTC), provider="postgres-test",
        status="RUNNING", input_json={"test": True},
    )
    repository = PostgresPhase1BRunsRepository(database)
    try:
        repository.insert(item)
        finished_at = datetime.now(UTC)
        repository.update_status(
            item.run_id,
            status="FAILED",
            error_message="database write failed",
            finished_at=finished_at,
        )
        updated = repository.get_run(item.run_id)
        assert updated is not None
        assert updated.status == "FAILED"
        assert updated.error_message == "database write failed"
        assert updated.finished_at == finished_at
    finally:
        with database.start().begin() as connection:
            connection.execute(
                text("DELETE FROM phase1b_runs WHERE run_id = :run_id"),
                {"run_id": str(item.run_id)},
            )
        database.close()


def test_postgres_content_recovery_preserves_snapshot() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")
    database = PostgresDatabase(url)
    database.initialize()
    repository = PostgresPhase1BRunsRepository(database)
    item = Phase1BRunRow(
        run_id=uuid4(), requested_at=datetime.now(UTC), provider="postgres-test",
        status="RUNNING", input_json={"recovery": True},
    )
    try:
        repository.insert(item)
        now = datetime.now(UTC)
        assert repository.mark_interrupted(now) >= 1
        updated = repository.get_run(item.run_id)
        assert updated is not None
        assert updated.status == "INTERRUPTED"
        assert updated.finished_at == now
        assert updated.input_json == {"recovery": True}
    finally:
        with database.start().begin() as connection:
            connection.execute(
                text("DELETE FROM phase1b_runs WHERE run_id = :run_id"),
                {"run_id": str(item.run_id)},
            )
        database.close()
