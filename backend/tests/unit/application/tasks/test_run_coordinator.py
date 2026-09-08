from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sector_pulse.application.tasks.run_coordinator import RunCoordinator
from sector_pulse.application.tasks.schedule_service import ScheduleCreate, ScheduleService
from sector_pulse.application.tasks.task_run_service import TaskRunService
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.runs.real_data_run_repository import SQLiteRealDataRunRepository
from sector_pulse.storage.sqlite.runs.task_repository import SQLiteTaskRepository


class FakeBridge:
    def __init__(self) -> None:
        self.started: list[tuple[object, object]] = []
        self.data_run_id = uuid4()

    def start(self, task_run_id, schedule):
        self.started.append((task_run_id, schedule))
        return self.data_run_id


@pytest.fixture
def coordinator(tmp_path: Path):
    database = SQLiteDatabase(tmp_path / "coordinator.db")
    repository = SQLiteTaskRepository(database)
    schedules = ScheduleService(repository)
    schedule = schedules.create(
        ScheduleCreate(
            name="盘后",
            mode="post_close",
            timezone="Asia/Shanghai",
            local_time="16:00",
            trading_days="weekdays",
        )
    )
    bridge = FakeBridge()
    service = RunCoordinator(
        repository,
        TaskRunService(repository),
        schedules,
        bridge,
        SQLiteRealDataRunRepository(database),
    )
    return service, repository, schedule, bridge


def test_manual_start_creates_and_links_data_run_once(coordinator) -> None:
    service, repository, schedule, bridge = coordinator

    first = service.start_schedule_now(schedule.schedule_id, "manual-1")
    second = service.start_schedule_now(schedule.schedule_id, "manual-1")

    detail = repository.get_task_detail(first)
    assert first == second
    assert detail is not None
    assert detail["data_run_id"] == str(bridge.data_run_id)
    assert len(bridge.started) == 1


def test_scheduled_start_uses_persisted_due_slot(coordinator) -> None:
    service, repository, schedule, bridge = coordinator
    due = datetime(2026, 8, 19, 8, 0, tzinfo=UTC)
    schedule = schedule.model_copy(update={"next_run_at": due})

    run_id = service.start_scheduled(schedule, due)

    detail = repository.get_task_detail(run_id)
    assert detail is not None
    assert detail["data_run_id"] == str(bridge.data_run_id)
    assert len(bridge.started) == 1


def test_start_failure_marks_task_failed(coordinator) -> None:
    service, repository, schedule, bridge = coordinator
    attempted: list[object] = []

    def fail(task_run_id, _schedule):
        attempted.append(task_run_id)
        raise ValueError("secret provider detail")

    bridge.start = fail

    with pytest.raises(ValueError, match="secret provider detail"):
        service.start_schedule_now(schedule.schedule_id, "manual-failure")

    assert len(attempted) == 1
    detail = repository.get_task_detail(attempted[0])
    assert detail is not None
    assert detail["status"] == "FAILED"
    assert detail["error_code"] == "DATA_RUN_START_FAILED"
