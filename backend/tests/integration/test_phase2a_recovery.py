from datetime import UTC, datetime, timedelta
from pathlib import Path

from sector_pulse.application.schedule_service import ScheduleService
from sector_pulse.application.scheduler import EmbeddedScheduler
from sector_pulse.domain.task import TaskRunKey, TaskRunStatus
from sector_pulse.storage.sqlite import SQLiteDatabase
from sector_pulse.storage.task_repository import SQLiteTaskRepository


class NoopExecutor:
    async def execute(self, run_id, provider: str, worker_id: str) -> None:
        return None


def test_restart_recovers_expired_worker_lease(tmp_path: Path):
    database = SQLiteDatabase(tmp_path / "recovery.db")
    repository = SQLiteTaskRepository(database)
    run_id = repository.create_or_get_run(
        TaskRunKey(input_fingerprint="recovery-input"), "fixture", {"mode": "intraday"}
    )
    now = datetime.now(UTC)
    assert repository.claim_run(
        run_id, "old-worker", now - timedelta(seconds=1), now=now - timedelta(minutes=1)
    )

    scheduler = EmbeddedScheduler(repository, ScheduleService(repository), NoopExecutor())
    recovered = scheduler.recover(now=now)

    assert recovered == 1
    assert repository.get_task_detail(run_id)["status"] == TaskRunStatus.RETRY_WAITING.value
