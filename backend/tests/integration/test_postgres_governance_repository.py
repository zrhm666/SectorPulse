import os
from uuid import uuid4

import pytest
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.postgres_governance_repository import PostgresGovernanceRepository


def test_postgres_governance_empty_decisions() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")
    database = PostgresDatabase(url)
    database.initialize()
    repository = PostgresGovernanceRepository(database)
    assert repository.list_evidence_decisions(uuid4()) == ()
    database.close()
