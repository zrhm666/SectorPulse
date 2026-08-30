from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sector_pulse.application.schedule_service import ScheduleCreate, ScheduleService
from sector_pulse.application.scheduler import EmbeddedScheduler
from sector_pulse.storage.sqlite import SQLiteDatabase
from sector_pulse.storage.task_repository import SQLiteTaskRepository


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
