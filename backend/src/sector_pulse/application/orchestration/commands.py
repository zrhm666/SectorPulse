"""Background command adapter for the single multi-agent run service."""

from typing import Any, Literal
from uuid import UUID, uuid4

from sector_pulse.application.orchestration.multi_agent_run_service import (
    MultiAgentRunRequest,
    MultiAgentRunService,
)
from sector_pulse.application.tasks.task_registry import RunTaskRegistry
from sector_pulse.domain.market.candidate_selection import CandidateSelection
from sector_pulse.ports.orchestration import SnapshotRepository
from sector_pulse.storage.ports.runs import RealDataRunRepositoryPort
from sector_pulse.web.services.run_service import ProviderUnavailable


class MultiAgentRunCommands:
    execution_engine: Literal["multi_agent"] = "multi_agent"

    def __init__(
        self,
        *,
        service: MultiAgentRunService,
        repository: SnapshotRepository,
        tasks: RunTaskRegistry | None = None,
        real_runs: RealDataRunRepositoryPort | None = None,
    ) -> None:
        self._service = service
        self._repository = repository
        self._tasks = tasks or RunTaskRegistry()
        self._real_runs = real_runs

    def create_run(
        self,
        input_json: dict[str, Any],
        provider: Literal["fixture", "live"],
        *,
        selection_policy: Literal["manual", "server_default"] = "manual",
        retry_of_run_id: UUID | None = None,
    ) -> UUID:
        try:
            self._service.preflight(provider)
        except ValueError as exc:
            raise ProviderUnavailable(str(exc)) from exc
        goal = input_json.get("goal") or ("full sector analysis" if input_json else None)
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("run goal is required")
        run_id = uuid4()
        request = MultiAgentRunRequest(
            run_id=run_id,
            goal=goal,
            selection_policy=selection_policy,
        )

        async def execute() -> None:
            await self._service.create(
                request,
                provider=provider,
                retry_of_run_id=retry_of_run_id,
            )

        self._tasks.start(run_id, execute())
        return run_id

    def create(
        self,
        input_json: dict[str, Any],
        provider: Literal["fixture", "live"] = "fixture",
        *,
        selection_policy: Literal["manual", "server_default"] = "manual",
    ) -> UUID:
        return self.create_run(
            input_json,
            provider,
            selection_policy=selection_policy,
        )

    def continue_data_run(
        self,
        run_id: UUID,
        selection: CandidateSelection,
        *,
        provider: Literal["fixture", "live"],
    ) -> UUID:
        try:
            self._service.preflight(provider)
        except ValueError as exc:
            raise ProviderUnavailable(str(exc)) from exc
        if selection.run_id != run_id:
            raise ValueError("confirmed selection must belong to the data run")
        if self._repository.load(run_id) is not None:
            raise ValueError("orchestration run already exists")
        goal = (
            f"complete sector analysis for confirmed selection v{selection.version}: "
            f"{', '.join(selection.selected_sector_ids)}"
        )
        request = MultiAgentRunRequest(
            run_id=run_id,
            goal=goal,
            confirmed_selection=selection,
        )

        async def execute() -> None:
            await self._service.create(request, provider=provider)

        self._tasks.start(run_id, execute())
        return run_id

    def retry_run(self, run_id: UUID) -> UUID:
        state = self._repository.load(run_id)
        if state is None:
            raise KeyError("orchestration run not found")
        root = next(task for task in state.tasks if task.parent_id is None)
        return self.create_run(
            {"goal": root.scope},
            state.provider,
            selection_policy=state.selection_policy,
            retry_of_run_id=run_id,
        )

    def retry_data_run(self, run_id: UUID) -> UUID:
        if self._real_runs is None:
            raise RuntimeError("real data run repository is not configured")
        source = self._real_runs.get_run(run_id)
        if source is None:
            raise KeyError("data run not found")
        scene = "盘中" if source.request.mode == "intraday" else "盘后"
        return self.create_run(
            {"goal": f"重新执行{scene}板块分析，复用历史输入 {run_id}"},
            source.provider,
            retry_of_run_id=run_id,
        )

    def cancel_run(self, run_id: UUID) -> bool:
        self._tasks.cancel(run_id)
        try:
            self._service.cancel(run_id)
        except KeyError:
            return False
        return True

    def retry(self, run_id: UUID) -> UUID:
        return self.retry_run(run_id)

    def cancel(self, run_id: UUID) -> bool:
        return self.cancel_run(run_id)

    async def wait(self, run_id: UUID) -> None:
        await self._tasks.wait(run_id)
