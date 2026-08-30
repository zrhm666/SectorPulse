import os
from uuid import uuid4

import pytest
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.postgres_draft_edit_repository import PostgresDraftEditRepository


def test_postgres_draft_edit_missing_version() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")
    database = PostgresDatabase(url)
    database.initialize()
    repository = PostgresDraftEditRepository(database)
    with pytest.raises(KeyError):
        repository.get_version(uuid4(), 1)
    database.close()
