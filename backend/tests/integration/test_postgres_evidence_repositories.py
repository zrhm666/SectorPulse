import os

import pytest
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.postgres_news_evidence_repository import PostgresNewsEvidenceRepository


@pytest.mark.asyncio
async def test_postgres_news_evidence_empty_query() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")
    database = PostgresDatabase(url)
    await database.initialize()
    repository = PostgresNewsEvidenceRepository(database)
    assert await repository.get_events(()) == ()
    await database.engine.dispose()
