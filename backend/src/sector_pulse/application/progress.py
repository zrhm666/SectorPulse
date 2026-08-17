from typing import Any, Protocol


class ProgressSink(Protocol):
    """管线进度事件接收器，只通报阶段事实，不感知 Web/SSE。"""

    def emit(self, stage: str, detail: dict[str, Any]) -> None: ...


class NoopProgressSink:
    """默认空实现，保证现有调用方零改动。"""

    def emit(self, stage: str, detail: dict[str, Any]) -> None:
        pass
