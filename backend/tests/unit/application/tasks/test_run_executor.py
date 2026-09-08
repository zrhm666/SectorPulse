from pathlib import Path

import pytest
from sector_pulse.application.tasks.run_executor import RetryPolicy, RunExecutor, StageWork
from sector_pulse.application.tasks.task_run_service import TaskRunService
from sector_pulse.domain.task import TaskRunKey, TaskStage
from sector_pulse.storage.sqlite import SQLiteDatabase
from sector_pulse.storage.task_repository import SQLiteTaskRepository


@pytest.fixture
def repository(tmp_path: Path) -> SQLiteTaskRepository:
    database = SQLiteDatabase(tmp_path / "executor.db")
    database.initialize()
    return SQLiteTaskRepository(database)


def test_retry_policy_classifies_transient_and_integrity_failures():
    policy = RetryPolicy(max_attempts=3, backoff_seconds=2)

    transient = policy.classify(TimeoutError(), attempt_no=1)
    integrity = policy.classify(ValueError("cutoff integrity failed"), attempt_no=1)

    assert transient.retryable is True
    assert transient.delay_seconds == 2
    assert integrity.retryable is False
    assert integrity.error_code == "TASK_VALIDATION_FAILED"


@pytest.mark.asyncio
async def test_executor_skips_stage_with_valid_checkpoint(repository):
    run_id = repository.create_or_get_run(
        key=TaskRunKey(input_fingerprint="executor-input"),
        provider="fixture",
        input_json={"mode": "intraday"},
    )
    repository.save_checkpoint(
        run_id, TaskStage.FETCHING_MARKET, "market-input", "phase2a-v1", {"ok": True}
    )
    calls: list[str] = []

    async def work() -> dict[str, object]:
        calls.append("called")
        return {"ok": False}

    executor = RunExecutor(repository, implementation_version="phase2a-v1")
    result = await executor.run_stage(
        run_id,
        StageWork(TaskStage.FETCHING_MARKET, "market-input", work),
    )

    assert result.payload == {"ok": True}
    assert calls == []


def test_task_run_service_manual_idempotency(repository):
    service = TaskRunService(repository)

    first = service.create_manual({"mode": "intraday"}, "fixture", "request-1")
    second = service.create_manual({"mode": "intraday"}, "fixture", "request-1")

    assert first == second
