from datetime import UTC, datetime
from pathlib import Path

import pytest
from sector_pulse.application.tasks.schedule_service import ScheduleCreate, ScheduleService
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.task_repository import SQLiteTaskRepository


@pytest.fixture
def schedule_service(tmp_path: Path) -> ScheduleService:
    database = SQLiteDatabase(tmp_path / "schedule.db")
    database.initialize()
    return ScheduleService(SQLiteTaskRepository(database))


def test_next_after_converts_plan_timezone_to_utc(schedule_service):
    schedule = schedule_service.create(
        ScheduleCreate(
            name="盘后",
            mode="post_close",
            timezone="Asia/Shanghai",
            local_time="16:00",
            trading_days="weekdays",
            enabled=True,
        )
    )

    due = schedule_service.next_after(
        schedule, datetime(2026, 8, 19, 7, 0, tzinfo=UTC)
    )

    assert due == datetime(2026, 8, 19, 8, 0, tzinfo=UTC)


def test_next_after_is_strictly_later_than_consumed_slot(schedule_service) -> None:
    schedule = schedule_service.create(
        ScheduleCreate(
            name="盘后",
            mode="post_close",
            timezone="Asia/Shanghai",
            local_time="16:00",
            trading_days="weekdays",
            enabled=True,
        )
    )

    due = schedule_service.next_after(
        schedule, datetime(2026, 8, 19, 8, 0, tzinfo=UTC)
    )

    assert due == datetime(2026, 8, 20, 8, 0, tzinfo=UTC)
