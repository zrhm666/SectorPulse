import asyncio
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from sector_pulse.application.phase1a2_probe import Phase1A2Dependencies
from sector_pulse.application.real_data_orchestrator import run_real_data_workflow
from sector_pulse.domain.real_data_run import RealDataRun, RealDataRunRequest, RealDataRunStatus
from sector_pulse.infrastructure.providers.real_data_factory import RealDataProviderFactory
from sector_pulse.storage.ports import RealDataRunRepositoryPort
from sector_pulse.web.progress_bus import ProgressBus


class DataRunService:
    """真实数据运行的后台任务门面；同步 preflight 早于任何数据库 insert。"""

    def __init__(
        self,
        repository: RealDataRunRepositoryPort,
        bus: ProgressBus,
        dependencies_factory: Callable[[str], Phase1A2Dependencies] | None = None,
        consent_file: Path | None = None,
        allow_fixture: bool = False,
    ) -> None:
        self.repository = repository
        self.bus = bus
        self._dependencies_factory = dependencies_factory
        self._factory = RealDataProviderFactory(consent_file)
        self._allow_fixture = allow_fixture
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._run_inputs: dict[
            UUID, tuple[RealDataRunRequest, Literal["fixture", "live"], UUID | None]
        ] = {}

    def preflight(self, provider: Literal["fixture", "live"]) -> None:
        if provider == "fixture":
            if not self._allow_fixture:
                raise ValueError("fixture data provider is not configured")
            return
        if provider != "live":
            raise ValueError(f"unknown provider: {provider}")
        result = self._factory.preflight()
        if not result.available:
            raise ValueError("missing live-data-consent")

    def create(
        self,
        request: RealDataRunRequest,
        provider: Literal["fixture", "live"],
        *,
        retry_of_run_id: UUID | None = None,
    ) -> UUID:
        self.preflight(provider)
        dependencies_factory = self._dependencies_factory
        if dependencies_factory is None:
            raise ValueError("real data dependencies are not configured")
        run_id = uuid4()

        async def execute() -> None:
            try:
                result = await run_real_data_workflow(
                    dependencies_factory(provider),
                    request,
                    run_id=run_id,
                    provider=provider,
                    retry_of_run_id=retry_of_run_id,
                    progress_sink=lambda status: self.bus.emit(
                        run_id,
                        {"type": "progress", "status": status.value},
                    ),
                )
                self.bus.finish(result.run.run_id, {"type": "done", "status": result.status.value})
            except asyncio.CancelledError:
                self._persist_cancelled(run_id, request, provider, retry_of_run_id)
                self.bus.finish(run_id, {"type": "cancelled", "status": "CANCELLED"})
                raise

        async def create_and_run() -> None:
            await execute()

        task = asyncio.create_task(create_and_run())
        self._tasks[run_id] = task
        self._run_inputs[run_id] = (request, provider, retry_of_run_id)

        def forget(_task: asyncio.Task[None]) -> None:
            self._tasks.pop(run_id, None)
            self._run_inputs.pop(run_id, None)

        task.add_done_callback(forget)
        return run_id

    def cancel(self, run_id: UUID) -> bool:
        task = self._tasks.get(run_id)
        if task is None or task.done():
            return False
        task.cancel()
        request, provider, retry_of_run_id = self._run_inputs[run_id]
        self._persist_cancelled(run_id, request, provider, retry_of_run_id)
        return True

    def _persist_cancelled(
        self,
        run_id: UUID,
        request: RealDataRunRequest,
        provider: Literal["fixture", "live"],
        retry_of_run_id: UUID | None,
    ) -> None:
        finished_at = datetime.now(UTC)
        if self.repository.get_run(run_id) is None:
            self.repository.insert(
                RealDataRun(
                    run_id=run_id,
                    retry_of_run_id=retry_of_run_id,
                    request=request,
                    provider=provider,
                    status=RealDataRunStatus.CANCELLED,
                    finished_at=finished_at,
                )
            )
        else:
            self.repository.update_status(
                run_id,
                RealDataRunStatus.CANCELLED,
                finished_at=finished_at,
            )

    async def wait(self, run_id: UUID) -> None:
        task = self._tasks.get(run_id)
        if task is None:
            return
        with suppress(asyncio.CancelledError):
            await task

    def retry(self, run_id: UUID) -> UUID:
        source = self.repository.get_run(run_id)
        if source is None:
            raise KeyError(run_id)
        retryable = {
            RealDataRunStatus.DEGRADED,
            RealDataRunStatus.BLOCKED,
            RealDataRunStatus.FAILED,
            RealDataRunStatus.CANCELLED,
            RealDataRunStatus.INTERRUPTED,
        }
        if source.status not in retryable:
            raise ValueError(f"run status {source.status.value} cannot be retried")
        return self.create(source.request, source.provider, retry_of_run_id=source.run_id)

    def mark_interrupted(self) -> int:
        return self.repository.mark_interrupted()
