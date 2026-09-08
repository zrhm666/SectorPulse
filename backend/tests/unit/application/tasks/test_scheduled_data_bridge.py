from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sector_pulse.application.tasks.schedule_service import ScheduleCreate, ScheduleService
from sector_pulse.application.tasks.scheduled_data_bridge import ScheduledDataRunBridge
from sector_pulse.domain.real_data_run import RealDataRun, RealDataRunRequest, RealDataRunStatus
from sector_pulse.domain.task import TaskRunKey, TaskRunStatus
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.phase1b_runs_repository import (
    Phase1BRunRow,
    SQLitePhase1BRunsRepository,
)
from sector_pulse.storage.sqlite.real_data_run_repository import SQLiteRealDataRunRepository
from sector_pulse.storage.sqlite.task_repository import SQLiteTaskRepository


class FakeDataRuns:
    def __init__(self):
        self.requests = []
        self.run_id = uuid4()

    def create(self, request, provider):
        self.requests.append((request, provider))
        return self.run_id


class FakeWriting:
    def __init__(self):
        self.generated = []

    def generate(self, run_id, sector_ids=None):
        self.generated.append((run_id, sector_ids))
        return run_id


class FakeSelections:
    def __init__(self):
        self.confirmed = []

    def confirm_default(self, run_id):
        self.confirmed.append(run_id)
        return type("Selection", (), {"selected_sector_ids": ("a", "b", "c")})()


def test_scheduled_bridge_creates_real_data_run_for_coordinator(tmp_path: Path):
    database = SQLiteDatabase(tmp_path / "bridge.db")
    tasks = SQLiteTaskRepository(database)
    real_runs = SQLiteRealDataRunRepository(database)
    task_run_id = tasks.create_or_get_run(TaskRunKey(input_fingerprint="bridge"), "live", {})
    schedules = ScheduleService(tasks)
    schedule = schedules.create(
        ScheduleCreate(
            name="盘后",
            mode="post_close",
            timezone="Asia/Shanghai",
            local_time="16:00",
            trading_days="weekdays",
        )
    )
    data_runs = FakeDataRuns()
    bridge = ScheduledDataRunBridge(tasks, real_runs, data_runs, FakeWriting())

    result = bridge.start(task_run_id, schedule)

    assert result == data_runs.run_id
    assert tasks.list_linked_runs() == []


def test_scheduled_bridge_confirms_default_selection_before_writing(tmp_path: Path):
    database = SQLiteDatabase(tmp_path / "advance.db")
    tasks = SQLiteTaskRepository(database)
    real_runs = SQLiteRealDataRunRepository(database)
    task_run_id = tasks.create_or_get_run(TaskRunKey(input_fingerprint="advance"), "live", {})
    run = RealDataRun(
        request=RealDataRunRequest(mode="post_close"),
        provider="fixture",
        status=RealDataRunStatus.READY_FOR_ATTRIBUTION,
    )
    real_runs.insert(run)
    tasks.link_data_run(task_run_id, run.run_id)
    selections = FakeSelections()
    writing = FakeWriting()
    bridge = ScheduledDataRunBridge(
        tasks,
        real_runs,
        FakeDataRuns(),
        writing,
        selections,
    )

    assert bridge.advance() == 1
    assert bridge.advance() == 0
    assert selections.confirmed == [run.run_id]
    assert writing.generated == [(run.run_id, ("a", "b", "c"))]


@pytest.mark.parametrize("data_status,target", [
    (RealDataRunStatus.FAILED, "FAILED"),
    (RealDataRunStatus.BLOCKED, "FAILED"),
    (RealDataRunStatus.CANCELLED, "CANCELLED"),
    (RealDataRunStatus.INTERRUPTED, "INTERRUPTED"),
    (RealDataRunStatus.DEGRADED, "DEGRADED"),
])
def test_bridge_reconciles_terminal_data_run(tmp_path, data_status, target):
    database = SQLiteDatabase(tmp_path / "terminal-data.db")
    tasks = SQLiteTaskRepository(database)
    real_runs = SQLiteRealDataRunRepository(database)
    task_id = tasks.create_or_get_run(TaskRunKey(input_fingerprint="terminal"), "live", {})
    run = RealDataRun(request=RealDataRunRequest(mode="post_close"), status=data_status)
    real_runs.insert(run)
    tasks.link_data_run(task_id, run.run_id)
    writing = FakeWriting()
    bridge = ScheduledDataRunBridge(tasks, real_runs, FakeDataRuns(), writing)

    assert bridge.advance() == 0
    assert tasks.get_task_detail(task_id)["status"] == target
    assert tasks.get_task_detail(task_id)["finished_at"] is not None
    assert writing.generated == []


@pytest.mark.parametrize("content_status,target", [
    ("READY_FOR_HUMAN_REVIEW", "READY_FOR_HUMAN_REVIEW"),
    ("UNREVIEWED", "DEGRADED"),
    ("REVISE_REQUIRED", "DEGRADED"),
    ("FAILED", "FAILED"),
    ("DRAFT_GENERATION_FAILED", "FAILED"),
    ("CANCELLED", "CANCELLED"),
])
def test_bridge_reconciles_terminal_content_once(tmp_path, content_status, target):
    database = SQLiteDatabase(tmp_path / "terminal-content.db")
    tasks = SQLiteTaskRepository(database)
    real_runs = SQLiteRealDataRunRepository(database)
    content_runs = SQLitePhase1BRunsRepository(database)
    task_id = tasks.create_or_get_run(TaskRunKey(input_fingerprint="content"), "live", {})
    run = RealDataRun(
        request=RealDataRunRequest(mode="post_close"),
        status=RealDataRunStatus.READY_FOR_ATTRIBUTION,
    )
    real_runs.insert(run)
    tasks.link_data_run(task_id, run.run_id)
    tasks.transition(task_id, TaskRunStatus.QUEUED, TaskRunStatus.RUNNING,
                     source="test", summary="started")
    content_runs.insert(Phase1BRunRow(
        run_id=run.run_id, requested_at=datetime.now(UTC), provider="fixture",
        status=content_status,
    ))
    bridge = ScheduledDataRunBridge(
        tasks, real_runs, FakeDataRuns(), FakeWriting(), content_runs=content_runs,
    )

    assert bridge.advance() == 0
    assert tasks.get_task_detail(task_id)["status"] == target
    events = len(tasks.list_events(task_id))
    assert bridge.advance() == 0
    assert len(tasks.list_events(task_id)) == events
