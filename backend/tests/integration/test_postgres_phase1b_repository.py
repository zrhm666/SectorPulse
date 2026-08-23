import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sector_pulse.domain.attribution import AttributionContext
from sector_pulse.domain.market import SectorKind
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.postgres_phase1b_repository import PostgresPhase1BRepository
from sqlalchemy import text


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


@pytest.mark.asyncio
async def test_postgres_phase1b_contexts_are_upserted_by_primary_key() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")

    database = PostgresDatabase(url)
    await database.initialize()
    run_id = uuid4()
    context = AttributionContext(
        run_id=run_id,
        sector_id="concept-test",
        sector_kind=SectorKind.CONCEPT,
        cutoff_at=datetime.now(UTC),
        market_facts={},
        event_ids=(),
        eligible_event_ids=(),
        background_event_ids=(),
        excluded_event_ids=(),
        source_grades={},
        counter_evidence=(),
    )
    repository = PostgresPhase1BRepository(database)
    try:
        await repository.save_contexts((context,))
        await repository.save_contexts((context,))
        assert await repository.get_contexts(run_id) == (context,)
    finally:
        async with database.engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM attribution_contexts WHERE run_id = :run_id"),
                {"run_id": str(run_id)},
            )
        await database.close()
