import os
from uuid import uuid4

import pytest
from sector_pulse.storage.postgres.database import PostgresDatabase
from sector_pulse.storage.postgres.news_retrieval_repository import PostgresNewsRetrievalRepository


@pytest.mark.postgres
def test_postgres_news_retrieval_empty_links() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")
    database = PostgresDatabase(url)
    database.initialize()
    repository = PostgresNewsRetrievalRepository(database)
    assert repository.list_links(uuid4()) == ()
    assert repository.list_query_documents(uuid4()) == ()
    database.close()
