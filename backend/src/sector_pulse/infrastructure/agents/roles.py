"""Server-owned A0-A4 role construction on the embedded agent framework."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from aidynamic_agent.agents.factory import AgentFactory
from aidynamic_agent.agents.parent import ParentAgent
from aidynamic_agent.agents.sub import SubAgent
from aidynamic_agent.core.agent import AgentConfig
from aidynamic_agent.core.message import (
    ContentBlockUnion,
    Message,
    Role,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from aidynamic_agent.llm.base import LLMProvider
from aidynamic_agent.managers.skill import SkillManager
from aidynamic_agent.tools.base import Tool
from aidynamic_agent.tools.registry import ToolRegistry

from sector_pulse.application.orchestration.budget import SharedBudget
from sector_pulse.application.orchestration.tasks import TaskOwnershipError
from sector_pulse.application.orchestration.tool_budget import SharedToolBudget
from sector_pulse.config.llm_config import LLMRuntimeConfig
from sector_pulse.domain.llm import PromptTurn
from sector_pulse.domain.orchestration.models import ModelPricing, TaskStatus
from sector_pulse.infrastructure.agents.provider import BudgetedProvider
from sector_pulse.infrastructure.agents.skills import AllowedSkillManager
from sector_pulse.infrastructure.agents.tool_adapter import BudgetedTool
from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry
from sector_pulse.ports.orchestration import SnapshotRepository


class AgentRole(StrEnum):
    A0 = "A0"
    A1 = "A1"
    A2 = "A2"
    A3 = "A3"
    A4 = "A4"


ROLE_TOOL_NAMES: dict[AgentRole, frozenset[str]] = {
    AgentRole.A0: frozenset(
        {
            "delegate",
            "inspect_artifacts",
            "inspect_tasks",
            "request_selection",
            "request_finish",
        }
    ),
    AgentRole.A1: frozenset(
        {
            "collect_market",
            "inspect_data_quality",
            "rank_sector_candidates",
            "collect_initial_news",
            "propose_candidates",
            "inspect_artifacts",
            "skill",
        }
    ),
    AgentRole.A2: frozenset(
        {
            "search_news",
            "read_news_detail",
            "inspect_evidence",
            "submit_analysis",
            "inspect_artifacts",
            "skill",
            # 内部研究资料库（规格 15）：只有 A2 有检索权限，因此只有 A2 的白名单里有它们。
            # 白名单说的是"这个角色**可以**调什么"；RAG 关掉时这三件工具根本不注册，于是
            # 这里的名字不会凭空出现在注册表里。
            "search_internal_research",
            "inspect_research_source",
            "accept_internal_evidence",
        }
    ),
    AgentRole.A3: frozenset(
        {
            "inspect_artifacts",
            "inspect_evidence",
            "submit_outline",
            "submit_draft",
            "submit_revision",
            "check_draft_rules",
            "skill",
        }
    ),
    AgentRole.A4: frozenset(
        {
            "inspect_artifacts",
            "read_news_detail",
            "inspect_evidence",
            "check_draft_rules",
            "submit_review",
            "skill",
        }
    ),
}


SKILLS_ROOT = Path("config/agent-skills")

# 每个角色能加载哪些方法文档。Skill 不是权限来源——能不能检索、能不能接纳证据由工具白名单
# 与接纳服务决定——这里决定的是"这个角色读得到哪些方法与写作规则"。
ROLE_SKILL_NAMES: dict[AgentRole, frozenset[str]] = {
    AgentRole.A1: frozenset({"data-gap-handling", "sector-selection"}),
    AgentRole.A2: frozenset(
        {"causal-evidence", "news-verification", "internal-research-retrieval"}
    ),
    AgentRole.A3: frozenset({"analysis-writing", "internal-evidence-writing"}),
    AgentRole.A4: frozenset(
        {"independent-review", "news-verification", "internal-evidence-writing"}
    ),
}


def role_skill_managers(skills_root: Path = SKILLS_ROOT) -> dict[AgentRole, SkillManager]:
    return {
        role: AllowedSkillManager(skills_root, allowed_names=names)
        for role, names in ROLE_SKILL_NAMES.items()
    }


def _task_tool_names(role: AgentRole, scope: str) -> frozenset[str]:
    if role is AgentRole.A3:
        if scope.startswith("revision:"):
            return frozenset({"inspect_artifacts", "submit_revision", "skill"})
        return frozenset({"inspect_artifacts", "submit_outline", "submit_draft", "skill"})
    if role is AgentRole.A4:
        return frozenset({"inspect_artifacts", "check_draft_rules", "submit_review", "skill"})
    return ROLE_TOOL_NAMES[role]


def _subagent_limits(role: AgentRole, scope: str) -> tuple[int, int]:
    """Allow enough turns for bounded inspect/skill/submit sequences."""
    if role is AgentRole.A3 and not scope.startswith("revision:"):
        return 24, 300
    if role in {AgentRole.A3, AgentRole.A4}:
        return 18, 300
    return 12, 120


@dataclass(frozen=True)
class RoleRuntime:
    provider: str
    model: str
    prompt: str
    pricing: ModelPricing | None
    demonstrations: tuple[PromptTurn, ...] = ()


def demonstration_messages(turns: Sequence[PromptTurn]) -> list[Message]:
    """把示范对话转成框架消息，工具调用与其结果保持成对且顺序一致。"""
    messages: list[Message] = []
    for turn in turns:
        if turn.role == "user":
            messages.append(Message.from_text(Role.USER, turn.text))
        elif turn.role == "tool":
            # 与框架自身写入工具结果的格式保持一致：user 轮只放结果块。
            result = ToolResultBlock(tool_call_id=turn.tool_call_id, tool_result_content=turn.text)
            messages.append(Message(Role.USER, [result]))
        else:
            blocks: list[ContentBlockUnion] = []
            if turn.text.strip():
                blocks.append(TextBlock(text=turn.text))
            if turn.calls_tool:
                blocks.append(
                    ToolUseBlock(
                        tool_call_id=turn.tool_call_id,
                        tool_name=turn.tool_name,
                        tool_input=dict(turn.tool_arguments),
                    )
                )
            messages.append(Message(Role.ASSISTANT, blocks))
    return messages


@dataclass(frozen=True)
class AgentToolContext:
    task_id: UUID
    attempt: int
    role: AgentRole
    scope: str
    worker_id: str
    input_artifact_ids: tuple[UUID, ...] = ()
    selection_version: int | None = None


_ROLE_PROMPT_IDS = {
    AgentRole.A0: "orchestration_a0",
    AgentRole.A1: "orchestration_a1",
    AgentRole.A2: "orchestration_a2",
    AgentRole.A3: "orchestration_a3",
    AgentRole.A4: "orchestration_a4",
}


def role_runtimes_from_config(
    config: LLMRuntimeConfig, prompt_registry: PromptRegistry
) -> dict[AgentRole, RoleRuntime]:
    runtimes: dict[AgentRole, RoleRuntime] = {}
    for role in AgentRole:
        route = config.role_route_for(role.value)
        pricing = config.model_pricing(route.model)
        if pricing is None:
            raise ValueError(f"model price is not configured for {role.value}: {route.model}")
        prompt = prompt_registry.get(_ROLE_PROMPT_IDS[role])
        runtimes[role] = RoleRuntime(
            provider=route.provider,
            model=route.model,
            prompt=prompt.system,
            pricing=pricing,
            demonstrations=prompt.demonstrations,
        )
    return runtimes


ProviderBuilder = Callable[[RoleRuntime], LLMProvider]
ToolBuilder = Callable[[], Tool]
ContextToolBuilder = Callable[[AgentToolContext], Tool]


class RoleAgentFactory:
    def __init__(
        self,
        *,
        repository: SnapshotRepository,
        run_id: UUID,
        provider_builder: ProviderBuilder,
        role_runtimes: Mapping[AgentRole, RoleRuntime],
        tool_builders: Mapping[str, ToolBuilder],
        tool_reserved_cny: Mapping[str, Decimal | None],
        contextual_tool_builders: Mapping[str, ContextToolBuilder] | None = None,
        skill_managers: Mapping[AgentRole, SkillManager] | None = None,
    ) -> None:
        self.repository = repository
        self.run_id = run_id
        self.provider_builder = provider_builder
        self.role_runtimes = dict(role_runtimes)
        self.tool_builders = dict(tool_builders)
        self.tool_reserved_cny = dict(tool_reserved_cny)
        self.contextual_tool_builders = dict(contextual_tool_builders or {})
        self.skill_managers = dict(skill_managers or {})

    def create(self, task_id: UUID, *, attempt: int) -> ParentAgent | SubAgent:
        state = self.repository.load(self.run_id)
        if state is None:
            raise KeyError("orchestration run not found")
        task = next((item for item in state.tasks if item.task_id == task_id), None)
        if task is None:
            raise KeyError("orchestration task not found")
        if task.attempt != attempt:
            raise TaskOwnershipError("stale task attempt")
        if task.status is not TaskStatus.RUNNING:
            raise TaskOwnershipError("agent task does not hold a worker lease")
        if task.worker_id is None:
            raise TaskOwnershipError("agent task has no worker owner")
        if task.lease_expires_at is None or task.lease_expires_at <= datetime.now(UTC):
            raise TaskOwnershipError("agent task lease expired")
        try:
            role = AgentRole(task.role)
        except ValueError as exc:
            raise ValueError(f"unregistered agent role: {task.role}") from exc
        if task.parent_id is None and role is not AgentRole.A0:
            raise ValueError("root task must use A0")
        if task.parent_id is not None and role is AgentRole.A0:
            raise ValueError("A0 cannot be delegated as a child")
        try:
            runtime = self.role_runtimes[role]
        except KeyError as exc:
            raise KeyError(f"runtime is not configured for {role.value}") from exc

        budget = SharedBudget(
            self.repository,
            self.run_id,
            task_id=task_id,
            attempt=attempt,
            role=role.value,
            provider=runtime.provider,
            model=runtime.model,
            action_summary=f"{role.value} model turn",
        )
        provider = BudgetedProvider(
            self.provider_builder(runtime),
            budget,
            output_limit=8192 if role is AgentRole.A3 else 4096,
            pricing=runtime.pricing,
        )
        registry = ToolRegistry()
        skill_manager = self.skill_managers.get(role)
        if skill_manager is not None:
            registry.context.set("skill_manager", skill_manager)
        tool_budget = SharedToolBudget(self.repository, self.run_id)
        context = AgentToolContext(
            task_id=task_id,
            attempt=attempt,
            role=role,
            scope=task.scope,
            worker_id=task.worker_id,
            input_artifact_ids=task.input_artifact_ids,
            selection_version=task.selection_version,
        )
        for name in sorted(_task_tool_names(role, task.scope)):
            contextual_builder = self.contextual_tool_builders.get(name)
            builder = self.tool_builders.get(name)
            if contextual_builder is None and builder is None:
                continue
            if state.limits.max_cny is not None and name not in self.tool_reserved_cny:
                raise ValueError(f"tool price is not configured: {name}")
            if contextual_builder is not None:
                inner = contextual_builder(context)
            elif builder is not None:
                inner = builder()
            else:  # pragma: no cover - guarded above for type narrowing
                continue
            inner.context = registry.context
            registry.register(
                BudgetedTool(
                    inner,
                    tool_budget,
                    task_id=task_id,
                    attempt=attempt,
                    reserved_cny=self.tool_reserved_cny.get(name),
                )
            )
        config = AgentConfig(
            max_loops=24 if role is AgentRole.A0 else 12,
            total_timeout=1200 if role is AgentRole.A0 else 120,
            token_budget=state.limits.max_tokens,
            max_retries=1,
        )
        framework_factory = AgentFactory(
            provider=provider,
            config=config,
            tool_registry=registry,
            inject_skill_info=skill_manager is not None,
        )
        examples = demonstration_messages(runtime.demonstrations)
        if role is AgentRole.A0:
            return framework_factory.create_parent_agent(
                system_prompt=runtime.prompt, example_messages=examples
            )
        max_loops, total_timeout = _subagent_limits(role, task.scope)
        return framework_factory.create_sub_agent(
            system_prompt=runtime.prompt,
            max_loops=max_loops,
            total_timeout=total_timeout,
            example_messages=examples,
        )
