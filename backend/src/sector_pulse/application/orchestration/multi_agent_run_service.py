"""Single application entry point for new parent/child agent runs."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
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
from sector_pulse.domain.market.candidate_proposal import CandidateProposal
from sector_pulse.domain.market.candidate_selection import CandidateSelection
from sector_pulse.domain.orchestration.models import ArtifactRef, TaskStatus
from sector_pulse.infrastructure.agents.composition import BusinessToolFactory
from sector_pulse.infrastructure.agents.provider_factory import AgentProviderFactory
from sector_pulse.infrastructure.agents.roles import ContextToolBuilder
from sector_pulse.infrastructure.agents.runtime import ParentAgentRuntime
from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
from sector_pulse.ports.orchestration import RevisionConflict, SnapshotRepository
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
        review_scope_resolver: Callable[[UUID], str] | None = None,
    ) -> None:
        self.repository = repository
        self.config = config
        self.prompt_registry = prompt_registry
        self.provider_factory = provider_factory
        self.business_tool_builders = dict(business_tool_builders or {})
        self.business_tool_factory = business_tool_factory
        self.tool_reserved_cny = dict(tool_reserved_cny or {})
        self.artifact_reader = artifact_reader or _UnavailableArtifactReader()
        self.finalization_policy = finalization_policy
        self.candidate_proposals = candidate_proposals
        self.review_scope_resolver = review_scope_resolver

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
            selected_sectors=(),
        )
        return run_id

    def cancel(self, run_id: UUID) -> None:
        state = self.repository.load(run_id)
        if state is None:
            raise KeyError("orchestration run not found")
        root = next(task for task in state.tasks if task.parent_id is None)
        TaskCoordinator(self.repository, run_id).cancel(root.task_id)

    def candidate_proposal(self, run_id: UUID) -> tuple[CandidateProposal, ArtifactRef, int, int]:
        if self.candidate_proposals is None:
            raise RuntimeError("candidate proposal repository is not configured")
        state = self.repository.load(run_id)
        if state is None:
            raise KeyError("orchestration run not found")
        root = next(task for task in state.tasks if task.parent_id is None)
        artifacts = [item for item in state.artifacts if item.kind == "candidate_proposal"]
        if not artifacts:
            raise KeyError("candidate proposal not found")
        artifact = artifacts[-1]
        prefix = "candidate-proposal:"
        if not artifact.reference.startswith(prefix):
            raise ValueError("candidate proposal reference is invalid")
        proposal = self.candidate_proposals.get(UUID(artifact.reference[len(prefix) :]))
        if proposal is None or proposal.run_id != run_id:
            raise KeyError("candidate proposal not found")
        return proposal, artifact, root.selection_version or 0, root.attempt

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
            selected_sectors=(),
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
        observed_at = datetime.now(UTC)
        resumed_deadline = observed_at + timedelta(
            seconds=runtime_config.orchestration_timeout_seconds
        )
        if state.deadline < resumed_deadline:
            for _ in range(32):
                state = self.repository.load(run_id)
                if state is None:
                    raise KeyError("orchestration run not found")
                if state.deadline >= resumed_deadline:
                    break
                try:
                    self.repository.save(
                        state.model_copy(
                            update={
                                "revision": state.revision + 1,
                                "deadline": resumed_deadline,
                            }
                        ),
                        state.revision,
                        "run.deadline_refreshed_after_selection",
                    )
                    state = self.repository.load(run_id)
                    break
                except RevisionConflict:
                    continue
            else:
                raise RevisionConflict("could not refresh run deadline")
        state = self.repository.load(run_id)
        if state is None:
            raise KeyError("orchestration run not found")
        root = next(task for task in state.tasks if task.parent_id is None)
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
        proposal = self.candidate_proposals.get(proposal_id)
        if proposal is None:  # pragma: no cover - atomically validated above
            raise KeyError("candidate proposal not found")
        by_id = {item.provider_sector_id: item for item in proposal.items}
        selected_sectors = tuple(
            (sector_id, by_id[sector_id].kind.value, by_id[sector_id].name)
            for sector_id in sector_ids
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
            selected_sectors=selected_sectors,
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
        selected_sectors: tuple[tuple[str, str, str], ...],
    ) -> None:
        run_provider_factory = self.provider_factory.create_run_scope()
        prices: dict[str, Decimal | int] = {
            "delegate": 0,
            "inspect_artifacts": 0,
            "inspect_tasks": 0,
            "request_selection": 0,
            "request_finish": 0,
            **self.tool_reserved_cny,
        }
        finalization_policy = self.finalization_policy or RequiredArtifactsFinalizationPolicy(
            goal=(
                CompletionGoal.FULL_ANALYSIS
                if selection_version is not None
                else CompletionGoal.DATA_PREPARATION
            ),
            required_analysis_scopes=tuple(
                f"sector:{kind}:{sector_id}" for sector_id, kind, _name in selected_sectors
            ),
            is_current=lambda artifact: True,
        )
        runtime = ParentAgentRuntime(
            repository=self.repository,
            run_id=run_id,
            root_task_id=root_id,
            root_attempt=attempt,
            root_worker_id=worker_id,
            config=runtime_config,
            prompt_registry=self.prompt_registry,
            provider_builder=lambda role, configured: run_provider_factory.build(
                role, configured, provider
            ),
            business_tool_builders=(
                self.business_tool_factory.build(run_id=run_id, provider=provider)
                if self.business_tool_factory is not None
                else self.business_tool_builders
            ),
            tool_reserved_cny=prices,
            artifact_reader=self.artifact_reader,
            finalization_policy=finalization_policy,
            selection_version=selection_version,
            allowed_analysis_scopes=tuple(
                f"sector:{kind}:{sector_id}" for sector_id, kind, _name in selected_sectors
            ),
            review_scope_resolver=self.review_scope_resolver,
        )
        coordinator = TaskCoordinator(self.repository, run_id)
        try:
            current_state = self.repository.load(run_id)
            if current_state is None:
                raise KeyError("orchestration run disappeared")
            result = await runtime.run(
                json.dumps(
                    {
                        "run_id": str(run_id),
                        "goal": goal,
                        "selection_version": selection_version,
                        "selected_sectors": [
                            {"sector_id": sector_id, "kind": kind, "name": name}
                            for sector_id, kind, name in selected_sectors
                        ],
                        "research_artifact_refs": [
                            str(artifact.artifact_id)
                            for artifact in current_state.artifacts
                            if artifact.kind in {"candidate_batch", "news_batch"}
                        ],
                    },
                    ensure_ascii=False,
                )
            )
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
            await run_provider_factory.close()
