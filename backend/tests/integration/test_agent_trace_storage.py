import os
from uuid import uuid4

import pytest
from sector_pulse.storage.postgres.database import PostgresDatabase
from sector_pulse.storage.postgres.writing.agent_execution_repository import (
    PostgresAgentExecutionRepository,
)
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.writing.agent_execution_repository import (
    SQLiteAgentExecutionRepository,
)
from sqlalchemy import text
from sqlalchemy.engine import make_url

from backend.tests.integration.test_phase1b_pipeline import contexts


@pytest.mark.parametrize("dialect", ["sqlite", "postgres"])
def test_trace_storage_is_idempotent_isolated_and_survives_reopen(tmp_path, dialect):
    run_id = uuid4()
    context = contexts()[0].model_copy(update={"run_id": run_id})
    if dialect == "postgres":
        url = os.getenv("SECTOR_PULSE_TEST_DATABASE_URL")
        if not url:
            pytest.skip("requires dedicated SECTOR_PULSE_TEST_DATABASE_URL")
        assert (make_url(url).database or "").endswith("_test"), "business database refused"
        db = PostgresDatabase(url)
        factory = PostgresAgentExecutionRepository
    else:
        db = SQLiteDatabase(tmp_path / "trace.db")
        factory = SQLiteAgentExecutionRepository
    db.initialize()
    try:
        repo = factory(db)
        repo.save(context, 1, {"type": "tool_result", "content": "中文来源"})
        repo.save(context, 1, {"type": "tool_result", "content": "duplicate must not overwrite"})
        repo.save(context, 2, {"type": "stopped", "reason": "AGENT_CANCELLED"})
        assert factory(db).list_for_run(uuid4()) == []
        rows = factory(db).list_for_run(run_id)
        assert [r["event"]["type"] for r in rows] == ["tool_result", "stopped"]
        assert rows[0]["event"]["content"] == "中文来源"
        assert rows[0]["sector_kind"] == "INDUSTRY"
        assert rows[0]["recorded_at"]
    finally:
        if dialect == "postgres":
            with db.start().begin() as connection:
                connection.execute(
                    text("DELETE FROM attribution_agent_steps WHERE run_id = :run"),
                    {"run": str(run_id)},
                )
            db.close()
