from datetime import UTC, datetime
from pathlib import Path

import pytest
from sector_pulse.application.schedule_service import ScheduleCreate, ScheduleService
from sector_pulse.application.scheduler import EmbeddedScheduler
from sector_pulse.storage.sqlite import SQLiteDatabase
from sector_pulse.storage.task_repository import SQLiteTaskRepository


class FakeExecutor:
    async def execute(self, run_id, provider, worker_id):
        return None


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
    return EmbeddedScheduler(repository, schedules, FakeExecutor()), repository, schedule


@pytest.mark.asyncio
async def test_scheduler_duplicate_poll_creates_one_run(scheduler):
    embedded, repository, _ = scheduler

    await embedded.poll_once(datetime(2026, 8, 19, 8, 0, tzinfo=UTC))
    await embedded.poll_once(datetime(2026, 8, 19, 8, 0, tzinfo=UTC))

    assert repository.count_runs() == 1
