"""Production composition for A0 execution and bounded T16 child dispatch."""

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from aidynamic_agent.core.agent import AgentResult
from aidynamic_agent.llm.base import LLMProvider
from aidynamic_agent.tools.base import Tool, ToolResult
from aidynamic_agent.tools.builtins.skill import SkillTool

from sector_pulse.application.orchestration.controls import (
    ArtifactInspector,
    ArtifactReader,
    FinalizationController,
    RequiredArtifactsFinalizationPolicy,
    SelectionController,
    TaskInspector,
)
from sector_pulse.application.orchestration.tasks import TaskCoordinator
from sector_pulse.config.llm_config import LLMRuntimeConfig
from sector_pulse.domain.orchestration.models import TaskStatus
from sector_pulse.infrastructure.agents.control_tools import (
    InspectArtifactsTool,
    InspectTasksTool,
    RequestFinishTool,
    RequestSelectionTool,
)
from sector_pulse.infrastructure.agents.delegation import RestrictedDelegateTool
from sector_pulse.infrastructure.agents.roles import (
    AgentRole,
    AgentToolContext,
    ContextToolBuilder,
    RoleAgentFactory,
    RoleRuntime,
    role_runtimes_from_config,
)
from sector_pulse.infrastructure.agents.skills import AllowedSkillManager
from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
from sector_pulse.ports.orchestration import SnapshotRepository

RuntimeProviderBuilder = Callable[[AgentRole, RoleRuntime], LLMProvider]


