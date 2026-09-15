"""Production composition for A0 execution and bounded T16 child dispatch."""

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from aidynamic_agent.core.agent import AgentResult, TerminationReason
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
ReviewScopeResolver = Callable[[UUID], str]


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
        allowed_analysis_scopes: tuple[str, ...] = (),
        review_scope_resolver: ReviewScopeResolver | None = None,
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
        self.allowed_analysis_scopes = allowed_analysis_scopes
        self.review_scope_resolver = review_scope_resolver
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
        if role is AgentRole.A2 and self.allowed_analysis_scopes:
            used = {task.scope for task in state.tasks if task.role == AgentRole.A2.value}
            if scope not in self.allowed_analysis_scopes:
                matching = tuple(
                    candidate
                    for candidate in self.allowed_analysis_scopes
                    if candidate not in used and candidate.rsplit(":", 1)[-1] in goal
                )
                remaining = tuple(
                    candidate for candidate in self.allowed_analysis_scopes if candidate not in used
                )
                if matching:
                    scope = matching[0]
                elif remaining:
                    scope = remaining[0]
        elif role is AgentRole.A3 and not scope.startswith("revision:"):
            scope = f"article:{self.run_id}"
        failed_delegates = sum(
            1
            for call in state.ledger.tool_invocations
            if call.task_id == self.root_task_id
            and call.tool_name == "delegate"
            and call.status.value == "failed"
        )
        if failed_delegates >= 3:
            TaskCoordinator(self.repository, self.run_id).fail(
                self.root_task_id,
                attempt=self.root_attempt,
                worker_id=self.root_worker_id,
                public_error_code="SPECIALIST_RETRY_LIMIT",
            )
            return ToolResult(
                content="specialist retry limit reached",
                success=False,
                error="specialist retry limit reached",
            )
        by_reference = {
            value: artifact
            for artifact in state.artifacts
            for value in (str(artifact.artifact_id), artifact.reference)
        }
        authoritative_sector_ids: tuple[str, ...] = ()
        if role is AgentRole.A3 and scope == f"article:{self.run_id}":
            tasks_by_id = {task.task_id: task for task in state.tasks}
            selections = tuple(
                artifact
                for artifact in state.artifacts
                if artifact.kind == "candidate_selection"
            )
            current_analyses = tuple(
                artifact
                for artifact in state.artifacts
                if artifact.kind == "sector_analysis"
                and (owner := tasks_by_id.get(artifact.task_id)) is not None
                and owner.role == AgentRole.A2.value
                and owner.status is TaskStatus.COMPLETED
                and artifact.attempt == owner.attempt
            )
            artifact_refs = tuple(
                str(artifact.artifact_id)
                for artifact in (*selections[-1:], *current_analyses)
            )
            authoritative_sector_ids = tuple(
                tasks_by_id[artifact.task_id].scope.rsplit(":", 1)[-1]
                for artifact in current_analyses
            )
        elif not artifact_refs:
            fallback_kinds = {
                AgentRole.A2: {"candidate_batch", "news_batch", "candidate_selection"},
                AgentRole.A3: {"candidate_selection", "sector_analysis", "evidence_inspection"},
                AgentRole.A4: {"article_draft", "draft_rules"},
            }.get(role, set())
            artifact_refs = tuple(
                str(artifact.artifact_id)
                for artifact in state.artifacts
                if artifact.kind in fallback_kinds
            )
        try:
            input_artifact_ids = tuple(by_reference[value].artifact_id for value in artifact_refs)
        except KeyError as exc:
            raise ValueError("delegation references an unknown artifact") from exc
        if role is AgentRole.A4 and self.review_scope_resolver is not None:
            draft_inputs = tuple(
                by_reference[value]
                for value in artifact_refs
                if by_reference[value].kind == "article_draft"
            )
            if len(draft_inputs) != 1 or len(artifact_refs) != 1:
                raise ValueError("A4 delegation requires exactly one draft artifact")
            scope = self.review_scope_resolver(draft_inputs[0].artifact_id)
        now = datetime.now(UTC)
        lease_seconds = 300 if role in {AgentRole.A3, AgentRole.A4} else 120
        lease_expires_at = min(state.deadline, now + timedelta(seconds=lease_seconds))
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
        prompt_payload: dict[str, object] = {
            "goal": goal,
            "scope": scope,
            "artifact_refs": artifact_refs,
        }
        if authoritative_sector_ids:
            prompt_payload["authoritative_sector_ids"] = authoritative_sector_ids
            prompt_payload["identity_instruction"] = (
                "Use these exact sector IDs in outline and draft submissions; do not "
                "substitute names, ranks, or artifact IDs."
            )
        prompt = json.dumps(prompt_payload, ensure_ascii=False)
        required_output_kind = {
            AgentRole.A1: "candidate_proposal",
            AgentRole.A2: "sector_analysis",
            AgentRole.A3: "article_draft",
            AgentRole.A4: "independent_review",
        }[role]

        def has_required_output() -> bool:
            current = self.repository.load(self.run_id)
            return current is not None and any(
                artifact.task_id == child.task_id
                and artifact.attempt == child.attempt
                and artifact.kind == required_output_kind
                for artifact in current.artifacts
            )

        try:
            agent = self.factory.create(child.task_id, attempt=child.attempt)
            result = await agent.run(prompt)
            continuation_limit = 2 if role in {AgentRole.A3, AgentRole.A4} else 0
            for _ in range(continuation_limit):
                if has_required_output() or result.error is not None:
                    break
                if result.termination_reason is not TerminationReason.END_TURN:
                    break
                result = await agent.run(
                    f"Required output '{required_output_kind}' is still missing. "
                    "Use the validation feedback already in context, correct the payload, "
                    "and call the required submission tool now. Do not end with prose only."
                )
        except Exception:
            failed_coordinator = TaskCoordinator(self.repository, self.run_id)
            failed_coordinator.fail(
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
        target = (
            TaskStatus.COMPLETED
            if result.error is None and has_required_output()
            else TaskStatus.FAILED
        )
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
            latest = self.repository.load(self.run_id)
            if latest is not None and sum(
                1
                for task in latest.tasks
                if task.parent_id == self.root_task_id and task.status is TaskStatus.FAILED
            ) >= 3:
                failed_coordinator.fail(
                    self.root_task_id,
                    attempt=self.root_attempt,
                    worker_id=self.root_worker_id,
                    public_error_code="SPECIALIST_RETRY_LIMIT",
                )
            latest = self.repository.load(self.run_id)
            failed_children = (
                sum(
                    1
                    for task in latest.tasks
                    if task.parent_id == self.root_task_id and task.status is TaskStatus.FAILED
                )
                if latest is not None
                else 0
            )
            if failed_children >= 3:
                coordinator.fail(
                    self.root_task_id,
                    attempt=self.root_attempt,
                    worker_id=self.root_worker_id,
                    public_error_code="SPECIALIST_RETRY_LIMIT",
                )
        return ToolResult(
            content=result.text[:4000],
            success=result.error is None,
            error=result.error,
            metadata={"result_reference": f"task:{child.task_id}"},
        )
