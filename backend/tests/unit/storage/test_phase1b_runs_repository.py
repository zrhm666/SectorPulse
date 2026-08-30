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


def test_recovery_preserves_content_artifacts_and_only_interrupts_running(tmp_path):
    repo = SQLitePhase1BRunsRepository(SQLiteDatabase(tmp_path / "recover-content.db"))
    now = datetime.now(UTC)
    running_id, complete_id, draft_id = uuid4(), uuid4(), uuid4()
    repo.insert(Phase1BRunRow(
        run_id=running_id, requested_at=now, provider="fixture", status="RUNNING",
        input_json={"retained": True}, draft_id=draft_id, elapsed_ms=123,
    ))
    repo.insert(Phase1BRunRow(
        run_id=complete_id, requested_at=now, provider="fixture",
        status="READY_FOR_HUMAN_REVIEW",
    ))

    assert repo.mark_interrupted(now) == 1
    assert repo.mark_interrupted(now) == 0
    recovered = repo.get_run(running_id)
    assert recovered.status == "INTERRUPTED"
    assert recovered.finished_at == now
    assert recovered.input_json == {"retained": True}
    assert recovered.draft_id == draft_id
    assert recovered.elapsed_ms == 123
    assert repo.get_run(complete_id).status == "READY_FOR_HUMAN_REVIEW"
