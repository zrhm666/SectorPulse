import asyncio
from uuid import uuid4

from sector_pulse.application.task_registry import RunTaskRegistry


async def _noop() -> None:
    await asyncio.sleep(0)


def test_completed_task_is_removed() -> None:
    async def scenario() -> None:
        registry = RunTaskRegistry()
        run_id = uuid4()
        registry.start(run_id, _noop())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not registry.contains(run_id)

    asyncio.run(scenario())


def test_cancel_returns_false_for_unknown_run() -> None:
    assert RunTaskRegistry().cancel(uuid4()) is False
