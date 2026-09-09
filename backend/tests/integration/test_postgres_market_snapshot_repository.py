import os
from uuid import uuid4

import pytest
from sector_pulse.domain.market.market import SectorKind
from sector_pulse.storage.postgres.database import PostgresDatabase
from sector_pulse.storage.postgres.market.market_snapshot_repository import (
    PostgresMarketSnapshotRepository,
)


@pytest.mark.postgres
def test_postgres_market_snapshot_empty_read() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")
    database = PostgresDatabase(url)
    database.initialize()
    repository = PostgresMarketSnapshotRepository(database)
    assert repository.get(uuid4(), SectorKind.INDUSTRY) is None
    database.close()
