import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sector_pulse.application.tasks.schedule_service import ScheduleCreate, ScheduleService
from sector_pulse.application.tasks.scheduler import EmbeddedScheduler
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.runs.task_repository import SQLiteTaskRepository


class FakeExecutor:
    def __init__(self) -> None:
        self.executed = []

    async def execute(self, run_id, provider, worker_id):
        self.executed.append(run_id)


@pytest.fixture
def scheduler(tmp_path: Path):
    database = SQLiteDatabase(tmp_path / "scheduler.db")
    database.initialize()
    repository = SQLiteTaskRepository(database)
    schedules = ScheduleService(repository)
    schedule = schedules.create(
        ScheduleCreate(
            name="盘后",
            mode="post_close",
            timezone="Asia/Shanghai",
            local_time="16:00",
            trading_days="weekdays",
            enabled=True,
        )
    )
    repository.update_schedule_next_run(
        schedule.schedule_id, datetime(2026, 8, 19, 8, 0, tzinfo=UTC)
    )
    executor = FakeExecutor()
    return EmbeddedScheduler(repository, schedules, executor), repository, schedule, executor


@pytest.mark.asyncio
async def test_scheduler_duplicate_poll_creates_one_run(scheduler):
    embedded, repository, _, executor = scheduler

    await embedded.poll_once(datetime(2026, 8, 19, 8, 0, tzinfo=UTC))
    await embedded.poll_once(datetime(2026, 8, 19, 8, 0, 1, tzinfo=UTC))

    assert repository.count_runs() == 1
    assert len(executor.executed) == 1


@pytest.mark.parametrize("delay_seconds", [1, 10, 30])
@pytest.mark.asyncio
async def test_scheduler_consumes_persisted_plan_after_poll_delay(
    scheduler, delay_seconds: int
) -> None:
    embedded, repository, schedule, executor = scheduler
    polled_at = datetime(2026, 8, 19, 8, 0, tzinfo=UTC) + timedelta(
        seconds=delay_seconds
    )

    await embedded.poll_once(polled_at)
    await embedded.poll_once(polled_at + timedelta(seconds=1))

    stored = repository.get_schedule(schedule.schedule_id)
    assert stored is not None
    assert repository.count_runs() == 1
    assert len(executor.executed) == 1
    assert stored["last_triggered_at"] == polled_at.isoformat()
    assert stored["next_run_at"] == datetime(2026, 8, 20, 8, 0, tzinfo=UTC).isoformat()


@pytest.mark.asyncio
async def test_one_broken_schedule_does_not_stop_other_due_schedules(
    tmp_path: Path,
) -> None:
    database = SQLiteDatabase(tmp_path / "isolated-scheduler.db")
    repository = SQLiteTaskRepository(database)
    schedules = ScheduleService(repository)
    due = datetime(2026, 8, 19, 8, 0, tzinfo=UTC)
    for name in ("broken", "healthy"):
        schedule = schedules.create(
            ScheduleCreate(
                name=name,
                mode="post_close",
                timezone="Asia/Shanghai",
                local_time="16:00",
                enabled=True,
            )
        )
        repository.update_schedule_next_run(schedule.schedule_id, due)

    class FailFirstExecutor(FakeExecutor):
        async def execute(self, run_id, provider, worker_id):
            self.executed.append(run_id)
            if len(self.executed) == 1:
                raise RuntimeError("provider secret must not persist")

    executor = FailFirstExecutor()
    scheduler = EmbeddedScheduler(repository, schedules, executor)

    await scheduler.poll_once(due)

    assert len(executor.executed) == 2
    failed = repository.get_task_detail(executor.executed[0])
    assert failed is not None
    assert failed["status"] == "FAILED"
    assert failed["error_code"] == "SCHEDULE_EXECUTION_FAILED"


@pytest.mark.asyncio
async def test_disabled_schedule_dispatch_still_advances_manual_work(tmp_path):
    database = SQLiteDatabase(tmp_path / "manual-maintenance.db")
    repository = SQLiteTaskRepository(database)
    advanced = asyncio.Event()

    class Bridge:
        def advance(self):
            advanced.set()
            return 1

    embedded = EmbeddedScheduler(
        repository, ScheduleService(repository), FakeExecutor(),
        bridge=Bridge(), dispatch_enabled=False,
    )

    async def forbidden_poll(*args, **kwargs):
        raise AssertionError("disabled schedules must not be dispatched")

    embedded.poll_once = forbidden_poll
    embedded.start()
    try:
        await asyncio.wait_for(advanced.wait(), timeout=1)
    finally:
        await embedded.stop()


@pytest.mark.asyncio
async def test_scheduler_recovers_after_maintenance_failure(scheduler, caplog):
    embedded, _, _, _ = scheduler
    recovered = asyncio.Event()
    failed = asyncio.Event()
    embedded._poll_seconds = 0
    embedded._dispatch_enabled = False

    class Bridge:
        def advance(self):
            if not failed.is_set():
                failed.set()
                raise RuntimeError("private provider credentials")
            recovered.set()
            return 1

    embedded._bridge = Bridge()
    embedded.start()
    try:
        await asyncio.wait_for(failed.wait(), timeout=1)
        await asyncio.wait_for(recovered.wait(), timeout=1)
        assert embedded.is_running
        assert embedded.is_healthy
        assert "private provider credentials" not in caplog.text
    finally:
        await embedded.stop()
    assert not embedded.is_running


@pytest.mark.asyncio
async def test_dispatch_failure_still_advances_manual_work_and_reports_unhealthy(scheduler):
    embedded, _, _, _ = scheduler
    advanced = asyncio.Event()

    async def broken_poll(*args, **kwargs):
        raise RuntimeError("temporary database outage")

    class Bridge:
        def advance(self):
            advanced.set()
            return 1

    embedded.poll_once = broken_poll
    embedded._bridge = Bridge()
    embedded.start()
    try:
        await asyncio.wait_for(advanced.wait(), timeout=1)
        assert embedded.is_running
        assert not embedded.is_healthy
    finally:
        await embedded.stop()


@pytest.mark.asyncio
async def test_stop_collects_an_already_failed_background_task(scheduler):
    embedded, _, _, _ = scheduler

    async def failed_loop():
        raise RuntimeError("failed before shutdown")

    embedded._task = asyncio.create_task(failed_loop())
    await asyncio.sleep(0)
    await embedded.stop()
    assert not embedded.is_running
