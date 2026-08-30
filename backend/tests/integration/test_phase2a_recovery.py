from datetime import UTC, datetime, timedelta
from pathlib import Path

from sector_pulse.application.run_coordinator import RunCoordinator
from sector_pulse.application.schedule_service import ScheduleService
from sector_pulse.application.scheduler import EmbeddedScheduler
from sector_pulse.application.task_run_service import TaskRunService
from sector_pulse.domain.real_data_run import RealDataRun, RealDataRunRequest, RealDataRunStatus
from sector_pulse.domain.task import TaskRunKey, TaskRunStatus
from sector_pulse.storage.real_data_run_repository import SQLiteRealDataRunRepository
from sector_pulse.storage.sqlite import SQLiteDatabase
from sector_pulse.storage.task_repository import SQLiteTaskRepository


class NoopExecutor:
    async def execute(self, run_id, provider: str, worker_id: str) -> None:
        return None


class NoopBridge:
    def start(self, task_run_id, schedule):
        raise AssertionError("recovery must not start new work")


def _coordinator(database: SQLiteDatabase) -> RunCoordinator:
    tasks = SQLiteTaskRepository(database)
    return RunCoordinator(
        tasks,
        TaskRunService(tasks),
        ScheduleService(tasks),
        NoopBridge(),
        SQLiteRealDataRunRepository(database),
    )


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


def test_startup_marks_unowned_active_runs_interrupted(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "real-recovery.db")
    repository = SQLiteRealDataRunRepository(database)
    run = RealDataRun(
        provider="fixture",
        request=RealDataRunRequest(mode="post_close"),
        status=RealDataRunStatus.FETCHING_NEWS,
    )
    repository.insert(run)

    assert _coordinator(database).recover_startup(datetime.now(UTC)) == 1
    stored = repository.get_run(run.run_id)
    assert stored is not None
    assert stored.status is RealDataRunStatus.INTERRUPTED


def test_startup_marks_running_task_interrupted(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "task-recovery.db")
    repository = SQLiteTaskRepository(database)
    run_id = repository.create_or_get_run(
        TaskRunKey(input_fingerprint="startup-recovery"), "fixture", {}
    )
    now = datetime.now(UTC)
    assert repository.claim_run(
        run_id, "dead-worker", now + timedelta(minutes=5), now=now
    )

    assert _coordinator(database).recover_startup(now + timedelta(seconds=1)) == 1
    detail = repository.get_task_detail(run_id)
    assert detail is not None
    assert detail["status"] == TaskRunStatus.INTERRUPTED.value
