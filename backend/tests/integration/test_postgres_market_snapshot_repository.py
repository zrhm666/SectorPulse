import os
from uuid import uuid4

import pytest
from sector_pulse.domain.market import SectorKind
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.postgres_market_snapshot_repository import (
    PostgresMarketSnapshotRepository,
)


@pytest.mark.asyncio
async def test_postgres_market_snapshot_empty_read() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")
    database = PostgresDatabase(url)
    await database.initialize()
    repository = PostgresMarketSnapshotRepository(database)
    assert await repository.get(uuid4(), SectorKind.INDUSTRY) is None
    await database.engine.dispose()
