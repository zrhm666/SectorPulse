"""Background command adapter for the single multi-agent run service."""

from datetime import UTC, datetime
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

    def recover_expired(self, now: datetime | None = None) -> int:
        """Requeue expired root leases so the next worker owns a fresh attempt."""
        observed = now or datetime.now(UTC)
        recovered = 0
        for state in self._repository.list_snapshots(limit=None):
            root = next((task for task in state.tasks if task.parent_id is None), None)
            if root is None or root.status.value not in {"running", "interrupted"}:
                continue
            if root.lease_expires_at is None or root.lease_expires_at > observed:
                continue
            root_record = root
            async def execute(run_id: UUID = state.run_id, attempt: int = root_record.attempt,
                              observed_at: datetime = observed) -> None:
                await self._service.recover(
                    run_id,
                    expected_attempt=attempt,
                    now=observed_at,
                )
            self._tasks.start(state.run_id, execute())
            recovered += 1
        return recovered

    def candidate_proposal(self, run_id: UUID) -> tuple[Any, Any, int, int]:
        return self._service.candidate_proposal(run_id)

    async def confirm_selection(
        self,
        *,
        run_id: UUID,
        proposal_id: UUID,
        sector_ids: tuple[str, ...],
        expected_selection_version: int,
        expected_attempt: int,
    ) -> int:
        # WAITING_USER_SELECTION becomes visible inside the control Tool before
        # that Tool/model turn has finished settling its audit records. Joining
        # the old attempt prevents the human confirmation CAS from racing those
        # final writes.
        await self._tasks.wait(run_id)
        proposal, _, actual_version, actual_attempt = self._service.candidate_proposal(run_id)
        if proposal.proposal_id != proposal_id:
            raise ValueError("candidate proposal is stale")
        if actual_version != expected_selection_version:
            raise ValueError("candidate selection version is stale")
        if actual_attempt != expected_attempt:
            raise ValueError("candidate selection task attempt is stale")
        allowed = {item.provider_sector_id for item in proposal.items}
        if not 3 <= len(sector_ids) <= 12 or len(set(sector_ids)) != len(sector_ids):
            raise ValueError("candidate selection must contain 3 to 12 unique sectors")
        if not set(sector_ids).issubset(allowed):
            raise ValueError("candidate selection contains an unknown sector")

        async def execute() -> None:
            await self._service.confirm_selection(
                run_id=run_id,
                proposal_id=proposal_id,
                sector_ids=sector_ids,
                expected_selection_version=expected_selection_version,
                expected_attempt=expected_attempt,
            )

        self._tasks.start(run_id, execute())
        return expected_attempt + 1

    def retry(self, run_id: UUID) -> UUID:
        return self.retry_run(run_id)

    def cancel(self, run_id: UUID) -> bool:
        return self.cancel_run(run_id)

    async def wait(self, run_id: UUID) -> None:
        await self._tasks.wait(run_id)
