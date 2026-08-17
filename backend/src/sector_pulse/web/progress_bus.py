# backend/src/sector_pulse/web/progress_bus.py
import asyncio
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from uuid import UUID


class ProgressBus:
    """进程内进度总线：事件回放有界，终态订阅会自动结束。"""

    def __init__(self, max_events_per_run: int = 256, max_terminal_runs: int = 128) -> None:
        if max_events_per_run < 1 or max_terminal_runs < 1:
            raise ValueError("progress bus limits must be positive")
        self._max_events = max_events_per_run
        self._max_terminal_runs = max_terminal_runs
        self._queues: dict[UUID, list[asyncio.Queue[dict[str, object] | None]]] = defaultdict(list)
        self._buffers: dict[UUID, deque[dict[str, object]]] = defaultdict(
            lambda: deque(maxlen=self._max_events)
        )
        self._terminal: set[UUID] = set()

    async def subscribe(self, run_id: UUID) -> AsyncIterator[dict[str, object]]:
        """先回放已有事件；已终止 run 回放后立即关闭。"""
        queue: asyncio.Queue[dict[str, object] | None] = asyncio.Queue()
        self._queues[run_id].append(queue)
        for buffered in self._buffers.get(run_id, ()):
            await queue.put(buffered)
        if run_id in self._terminal:
            await queue.put(None)
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            subscribers = self._queues.get(run_id, [])
            if queue in subscribers:
                subscribers.remove(queue)
            if not subscribers and run_id in self._terminal:
                self._queues.pop(run_id, None)
                self._buffers.pop(run_id, None)
                self._terminal.discard(run_id)

    def emit(self, run_id: UUID, event: dict[str, object]) -> None:
        if run_id in self._terminal:
            return
        self._buffers[run_id].append(event)
        for queue in self._queues.get(run_id, ()):
            queue.put_nowait(event)

    def finish(self, run_id: UUID, terminal_event: dict[str, object]) -> None:
        """记录终态、广播终态并关闭当前订阅者。"""
        if run_id in self._terminal:
            return
        self._terminal.add(run_id)
        self._buffers[run_id].append(terminal_event)
        for queue in self._queues.get(run_id, ()):
            queue.put_nowait(terminal_event)
            queue.put_nowait(None)
        self._evict_terminal_runs()

    def close(self, run_id: UUID) -> None:
        """兼容旧调用方；无终态事件时用空关闭信号结束订阅。"""
        if run_id in self._terminal:
            return
        self._terminal.add(run_id)
        for queue in self._queues.get(run_id, ()):
            queue.put_nowait(None)
        self._evict_terminal_runs()

    def _evict_terminal_runs(self) -> None:
        if len(self._terminal) <= self._max_terminal_runs:
            return
        for run_id in tuple(self._terminal)[: len(self._terminal) - self._max_terminal_runs]:
            if not self._queues.get(run_id):
                self._terminal.discard(run_id)
                self._buffers.pop(run_id, None)