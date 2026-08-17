from datetime import UTC, datetime
from uuid import uuid4

from sector_pulse.storage.phase1b_runs_repository import (
    Phase1BRunRow,
    SQLitePhase1BRunsRepository,
)
from sector_pulse.storage.sqlite import SQLiteDatabase


def test_insert_list_and_update(tmp_path) -> None:
    db = SQLiteDatabase(tmp_path / "test.db")
    repo = SQLitePhase1BRunsRepository(db)
    run_id = uuid4()
    repo.insert(
        Phase1BRunRow(
            run_id=run_id,
            requested_at=datetime(2026, 8, 14, 12, tzinfo=UTC),
            provider="fixture",
            status="RUNNING",
        )
    )
    draft_id = uuid4()
    repo.update_status(
        run_id,
        status="READY_FOR_HUMAN_REVIEW",
        elapsed_ms=500,
        total_cost_cny="0",
        draft_id=draft_id,
        finished_at=datetime(2026, 8, 14, 12, 1, tzinfo=UTC),
    )
    run = repo.get_run(run_id)
    assert run is not None
    assert run.status == "READY_FOR_HUMAN_REVIEW"
    assert run.elapsed_ms == 500
    assert run.draft_id == draft_id
    listed = repo.list_runs()
    assert len(listed) == 1
    assert listed[0].run_id == run_id