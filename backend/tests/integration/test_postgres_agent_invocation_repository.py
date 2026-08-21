import os
from uuid import uuid4

import pytest
from sector_pulse.domain.llm import AgentInvocation, LLMStatus, MoneyCny, TokenUsage
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.postgres_agent_invocation_repository import (
    PostgresAgentInvocationRepository,
)


@pytest.mark.asyncio
async def test_postgres_agent_invocation_round_trip() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")
    database = PostgresDatabase(url)
    await database.initialize()
    run_id = uuid4()
    item = AgentInvocation(
        invocation_id=uuid4(), run_id=run_id, stage="postgres-test",
        provider_id="test", model="test", prompt_id="test", prompt_version="1",
        input_hash="in", output_hash="out", status=LLMStatus.SUCCESS,
        usage=TokenUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        estimated_cost_cny=MoneyCny(amount="0.01"),
    )
    repository = PostgresAgentInvocationRepository(database)
    await repository.save([item])
    loaded = await repository.list_for_run(run_id)
    assert len(loaded) == 1
    assert loaded[0].invocation_id == item.invocation_id
    await database.engine.dispose()
