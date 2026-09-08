import os

import pytest
from sector_pulse.storage.postgres.database import PostgresDatabase
from sector_pulse.storage.postgres.news_evidence_repository import PostgresNewsEvidenceRepository


@pytest.mark.postgres
def test_postgres_news_evidence_empty_query() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")
    database = PostgresDatabase(url)
    database.initialize()
    repository = PostgresNewsEvidenceRepository(database)
    assert repository.get_events(()) == ()
    database.close()