class ParentAgentRuntime:
    def __init__(
        self,
        *,
        repository: SnapshotRepository,
        run_id: UUID,
        root_task_id: UUID,
        root_attempt: int,
        root_worker_id: str,
        config: LLMRuntimeConfig,
        prompt_registry: PromptRegistry,
        provider_builder: RuntimeProviderBuilder,
        business_tool_builders: Mapping[str, ContextToolBuilder],
        tool_reserved_cny: Mapping[str, Decimal | int],
        artifact_reader: ArtifactReader,
        finalization_policy: RequiredArtifactsFinalizationPolicy,
        selection_version: int | None = None,
    ) -> None:
        self.repository = repository
        self.run_id = run_id
        self.root_task_id = root_task_id
        self.root_attempt = root_attempt
        self.root_worker_id = root_worker_id
        self.config = config
        self.provider_builder = provider_builder
        self.runtimes = role_runtimes_from_config(config, prompt_registry)
        self.artifact_reader = artifact_reader
        self.finalization_policy = finalization_policy
        self.selection_version = selection_version
        self.business_tool_builders = dict(business_tool_builders)
        self.tool_reserved_cny = {
            name: value if isinstance(value, Decimal) else Decimal(value)
            for name, value in tool_reserved_cny.items()
        }
        self.factory = self._build_factory()

    def _build_factory(self) -> RoleAgentFactory:
        contextual: dict[str, ContextToolBuilder] = dict(self.business_tool_builders)
        contextual.update(
            {
                "delegate": lambda context: RestrictedDelegateTool(self._dispatch),
                "inspect_artifacts": self._inspect_artifacts,
                "inspect_tasks": self._inspect_tasks,
                "request_selection": self._request_selection,
                "request_finish": self._request_finish,
                "skill": lambda context: SkillTool(),
            }
        )
        self.tool_reserved_cny.setdefault("skill", Decimal("0"))
        a1_skills = AllowedSkillManager(
            Path("config/agent-skills"),
            allowed_names=frozenset({"data-gap-handling", "sector-selection"}),
        )
        a2_skills = AllowedSkillManager(
            Path("config/agent-skills"),
            allowed_names=frozenset({"causal-evidence", "news-verification"}),
        )
        a3_skills = AllowedSkillManager(
            Path("config/agent-skills"),
            allowed_names=frozenset({"analysis-writing"}),
        )
        a4_skills = AllowedSkillManager(
            Path("config/agent-skills"),
            allowed_names=frozenset({"independent-review", "news-verification"}),
        )
        return RoleAgentFactory(
            repository=self.repository,
            run_id=self.run_id,
            provider_builder=self._provider,
            role_runtimes=self.runtimes,
            tool_builders={},
            contextual_tool_builders=contextual,
            tool_reserved_cny=self.tool_reserved_cny,
            skill_managers={
                AgentRole.A1: a1_skills,
                AgentRole.A2: a2_skills,
                AgentRole.A3: a3_skills,
                AgentRole.A4: a4_skills,
            },
        )

    def _provider(self, runtime: RoleRuntime) -> LLMProvider:
        role = next(role for role, candidate in self.runtimes.items() if candidate is runtime)
        return self.provider_builder(role, runtime)

    def _inspect_artifacts(self, context: AgentToolContext) -> Tool:
        return InspectArtifactsTool(
            ArtifactInspector(self.repository, self.run_id, self.artifact_reader),
            task_id=context.task_id,
            attempt=context.attempt,
        )

    def _inspect_tasks(self, context: AgentToolContext) -> Tool:
        return InspectTasksTool(
            TaskInspector(self.repository, self.run_id),
            task_id=context.task_id,
            attempt=context.attempt,
        )

    def _request_selection(self, context: AgentToolContext) -> Tool:
        return RequestSelectionTool(
            SelectionController(self.repository, self.run_id),
            task_id=context.task_id,
            attempt=context.attempt,
            worker_id=context.worker_id,
        )

    def _request_finish(self, context: AgentToolContext) -> Tool:
        return RequestFinishTool(
            FinalizationController(
                self.repository,
                self.run_id,
                self.finalization_policy,
            ),
            task_id=context.task_id,
            attempt=context.attempt,
            worker_id=context.worker_id,
        )

    async def run(self, goal: str) -> AgentResult:
        parent = self.factory.create(self.root_task_id, attempt=self.root_attempt)
        return await parent.run(goal)

    async def _dispatch(
        self,
        role_name: str,
        goal: str,
        scope: str,
        artifact_refs: tuple[str, ...],
    ) -> ToolResult:
        role = AgentRole(role_name)
        if role is AgentRole.A0:
            raise ValueError("A0 cannot be delegated")
        state = self.repository.load(self.run_id)
        if state is None:
            raise KeyError("orchestration run not found")
        by_reference = {
            value: artifact
            for artifact in state.artifacts
            for value in (str(artifact.artifact_id), artifact.reference)
        }
        try:
            input_artifact_ids = tuple(by_reference[value].artifact_id for value in artifact_refs)
        except KeyError as exc:
            raise ValueError("delegation references an unknown artifact") from exc
        now = datetime.now(UTC)
        lease_expires_at = min(state.deadline, now + timedelta(seconds=120))
        child_id = uuid4()
        child_worker_id = f"agent-{uuid4()}"
        child = TaskCoordinator(self.repository, self.run_id).delegate_child(
            self.root_task_id,
            parent_attempt=self.root_attempt,
            parent_worker_id=self.root_worker_id,
            child_id=child_id,
            child_worker_id=child_worker_id,
            child_lease_expires_at=lease_expires_at,
            role=role.value,
            scope=scope,
            input_artifact_ids=input_artifact_ids,
            selection_version=self.selection_version,
            now=now,
        )
        prompt = json.dumps(
            {"goal": goal, "scope": scope, "artifact_refs": artifact_refs},
            ensure_ascii=False,
        )
        try:
            result = await self.factory.create(child.task_id, attempt=child.attempt).run(prompt)
        except Exception:
            TaskCoordinator(self.repository, self.run_id).fail(
                child.task_id,
                attempt=child.attempt,
                worker_id=child_worker_id,
                public_error_code="AGENT_EXECUTION_FAILED",
            )
            return ToolResult(
                content="specialist execution failed",
                success=False,
                error="specialist execution failed",
                metadata={"result_reference": f"task:{child.task_id}"},
            )
        target = TaskStatus.COMPLETED if result.error is None else TaskStatus.FAILED
        coordinator = TaskCoordinator(self.repository, self.run_id)
        if target is TaskStatus.COMPLETED:
            coordinator.transition(
                child.task_id,
                attempt=child.attempt,
                worker_id=child_worker_id,
                target=target,
            )
        else:
            coordinator.fail(
                child.task_id,
                attempt=child.attempt,
                worker_id=child_worker_id,
                public_error_code="AGENT_EXECUTION_FAILED",
            )
        return ToolResult(
            content=result.text[:4000],
            success=result.error is None,
            error=result.error,
            metadata={"result_reference": f"task:{child.task_id}"},
        )
