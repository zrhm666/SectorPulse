"""Legacy compatibility layer.

Provides adapters to run the old-style Hermes agent loop with the new OOP architecture.
This allows a gradual migration path -- old code paths can wrap the new agent and
still expose the same external interfaces.
"""

from __future__ import annotations

import json
from typing import Any

from aidynamic_agent.core.agent import AgentConfig, AgentResult, BaseAgent
from aidynamic_agent.hooks.base import HookExecutor
from aidynamic_agent.llm.base import LLMProvider
from aidynamic_agent.tools.registry import ToolRegistry


class LegacyAgentAdapter:
    """Wraps a new-style BaseAgent to expose legacy-compatible methods.

    Legacy callers expect:
    - async run(input: str) -> dict (JSON-like result)
    - .context.messages (raw list access)
    - Tool execution via a flat registry
    """

    def __init__(
        self,
        agent: BaseAgent,
    ):
        self.agent = agent

    async def run(self, user_input: str) -> dict[str, Any]:
        """Run the agent and return a legacy-style dict result."""
        result: AgentResult = await self.agent.run(user_input)
        return {
            "text": result.text,
            "termination_reason": result.termination_reason.value,
            "loops_used": result.loops_used,
            "tokens_used": result.tokens_used,
            "time_elapsed": round(result.time_elapsed, 2),
            "error": result.error,
            "error_detail": [
                {
                    "error_type": e.error_type,
                    "message": e.message,
                    "loop_iteration": e.loop_iteration,
                    "tool_name": e.tool_name,
                    "recoverable": e.recoverable,
                }
                for e in result.error_detail
            ],
        }

    @property
    def messages(self) -> list:
        """Access the underlying context messages for legacy inspection."""
        if self.agent.context is None:
            return []
        return self.agent.context.messages


class LegacyToolAdapter:
    """Adapt old-style tool dict format to new ToolRegistry tools.

    Old format:
        {"name": "...", "execute": async_fn, "description": "..."}
    New format:
        Tool subclass with execute() method
    """

    @staticmethod
    def adapt_tool(
        name: str,
        execute_fn,
        description: str = "",
        parameters: dict | None = None,
        tags: list[str] | None = None,
    ) -> type:
        """Create a Tool subclass from an old-style function.

        Args:
            name: Tool name
            execute_fn: async function that takes **kwargs and returns a dict
            description: Tool description
            parameters: JSON Schema for parameters
            tags: Permission tags
        """
        from aidynamic_agent.tools.base import Tool, ToolResult

        class _AdaptedTool(Tool):
            _name = name
            _desc = description
            _params = parameters or {}
            _tags = tags or []
            _fn = execute_fn

            async def execute(self, **kwargs) -> ToolResult:
                raw = await self._fn(**kwargs)
                if isinstance(raw, dict):
                    return ToolResult(
                        content=json.dumps(raw, indent=2)
                        if not isinstance(raw.get("content"), str)
                        else raw.get("content", ""),
                        success=raw.get("success", True),
                        error=raw.get("error"),
                        metadata={
                            k: v for k, v in raw.items() if k not in ("content", "success", "error")
                        },
                    )
                return ToolResult(content=str(raw))

        _AdaptedTool.name = name
        _AdaptedTool.description = description
        _AdaptedTool.parameters = parameters or {}
        _AdaptedTool.tags = tags or []
        return _AdaptedTool


def build_legacy_agent(
    provider: LLMProvider,
    config: AgentConfig | None = None,
    tool_registry: ToolRegistry | None = None,
    hook_executor: HookExecutor | None = None,
) -> LegacyAgentAdapter:
    """Build a legacy-compatible agent from new components.

    This is the main entry point for code that previously created agents
    through the old system.
    """
    from aidynamic_agent.agents.factory import AgentFactory

    factory = AgentFactory(
        provider=provider,
        config=config or AgentConfig(),
        tool_registry=tool_registry,
        hook_executor=hook_executor,
    )

    parent = factory.create_parent_agent()
    return LegacyAgentAdapter(parent)
