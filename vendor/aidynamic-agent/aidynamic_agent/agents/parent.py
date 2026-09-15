"""ParentAgent - concrete agent extending BaseAgent with LLM and tool implementations."""

from __future__ import annotations

from aidynamic_agent.core.agent import (
    AgentConfig,
    BaseAgent,
    TerminationReason,
)
from aidynamic_agent.core.message import (
    Message,
    Role,
    ToolResultBlock,
    ToolUseBlock,
)
from aidynamic_agent.hooks.base import HookEvent, HookExecutor
from aidynamic_agent.llm.base import LLMProvider, LLMResponse
from aidynamic_agent.tools.registry import ToolRegistry


class HookBlockedException(Exception):
    """Raised when a hook blocks execution."""

    def __init__(self, event: HookEvent, message: str = "Execution blocked by hook"):
        self.event = event
        super().__init__(message)


class ParentAgent(BaseAgent):
    """Concrete parent agent with real LLM calls and tool execution.

    Extends BaseAgent with:
    - _call_llm: calls provider.create() with context messages and tool definitions
    - _execute_tools: iterates tool calls, executes via registry, adds results to context
    - Hook integration: fires BEFORE/AFTER hooks for LLM and tool operations
    """

    def __init__(
        self,
        config: AgentConfig,
        provider: LLMProvider,
        tool_registry: ToolRegistry,
        hook_executor: HookExecutor | None = None,
    ):
        super().__init__(config)
        self.provider = provider
        self.tool_registry = tool_registry
        self.hook_executor = hook_executor

    # ------------------------------------------------------------------
    # Override _check_termination_conditions to fire BEFORE_LLM_CALL hook
    # ------------------------------------------------------------------

    async def _check_termination_conditions(self, iteration: int) -> TerminationReason | None:
        """Check termination + fire BEFORE_LLM_CALL hook.

        If the BEFORE_LLM_CALL hook blocks, return HOOK_BLOCKED immediately.
        """
        # First check standard conditions (timeout, token budget)
        result = await super()._check_termination_conditions(iteration)
        if result:
            return result

        # Fire BEFORE_LLM_CALL hook as part of iteration check
        if self.hook_executor:
            hook_ctx = await self.hook_executor.execute(
                HookEvent.BEFORE_LLM_CALL,
                {
                    "messages": self.context.messages if self.context else [],
                    "iteration": iteration,
                },
            )
            if hook_ctx.blocked:
                return TerminationReason.HOOK_BLOCKED

        return None

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------

    async def _call_llm(self) -> LLMResponse:
        """Call the LLM provider with context messages and tool definitions.

        Fires AFTER_LLM_CALL hook after receiving the response.
        BEFORE_LLM_CALL is fired in _check_termination_conditions so that
        blocking can produce TerminationReason.HOOK_BLOCKED.
        """
        # Build tool definitions for available tools
        tool_defs = self.tool_registry.to_tool_definitions(self.config.allowed_tool_tags)

        context = await self._ensure_context()
        response = await self.provider.create(context.messages, tools=tool_defs)

        # Track token usage
        if response.usage and "total_tokens" in response.usage:
            self.tokens_used += response.usage["total_tokens"]

        # Fire AFTER_LLM_CALL hook
        if self.hook_executor:
            await self.hook_executor.execute(HookEvent.AFTER_LLM_CALL, {"response": response})

        return response

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def _execute_tools(self, tool_calls: list[ToolUseBlock]) -> None:
        """Execute tool calls from the LLM response.

        For each tool call:
        1. Fire BEFORE_TOOL_EXEC hook; if blocked, add error result and skip
        2. Look up tool in registry and execute
        3. Fire AFTER_TOOL_EXEC hook
        4. Add ToolResultBlock to context
        """
        for tc in tool_calls:
            tool_name = tc.tool_name
            tool_input = tc.tool_input
            tool_call_id = tc.tool_call_id

            # Fire BEFORE_TOOL_EXEC hook
            if self.hook_executor:
                hook_ctx = await self.hook_executor.execute(
                    HookEvent.BEFORE_TOOL_EXEC,
                    {
                        "tool_name": tool_name,
                        "tool_input": tool_input,
                        "tool_call_id": tool_call_id,
                    },
                )
                if hook_ctx.blocked:
                    # Add error ToolResultBlock instead of executing
                    await self._add_tool_result(
                        tool_call_id=tool_call_id,
                        content=f"Tool execution blocked by hook: {tool_name}",
                        is_error=True,
                    )
                    continue

            # Look up and execute the tool
            result_content: str
            is_error: bool

            tool = self.tool_registry.get(tool_name)
            if tool is None or tool not in self.tool_registry.list_available(
                self.config.allowed_tool_tags
            ):
                result_content = f"Tool not found or not allowed: {tool_name}"
                is_error = True
            else:
                try:
                    result = await tool.run(**tool_input)
                    result_content = result.content
                    is_error = not result.success
                except Exception as e:
                    result_content = f"Tool error: {e}"
                    is_error = True
                    self._record_error(
                        "tool_error",
                        str(e),
                        iteration=0,
                        tool_name=tool_name,
                        recoverable=False,
                    )

            # Fire AFTER_TOOL_EXEC hook
            if self.hook_executor:
                await self.hook_executor.execute(
                    HookEvent.AFTER_TOOL_EXEC,
                    {
                        "tool_name": tool_name,
                        "tool_call_id": tool_call_id,
                        "result": result_content,
                        "is_error": is_error,
                    },
                )

            # Add result to context
            await self._add_tool_result(
                tool_call_id=tool_call_id,
                content=result_content,
                is_error=is_error,
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _add_tool_result(self, tool_call_id: str, content: str, is_error: bool) -> None:
        """Add a ToolResultBlock to the context.

        Uses Role.USER (Anthropic standard). OpenAI adapter will convert
        to role: "tool" when communicating with OpenAI-compatible APIs.
        """
        context = await self._ensure_context()
        await context.add_message(
            Message(
                role=Role.USER,
                content=[
                    ToolResultBlock(
                        tool_call_id=tool_call_id,
                        tool_result_content=content,
                        is_error=is_error,
                    )
                ],
            )
        )
