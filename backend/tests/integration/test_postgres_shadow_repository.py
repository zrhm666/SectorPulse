import os
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sector_pulse.domain.shadow_acceptance import ShadowRun
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.postgres_shadow_acceptance_repository import (
    PostgresShadowAcceptanceRepository,
)


@pytest.mark.asyncio
async def test_postgres_shadow_repository_round_trip() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")
    database = PostgresDatabase(url)
    await database.initialize()
    item = ShadowRun(
        run_id=uuid4(),
        trading_date=date(2026, 8, 21),
        mode="postgres-test",
        created_at=datetime.now(UTC),
    )
    repository = PostgresShadowAcceptanceRepository(database)
    await repository.save_run(item)
    loaded = await repository.get(item.shadow_id)
    assert loaded is not None
    assert loaded.shadow_id == item.shadow_id
    await database.close()
