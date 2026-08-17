"""运行命令服务。

该服务只负责把 Web 命令转交给运行门面，后续可在此集中加入权限、重试
幂等键和审计记录，而不把这些横切逻辑塞进 FastAPI 路由。
"""

from typing import Any, Protocol
from uuid import UUID


class _RunCommandPort(Protocol):
    def create_run(self, input_json: dict[str, Any], provider: str) -> UUID: ...

    def cancel_run(self, run_id: UUID) -> bool: ...

    def retry_run(self, run_id: UUID) -> UUID: ...


class RunCommandService:
    def __init__(self, port: _RunCommandPort) -> None:
        self._port = port

    def create(self, input_json: dict[str, Any], provider: str = "fixture") -> UUID:
        return self._port.create_run(input_json, provider)

    def cancel(self, run_id: UUID) -> bool:
        return self._port.cancel_run(run_id)

    def retry(self, run_id: UUID) -> UUID:
        return self._port.retry_run(run_id)
