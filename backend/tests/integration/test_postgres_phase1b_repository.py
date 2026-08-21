import os
from uuid import uuid4

import pytest
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.postgres_phase1b_repository import PostgresPhase1BRepository


@pytest.mark.asyncio
async def test_postgres_phase1b_repository_empty_reads() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")
    database = PostgresDatabase(url)
    await database.initialize()
    repository = PostgresPhase1BRepository(database)
    run_id = uuid4()
    assert await repository.get_contexts(run_id) == ()
    assert await repository.get_gates(run_id) == ()
    assert await repository.get_cards(run_id) == ()
    assert await repository.get_outline(run_id) is None
    assert await repository.get_drafts(run_id) == ()
    assert await repository.get_review(run_id) is None
    await database.engine.dispose()
