import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sector_pulse.domain.prompt_golden import PromptGoldenCase
from sector_pulse.storage.postgres.database import PostgresDatabase
from sector_pulse.storage.postgres.prompt_golden_repository import PostgresPromptGoldenRepository


def test_postgres_prompt_golden_round_trip() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")
    database = PostgresDatabase(url)
    database.initialize()
    item = PromptGoldenCase(
        prompt_id="postgres-test", prompt_version=1, input_hash=f"hash-{uuid4()}",
        expected_schema="schema", result="result", created_at=datetime.now(UTC),
    )
    repository = PostgresPromptGoldenRepository(database)
    repository.save(item)
    loaded = repository.list()
    assert any(case.case_id == item.case_id for case in loaded)
    database.close()
