"""运行任务生命周期注册表。

将 asyncio Task 的保存、取消和完成清理从 Web 门面中抽离，避免请求层直接
管理后台任务字典。
"""

import asyncio
from collections.abc import Coroutine
from typing import Any
from uuid import UUID


class RunTaskRegistry:
    """按 run_id 管理后台任务，并在任务结束后自动释放引用。"""

    def __init__(self) -> None:
        self._tasks: dict[UUID, asyncio.Task[None]] = {}

    def start(self, run_id: UUID, coroutine: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coroutine)
        self._tasks[run_id] = task
        # done 回调只负责清理内存引用，不改变领域状态；状态由执行器统一落库。
        task.add_done_callback(lambda _: self._tasks.pop(run_id, None))

    def cancel(self, run_id: UUID) -> bool:
        task = self._tasks.get(run_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    def contains(self, run_id: UUID) -> bool:
        return run_id in self._tasks
