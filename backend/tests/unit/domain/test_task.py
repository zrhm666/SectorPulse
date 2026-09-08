from sector_pulse.domain.runs.task import TaskRunStatus


def test_interrupted_task_is_terminal() -> None:
    assert TaskRunStatus.INTERRUPTED.is_terminal
