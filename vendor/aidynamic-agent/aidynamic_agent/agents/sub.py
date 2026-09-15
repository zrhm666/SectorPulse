"""SubAgent extends BaseAgent with sub-agent specific behavior.

Provides shorter default timeouts, limited tool access (excludes 'parent_only'
tagged tools and blocks TaskTool), and a communication protocol via
SubAgentRequest / SubAgentResponse.
"""

from __future__ import annotations

from dataclasses import dataclass

from aidynamic_agent.core.agent import (
    AgentConfig,
    AgentResult,
    BaseAgent,
    TerminationReason,
)
from aidynamic_agent.core.message import Message, Role, ToolResultBlock
from aidynamic_agent.hooks.base import HookEvent, HookExecutor
from aidynamic_agent.llm.base import LLMProvider, LLMResponse
from aidynamic_agent.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Communication protocol dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SubAgentRequest:
    """Request sent to a sub-agent to perform a delegated task."""

    task_description: str
    context_files: list[str] | None = None
    constraints: dict | None = None


@dataclass
class SubAgentResponse:
    """Response returned by a sub-agent after completing a task."""

    success: bool
    result_text: str
    termination_reason: TerminationReason
    error: str | None = None


# ---------------------------------------------------------------------------
# SubAgent
# ---------------------------------------------------------------------------


