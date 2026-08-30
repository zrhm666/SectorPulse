import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sector_pulse.storage.phase1b_runs_repository import Phase1BRunRow
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.postgres_operations_query import PostgresOperationsQuery
from sector_pulse.storage.postgres_phase1b_runs_repository import (
    PostgresPhase1BRunsRepository,
)
from sqlalchemy import text


@pytest.mark.postgres
def test_postgres_operations_query_returns_the_normalized_contract() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")
    database = PostgresDatabase(url)
    database.initialize()
    run_id = uuid4()
    requested_at = datetime.now(UTC)
    repository = PostgresPhase1BRunsRepository(database)
    try:
        repository.insert(
            Phase1BRunRow(
                run_id=run_id,
                requested_at=requested_at,
                provider="postgres-test",
                status="RUNNING",
            )
        )

        records = PostgresOperationsQuery(database).list_records(
            since=requested_at - timedelta(minutes=1), limit=1
        )

        assert len(records) == 1
        assert records[0].run_id == str(run_id)
        assert records[0].kind == "content"
        assert records[0].mode == "内容生成"
        assert records[0].provider == "postgres-test"
        assert records[0].candidate_count == 0
    finally:
        with database.start().begin() as connection:
            connection.execute(
                text("DELETE FROM phase1b_runs WHERE run_id = :run_id"),
                {"run_id": str(run_id)},
            )
        database.close()
