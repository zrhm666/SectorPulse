import os
from uuid import uuid4

import pytest
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.postgres_news_retrieval_repository import PostgresNewsRetrievalRepository


@pytest.mark.asyncio
async def test_postgres_news_retrieval_empty_links() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")
    database = PostgresDatabase(url)
    await database.initialize()
    repository = PostgresNewsRetrievalRepository(database)
    assert await repository.list_links(uuid4()) == ()
    assert await repository.list_query_documents(uuid4()) == ()
    await database.engine.dispose()
