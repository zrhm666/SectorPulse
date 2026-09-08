"""运行查询服务。

查询侧使用窄接口隔离 Web DTO 读取，避免页面路由依赖 RunService 的写入能力。
"""

from typing import Any, Protocol
from uuid import UUID

from sector_pulse.web.schemas.runs import RunDetail, RunSummary


class _RunQueryPort(Protocol):
    def list_runs(self, limit: int = 50) -> list[RunSummary]: ...

    def get_run(self, run_id: UUID) -> RunDetail | None: ...

    def get_radar(self, run_id: UUID) -> dict[str, Any]: ...

    def get_draft(self, run_id: UUID) -> dict[str, Any]: ...

    def get_evidence(self, run_id: UUID) -> dict[str, Any]: ...

    def get_review(self, run_id: UUID) -> dict[str, Any]: ...

    def render_draft_markdown(self, run_id: UUID) -> str | None: ...

    def render_draft_text(self, run_id: UUID) -> str | None: ...


class RunQueryService:
    def __init__(self, port: _RunQueryPort) -> None:
        self._port = port

    def list(self, limit: int = 50) -> list[RunSummary]:
        return self._port.list_runs(limit)

    def detail(self, run_id: UUID) -> RunDetail | None:
        return self._port.get_run(run_id)

    def radar(self, run_id: UUID) -> dict[str, Any]:
        return self._port.get_radar(run_id)

    def draft(self, run_id: UUID) -> dict[str, Any]:
        return self._port.get_draft(run_id)

    def evidence(self, run_id: UUID) -> dict[str, Any]:
        return self._port.get_evidence(run_id)

    def review(self, run_id: UUID) -> dict[str, Any]:
        return self._port.get_review(run_id)

    def markdown(self, run_id: UUID) -> str | None:
        return self._port.render_draft_markdown(run_id)

    def text(self, run_id: UUID) -> str | None:
        return self._port.render_draft_text(run_id)
