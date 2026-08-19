from datetime import UTC, datetime, timedelta

import pytest
from sector_pulse.domain.task import TaskRunKey, TaskRunStatus, TaskStage
from sector_pulse.storage.sqlite import SQLiteDatabase
from sector_pulse.storage.task_repository import SQLiteTaskRepository


def test_phase2a_migration_creates_task_tables(tmp_path):
    db = SQLiteDatabase(tmp_path / "phase2a.db")

    db.initialize()

    with db.connection() as connection:
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert {
        "schedules",
        "task_runs",
        "run_stage_attempts",
        "run_checkpoints",
        "task_events",
    } <= names


@pytest.fixture
def repository(tmp_path):
    database = SQLiteDatabase(tmp_path / "phase2a.db")
    database.initialize()
    return SQLiteTaskRepository(database)


def test_duplicate_schedule_trigger_returns_same_run_id(repository):
    key = TaskRunKey(
        input_fingerprint="fingerprint-1",
    )

    first = repository.create_or_get_run(key, "live", {"mode": "post_close"})
    second = repository.create_or_get_run(key, "live", {"mode": "post_close"})

    assert first == second


def test_claim_run_requires_expired_or_same_worker_lease(repository):
    run_id = repository.create_or_get_run(
        TaskRunKey(input_fingerprint="manual-1"), "fixture", {"mode": "intraday"}
    )
    now = datetime.now(UTC)
    lease_until = now + timedelta(minutes=5)

    assert repository.claim_run(run_id, "worker-1", lease_until, now=now)
    assert not repository.claim_run(run_id, "worker-2", lease_until, now=now)
    assert repository.claim_run(run_id, "worker-1", lease_until, now=now)
    expired_now = now + timedelta(minutes=6)
    assert repository.claim_run(
        run_id, "worker-2", expired_now + timedelta(minutes=5), now=expired_now
    )


def test_checkpoint_is_immutable(repository):
    run_id = repository.create_or_get_run(
        TaskRunKey(input_fingerprint="manual-2"), "fixture", {"mode": "intraday"}
    )

    checkpoint = repository.save_checkpoint(
        run_id,
        TaskStage.FETCHING_MARKET,
        "market-input",
        "phase2a-v1",
        {"count": 1},
    )

    assert repository.get_latest_valid_checkpoint(
        run_id, TaskStage.FETCHING_MARKET, "market-input", "phase2a-v1"
    ) == checkpoint
    with pytest.raises(ValueError, match="checkpoint already exists"):
        repository.save_checkpoint(
            run_id,
            TaskStage.FETCHING_MARKET,
            "market-input",
            "phase2a-v1",
            {"count": 2},
        )


def test_transition_requires_expected_status_and_records_event(repository):
    run_id = repository.create_or_get_run(
        TaskRunKey(input_fingerprint="manual-3"), "fixture", {"mode": "intraday"}
    )

    assert repository.transition(
        run_id,
        TaskRunStatus.QUEUED,
        TaskRunStatus.RUNNING,
        source="manual",
        summary="claimed",
    )
    assert not repository.transition(
        run_id,
        TaskRunStatus.QUEUED,
        TaskRunStatus.FAILED,
        source="manual",
        summary="stale transition",
    )
    assert repository.list_events(run_id)[0].new_status == TaskRunStatus.RUNNING
