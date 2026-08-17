# backend/src/sector_pulse/web/progress_bus.py
import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from uuid import UUID


class ProgressBus:
    """进程内进度事件总线，支持 SSE 订阅与完成后回放。"""

    def __init__(self) -> None:
        self._queues: dict[UUID, list[asyncio.Queue[dict[str, object] | None]]] = defaultdict(
            list
        )
        self._buffers: dict[UUID, list[dict[str, object]]] = defaultdict(list)

    async def subscribe(self, run_id: UUID) -> AsyncIterator[dict[str, object]]:
        queue: asyncio.Queue[dict[str, object] | None] = asyncio.Queue()
        self._queues[run_id].append(queue)
        for buffered in self._buffers.get(run_id, []):
            await queue.put(buffered)
        try:
            while True:
                event: dict[str, object] | None = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            self._queues[run_id].remove(queue)

    def emit(self, run_id: UUID, event: dict[str, object]) -> None:
        self._buffers[run_id].append(event)
        for queue in self._queues.get(run_id, []):
            queue.put_nowait(event)

    def close(self, run_id: UUID) -> None:
        for queue in self._queues.get(run_id, []):
            queue.put_nowait(None)
