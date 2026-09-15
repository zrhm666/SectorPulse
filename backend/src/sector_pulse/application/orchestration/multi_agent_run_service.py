"""Single application entry point for new parent/child agent runs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sector_pulse.application.orchestration.controls import (
    ArtifactContent,
    ArtifactReader,
    CompletionGoal,
    RequiredArtifactsFinalizationPolicy,
)
from sector_pulse.application.orchestration.runtime import OrchestrationRunStarter
from sector_pulse.application.orchestration.selection_resume import SelectionResumeService
from sector_pulse.application.orchestration.tasks import TaskCoordinator
from sector_pulse.config.llm_config import LLMRuntimeConfig
from sector_pulse.domain.market.candidate_selection import CandidateSelection
from sector_pulse.domain.orchestration.models import ArtifactRef, TaskStatus
from sector_pulse.infrastructure.agents.composition import BusinessToolFactory
from sector_pulse.infrastructure.agents.provider_factory import AgentProviderFactory
from sector_pulse.infrastructure.agents.roles import ContextToolBuilder
from sector_pulse.infrastructure.agents.runtime import ParentAgentRuntime
from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
from sector_pulse.ports.orchestration import SnapshotRepository
from sector_pulse.storage.ports.market import CandidateProposalRepositoryPort


@dataclass(frozen=True)
class MultiAgentRunRequest:
    goal: str
    run_id: UUID | None = None
    selection_policy: Literal["manual", "server_default"] = "manual"
    confirmed_selection: CandidateSelection | None = None

    def __post_init__(self) -> None:
        if not self.goal.strip():
            raise ValueError("run goal is required")
        if self.confirmed_selection is not None and self.run_id != self.confirmed_selection.run_id:
            raise ValueError("confirmed selection must belong to the orchestration run")


class _UnavailableArtifactReader:
    def read(self, artifact: ArtifactRef, *, max_chars: int) -> ArtifactContent:
        del artifact, max_chars
        raise ValueError("artifact content reader is not configured")


class MultiAgentRunService:
    """Preflight, persist, and execute one aidynamic-agent root run."""

    def __init__(
        self,
        *,
        repository: SnapshotRepository,
        config: LLMRuntimeConfig,
        prompt_registry: PromptRegistry,
        provider_factory: AgentProviderFactory,
        business_tool_builders: Mapping[str, ContextToolBuilder] | None = None,
        business_tool_factory: BusinessToolFactory | None = None,
        tool_reserved_cny: Mapping[str, Decimal | int] | None = None,
        artifact_reader: ArtifactReader | None = None,
        finalization_policy: RequiredArtifactsFinalizationPolicy | None = None,
        candidate_proposals: CandidateProposalRepositoryPort | None = None,
    ) -> None:
        self.repository = repository
        self.config = config
        self.prompt_registry = prompt_registry
        self.provider_factory = provider_factory
        self.business_tool_builders = dict(business_tool_builders or {})
        self.business_tool_factory = business_tool_factory
        self.tool_reserved_cny = dict(tool_reserved_cny or {})
        self.artifact_reader = artifact_reader or _UnavailableArtifactReader()
        self.finalization_policy = finalization_policy or RequiredArtifactsFinalizationPolicy(
            goal=CompletionGoal.DATA_PREPARATION,
            is_current=lambda artifact: True,
        )
        self.candidate_proposals = candidate_proposals

    def preflight(self, provider: Literal["fixture", "live"]) -> None:
        self.provider_factory.resolve_runtime_config(self.config, provider)

    async def create(
        self,
        request: MultiAgentRunRequest,
        *,
        provider: Literal["fixture", "live"],
        retry_of_run_id: UUID | None = None,
    ) -> UUID:
        runtime_config = self.provider_factory.resolve_runtime_config(self.config, provider)
        run_id = request.run_id or uuid4()
        if self.repository.load(run_id) is not None:
            raise ValueError("orchestration run already exists")
        root_id = uuid4()
        worker_id = f"root-agent-{uuid4()}"
        initial_artifacts: tuple[ArtifactRef, ...] = ()
        selection_version = None
        if request.confirmed_selection is not None:
            selection_version = request.confirmed_selection.version
            initial_artifacts = (
                ArtifactRef(
                    artifact_id=uuid5(
                        NAMESPACE_URL,
                        f"sector-pulse:candidate-selection:{run_id}:{selection_version}",
                    ),
                    task_id=root_id,
                    attempt=1,
                    kind="candidate_selection",
                    reference=f"candidate-selection:{selection_version}",
                ),
            )
        root = OrchestrationRunStarter(self.repository, runtime_config).start(
            run_id=run_id,
            task_id=root_id,
            worker_id=worker_id,
            goal=request.goal,
            provider=provider,
            selection_policy=request.selection_policy,
            retry_of_run_id=retry_of_run_id,
            initial_artifacts=initial_artifacts,
            selection_version=selection_version,
        )
        await self._run_owned(
            run_id=run_id,
            root_id=root_id,
            attempt=root.attempt,
            worker_id=worker_id,
            goal=request.goal,
            provider=provider,
            runtime_config=runtime_config,
            selection_version=selection_version,
        )
        return run_id

    def cancel(self, run_id: UUID) -> None:
        state = self.repository.load(run_id)
        if state is None:
            raise KeyError("orchestration run not found")
        root = next(task for task in state.tasks if task.parent_id is None)
        TaskCoordinator(self.repository, run_id).cancel(root.task_id)

    async def recover(
        self,
        run_id: UUID,
        *,
        expected_attempt: int,
        now: datetime | None = None,
    ) -> UUID:
        state = self.repository.load(run_id)
        if state is None:
            raise KeyError("orchestration run not found")
        runtime_config = self.provider_factory.resolve_runtime_config(
            self.config, state.provider
        )
        root = next(task for task in state.tasks if task.parent_id is None)
        observed_at = now or datetime.now(UTC)
        worker_id = f"root-agent-{uuid4()}"
        lease_expires_at = min(
            state.deadline,
            observed_at + timedelta(seconds=runtime_config.orchestration_timeout_seconds),
        )
        recovered = TaskCoordinator(self.repository, run_id).recover(
            root.task_id,
            expected_attempt=expected_attempt,
            worker_id=worker_id,
            lease_expires_at=lease_expires_at,
            now=observed_at,
        )
        await self._run_owned(
            run_id=run_id,
            root_id=root.task_id,
            attempt=recovered.attempt,
            worker_id=worker_id,
            goal=root.scope,
            provider=state.provider,
            runtime_config=runtime_config,
            selection_version=root.selection_version,
        )
        return run_id

    async def confirm_selection(
        self,
        *,
        run_id: UUID,
        proposal_id: UUID,
        sector_ids: tuple[str, ...],
        expected_selection_version: int,
        expected_attempt: int,
    ) -> UUID:
        if self.candidate_proposals is None:
            raise RuntimeError("candidate proposal repository is not configured")
        state = self.repository.load(run_id)
        if state is None:
            raise KeyError("orchestration run not found")
        runtime_config = self.provider_factory.resolve_runtime_config(
            self.config, state.provider
        )
        root = next(task for task in state.tasks if task.parent_id is None)
        observed_at = datetime.now(UTC)
        worker_id = f"root-agent-{uuid4()}"
        claimed = SelectionResumeService(
            orchestration=self.repository,
            proposals=self.candidate_proposals,
        ).confirm_and_claim(
            run_id=run_id,
            proposal_id=proposal_id,
            sector_ids=sector_ids,
            expected_selection_version=expected_selection_version,
            expected_attempt=expected_attempt,
            worker_id=worker_id,
            lease_expires_at=min(
                state.deadline,
                observed_at + timedelta(seconds=runtime_config.orchestration_timeout_seconds),
            ),
            now=observed_at,
        )
        await self._run_owned(
            run_id=run_id,
            root_id=root.task_id,
            attempt=claimed.attempt,
            worker_id=worker_id,
            goal=root.scope,
            provider=state.provider,
            runtime_config=runtime_config,
            selection_version=claimed.selection_version,
        )
        return run_id

    async def confirm_default_selection(
        self,
        *,
        run_id: UUID,
        proposal_id: UUID,
        expected_selection_version: int,
        expected_attempt: int,
    ) -> UUID:
        if self.candidate_proposals is None:
            raise RuntimeError("candidate proposal repository is not configured")
        state = self.repository.load(run_id)
        if state is None:
            raise KeyError("orchestration run not found")
        if state.selection_policy != "server_default":
            raise ValueError("run was not authorized for server default selection")
        proposal = self.candidate_proposals.get(proposal_id)
        if proposal is None or proposal.run_id != run_id:
            raise ValueError("candidate proposal is not part of this run")
        return await self.confirm_selection(
            run_id=run_id,
            proposal_id=proposal_id,
            sector_ids=tuple(item.provider_sector_id for item in proposal.items),
            expected_selection_version=expected_selection_version,
            expected_attempt=expected_attempt,
        )

    async def _run_owned(
        self,
        *,
        run_id: UUID,
        root_id: UUID,
        attempt: int,
        worker_id: str,
        goal: str,
        provider: Literal["fixture", "live"],
        runtime_config: LLMRuntimeConfig,
        selection_version: int | None,
    ) -> None:
        prices: dict[str, Decimal | int] = {
            "delegate": 0,
            "inspect_artifacts": 0,
            "inspect_tasks": 0,
            "request_selection": 0,
            "request_finish": 0,
            **self.tool_reserved_cny,
        }
        runtime = ParentAgentRuntime(
            repository=self.repository,
            run_id=run_id,
            root_task_id=root_id,
            root_attempt=attempt,
            root_worker_id=worker_id,
            config=runtime_config,
            prompt_registry=self.prompt_registry,
            provider_builder=lambda role, configured: self.provider_factory.build(
                role, configured, provider
            ),
            business_tool_builders=(
                self.business_tool_factory.build(run_id=run_id, provider=provider)
                if self.business_tool_factory is not None
                else self.business_tool_builders
            ),
            tool_reserved_cny=prices,
            artifact_reader=self.artifact_reader,
            finalization_policy=self.finalization_policy,
            selection_version=selection_version,
        )
        coordinator = TaskCoordinator(self.repository, run_id)
        try:
            result = await runtime.run(goal)
            current = self.repository.load(run_id)
            if current is None:  # pragma: no cover - repository contract violation
                raise KeyError("orchestration run disappeared")
            current_root = next(task for task in current.tasks if task.task_id == root_id)
            if current_root.status is TaskStatus.RUNNING:
                if result.error is None:
                    coordinator.transition(
                        root_id,
                        attempt=attempt,
                        worker_id=worker_id,
                        target=TaskStatus.WAITING,
                    )
                else:
                    coordinator.fail(
                        root_id,
                        attempt=attempt,
                        worker_id=worker_id,
                        public_error_code="AGENT_EXECUTION_FAILED",
                    )
        except Exception:
            current = self.repository.load(run_id)
            if current is not None:
                current_root = next(task for task in current.tasks if task.task_id == root_id)
                if current_root.status is TaskStatus.RUNNING:
                    coordinator.fail(
                        root_id,
                        attempt=attempt,
                        worker_id=worker_id,
                        public_error_code="AGENT_EXECUTION_FAILED",
                    )
            raise
        finally:
            await self.provider_factory.close()