class SubAgent(BaseAgent):
    """Sub-agent with restricted tool access and shorter timeouts.

    Extends BaseAgent with:
    - Default shorter config (max_loops=10, total_timeout=120, token_budget=50000)
    - Tool registry excludes 'parent_only' tagged tools
    - Cannot call TaskTool (delegation from sub-agent not allowed)
    """

    DEFAULT_CONFIG = AgentConfig(
        max_loops=10,
        total_timeout=120,
        token_budget=50000,
    )

    # Tools that sub-agents are not allowed to invoke
    FORBIDDEN_TOOL_NAMES: frozenset[str] = frozenset({"task"})

    def __init__(
        self,
        config: AgentConfig | None = None,
        provider: LLMProvider | None = None,
        tool_registry: ToolRegistry | None = None,
        hook_executor: HookExecutor | None = None,
    ) -> None:
        merged_config = config or AgentConfig(
            max_loops=self.DEFAULT_CONFIG.max_loops,
            total_timeout=self.DEFAULT_CONFIG.total_timeout,
            token_budget=self.DEFAULT_CONFIG.token_budget,
        )
        super().__init__(merged_config)

        self.provider = provider
        self.tool_registry = tool_registry or ToolRegistry()
        self.hook_executor = hook_executor or HookExecutor()

    # -- helpers ----------------------------------------------------------

    def _get_available_tools(self) -> list:
        """Return tools available to the sub-agent, excluding 'parent_only'
        tagged tools and any tools in FORBIDDEN_TOOL_NAMES (e.g. task)."""
        all_tools = self.tool_registry.list_available(self.config.allowed_tool_tags)
        return [
            t
            for t in all_tools
            if "parent_only" not in t.tags and t.name not in self.FORBIDDEN_TOOL_NAMES
        ]

    def _is_tool_allowed(self, tool_name: str) -> bool:
        """Check whether a given tool name is permitted for sub-agents."""
        if tool_name in self.FORBIDDEN_TOOL_NAMES:
            return False
        tool = self.tool_registry.get(tool_name)
        if tool is None:
            return False
        if "parent_only" in tool.tags:
            return False
        return tool in self.tool_registry.list_available(self.config.allowed_tool_tags)

    # -- abstract implementations -----------------------------------------

    async def _call_llm(self) -> LLMResponse:
        """Call the LLM provider with the current context messages and
        available sub-agent tools."""
        if self.context is None:
            raise RuntimeError("SubAgent called _call_llm but context is not initialised")

        # Build hook context for BEFORE_LLM_CALL
        if self.hook_executor is not None:
            hook_ctx = await self.hook_executor.execute(
                HookEvent.BEFORE_LLM_CALL,
                data={"agent_type": "sub"},
            )
            if hook_ctx.blocked:
                self._record_error(
                    "hook_error",
                    "LLM call blocked by hook",
                    self.context.loop_count if hasattr(self.context, "loop_count") else 0,
                    recoverable=False,
                )
                raise RuntimeError("LLM call blocked by hook")

        if self.provider is None:
            raise RuntimeError("SubAgent called _call_llm but no provider was set")

        tool_defs = [t.to_tool_definition() for t in self._get_available_tools()]
        response: LLMResponse = await self.provider.create(
            messages=self.context.messages,
            tools=tool_defs if tool_defs else None,
        )

        if response.usage and "total_tokens" in response.usage:
            self.tokens_used += response.usage["total_tokens"]

        # AFTER_LLM_CALL hook
        if self.hook_executor is not None:
            await self.hook_executor.execute(
                HookEvent.AFTER_LLM_CALL,
                data={"stop_reason": response.stop_reason.value},
            )

        return response

    async def _execute_tools(self, tool_calls: list) -> None:
        """Execute tool calls, adding results to the conversation context.

        Skips tools that are not allowed for sub-agents (parent_only tagged
        or explicitly forbidden like TaskTool)."""
        if self.context is None:
            raise RuntimeError("SubAgent called _execute_tools but context is not initialised")

        for tool_call in tool_calls:
            tool_name = (
                tool_call.tool_name if hasattr(tool_call, "tool_name") else tool_call.get("name")
            )
            tool_input = (
                tool_call.tool_input
                if hasattr(tool_call, "tool_input")
                else tool_call.get("input", {})
            )
            tool_call_id = (
                tool_call.tool_call_id
                if hasattr(tool_call, "tool_call_id")
                else tool_call.get("id", "")
            )

            if not self._is_tool_allowed(tool_name):
                # Inject an error result for forbidden tools
                block = ToolResultBlock(
                    tool_call_id=tool_call_id,
                    tool_result_content=f"Error: tool '{tool_name}' is not available to sub-agents",
                    is_error=True,
                )
                await self.context.add_message(
                    Message(role=Role.ASSISTANT, content=[])  # placeholder
                )
                await self.context.add_message(
                    Message(
                        role=Role.USER,
                        content=[block],
                    )
                )
                self._record_error(
                    "tool_error",
                    f"Sub-agent attempted to call forbidden tool: {tool_name}",
                    self.context.loop_count if hasattr(self.context, "loop_count") else 0,
                    tool_name=tool_name,
                    recoverable=False,
                )
                continue

            # BEFORE_TOOL_EXEC hook
            if self.hook_executor is not None:
                hook_ctx = await self.hook_executor.execute(
                    HookEvent.BEFORE_TOOL_EXEC,
                    data={"tool_name": tool_name, "tool_input": tool_input},
                )
                if hook_ctx.blocked:
                    block = ToolResultBlock(
                        tool_call_id=tool_call_id,
                        tool_result_content="Tool execution blocked by hook",
                        is_error=True,
                    )
                    await self.context.add_message(Message(role=Role.USER, content=[block]))
                    continue

            tool = self.tool_registry.get(tool_name)
            if tool is None:
                block = ToolResultBlock(
                    tool_call_id=tool_call_id,
                    tool_result_content=f"Error: tool '{tool_name}' not found in registry",
                    is_error=True,
                )
                await self.context.add_message(Message(role=Role.USER, content=[block]))
                continue

            try:
                result = await tool.run(**tool_input)
            except Exception as e:
                result_content = f"Error executing tool '{tool_name}': {e}"
                block = ToolResultBlock(
                    tool_call_id=tool_call_id,
                    tool_result_content=result_content,
                    is_error=True,
                )
                self._record_error(
                    "tool_error",
                    result_content,
                    self.context.loop_count if hasattr(self.context, "loop_count") else 0,
                    tool_name=tool_name,
                    recoverable=True,
                )
                await self.context.add_message(Message(role=Role.USER, content=[block]))
                continue

            block = ToolResultBlock(
                tool_call_id=tool_call_id,
                tool_result_content=result.content,
                is_error=not result.success,
                history_key=getattr(result, "history_key", None),
            )
            await self.context.add_message(Message(role=Role.USER, content=[block]))

            # AFTER_TOOL_EXEC hook
            if self.hook_executor is not None:
                await self.hook_executor.execute(
                    HookEvent.AFTER_TOOL_EXEC,
                    data={"tool_name": tool_name, "success": result.success},
                )

    # -- public helpers ---------------------------------------------------

    def create_request(self, task_description: str, **kwargs) -> SubAgentRequest:
        """Convenience factory for building a SubAgentRequest."""
        return SubAgentRequest(task_description=task_description, **kwargs)

    @staticmethod
    def build_response(result: AgentResult) -> SubAgentResponse:
        """Build a SubAgentResponse from an AgentResult."""
        return SubAgentResponse(
            success=result.termination_reason == TerminationReason.END_TURN,
            result_text=result.text,
            termination_reason=result.termination_reason,
            error=result.error,
        )
