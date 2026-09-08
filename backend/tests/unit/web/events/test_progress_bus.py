# backend/tests/unit/web/test_progress_bus.py
import asyncio
from uuid import uuid4

from sector_pulse.web.events.progress_bus import ProgressBus


def test_emit_and_subscribe() -> None:
    bus = ProgressBus()
    run_id = uuid4()
    received: list[dict] = []

    async def main() -> None:
        async def subscriber() -> None:
            async for event in bus.subscribe(run_id):
                received.append(event)

        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0)
        bus.emit(run_id, {"type": "progress", "stage": "start"})
        bus.emit(run_id, {"type": "done"})
        bus.close(run_id)
        await task

    asyncio.run(main())
    assert received == [
        {"type": "progress", "stage": "start"},
        {"type": "done"},
    ]


def test_subscribe_replays_buffered_events() -> None:
    bus = ProgressBus()
    run_id = uuid4()
    # 事件先于订阅者到达：后续订阅者应回放缓冲区中已有的全部事件。
    bus.emit(run_id, {"type": "progress", "stage": "start"})
    bus.emit(run_id, {"type": "done"})
    received: list[dict] = []

    async def main() -> None:
        async def subscriber() -> None:
            async for event in bus.subscribe(run_id):
                received.append(event)

        task = asyncio.create_task(subscriber())
        await asyncio.sleep(0)
        bus.close(run_id)
        await task

    asyncio.run(main())
    assert received == [
        {"type": "progress", "stage": "start"},
        {"type": "done"},
    ]
