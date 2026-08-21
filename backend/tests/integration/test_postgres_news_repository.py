import os

import pytest
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.postgres_news_repository import PostgresNewsRepository


@pytest.mark.asyncio
async def test_postgres_news_repository_empty_reads() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")
    database = PostgresDatabase(url)
    await database.initialize()
    repository = PostgresNewsRepository(database)
    assert await repository.get_event("missing-postgres-event") is None
    assert await repository.get_events(()) == ()
    assert await repository.get_documents(()) == {}
    await database.engine.dispose()
