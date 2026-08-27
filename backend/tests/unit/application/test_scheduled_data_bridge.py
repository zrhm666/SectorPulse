from pathlib import Path
from uuid import uuid4

from sector_pulse.application.schedule_service import ScheduleCreate, ScheduleService
from sector_pulse.application.scheduled_data_bridge import ScheduledDataRunBridge
from sector_pulse.domain.real_data_run import RealDataRun, RealDataRunRequest, RealDataRunStatus
from sector_pulse.domain.task import TaskRunKey
from sector_pulse.storage.real_data_run_repository import SQLiteRealDataRunRepository
from sector_pulse.storage.sqlite import SQLiteDatabase
from sector_pulse.storage.task_repository import SQLiteTaskRepository


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


def test_scheduled_bridge_creates_and_links_real_data_run(tmp_path: Path):
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
    assert tasks.list_linked_runs() == [(task_run_id, data_runs.run_id)]


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
    assert selections.confirmed == [run.run_id]
    assert writing.generated == [(run.run_id, ("a", "b", "c"))]
