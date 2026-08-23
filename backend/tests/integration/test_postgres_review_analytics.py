import os
from uuid import uuid4

import pytest
from sector_pulse.application.postgres_review_analytics import PostgresReviewAnalyticsQueries
from sector_pulse.storage.postgres import PostgresDatabase
from sqlalchemy import text


@pytest.mark.asyncio
async def test_postgres_review_analytics_sums_text_costs_as_numeric() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")

    run_id = str(uuid4())
    invocation_id = str(uuid4())
    database = PostgresDatabase(url)
    await database.initialize()
    try:
        async with database.engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO agent_invocations "
                    "(invocation_id, run_id, stage, provider_id, model, prompt_id, "
                    "prompt_version, input_hash, output_hash, status, prompt_tokens, "
                    "completion_tokens, total_tokens, estimated_cost_cny, error_code) "
                    "VALUES (:invocation_id, :run_id, 'writing', 'test', 'model', 'prompt', "
                    "'1', 'input', 'output', 'SUCCESS', 1, 1, 2, '1.25', NULL)"
                ),
                {"invocation_id": invocation_id, "run_id": run_id},
            )

        result = await PostgresReviewAnalyticsQueries(database).for_run(run_id)
        assert result.llm_cost_cny == 1.25
    finally:
        async with database.engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM agent_invocations WHERE run_id = :run_id"),
                {"run_id": run_id},
            )
        await database.close()
