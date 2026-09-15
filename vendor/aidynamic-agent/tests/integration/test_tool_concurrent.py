"""Integration tests for tool concurrent execution."""

import asyncio

import pytest

from aidynamic_agent.agents.factory import AgentFactory
from aidynamic_agent.core.agent import TerminationReason
from aidynamic_agent.core.message import FinishReason, TextBlock, ToolUseBlock
from aidynamic_agent.tools.base import Tool, ToolResult
from aidynamic_agent.tools.registry import ToolRegistry
from tests.mocks.mock_llm import MockLLMProvider, MockResponseConfig
from tests.mocks.mock_tools import MockToolWithError


class SlowTool(Tool):
    """A tool that simulates slow execution."""

    name = "slow_tool"
    description = "A slow tool"
    parameters = {"type": "object", "properties": {"delay": {"type": "number"}}, "required": []}

    async def execute(self, delay: float = 0.5, **kwargs) -> ToolResult:
        await asyncio.sleep(delay)
        return ToolResult(content=f"Slept {delay}s")


class TestToolConcurrent:
    """Test tool execution timing."""

    @pytest.mark.asyncio
    async def test_multiple_slow_tools_execute(self):
        """Multiple slow tools should all complete (currently sequential)."""
        tool = SlowTool()
        provider = MockLLMProvider()
        provider.set_responses(
            [
                MockResponseConfig(
                    content=[
                        ToolUseBlock(
                            tool_call_id="c1", tool_name="slow_tool", tool_input={"delay": 0.1}
                        ),
                        ToolUseBlock(
                            tool_call_id="c2", tool_name="slow_tool", tool_input={"delay": 0.1}
                        ),
                        ToolUseBlock(
                            tool_call_id="c3", tool_name="slow_tool", tool_input={"delay": 0.1}
                        ),
                    ],
                    stop_reason=FinishReason.TOOL_USE,
                ),
                MockResponseConfig(content=[TextBlock(text="Done")]),
            ]
        )
        registry = ToolRegistry()
        registry.register(tool)

        factory = AgentFactory(provider=provider, tool_registry=registry)
        agent = factory.create_parent_agent()

        result = await agent.run("Do 3 slow things")
        assert result.termination_reason == TerminationReason.END_TURN

    @pytest.mark.asyncio
    async def test_concurrent_tool_errors_all_reported(self):
        """When multiple tools fail, all errors should be handled."""
        failing_tool = MockToolWithError(error_message="boom")
        provider = MockLLMProvider()
        provider.set_responses(
            [
                MockResponseConfig(
                    content=[
                        ToolUseBlock(tool_call_id="c1", tool_name="mock_tool_error", tool_input={}),
                        ToolUseBlock(tool_call_id="c2", tool_name="mock_tool_error", tool_input={}),
                    ],
                    stop_reason=FinishReason.TOOL_USE,
                ),
                MockResponseConfig(content=[TextBlock(text="Done")]),
            ]
        )
        registry = ToolRegistry()
        registry.register(failing_tool)

        factory = AgentFactory(provider=provider, tool_registry=registry)
        agent = factory.create_parent_agent()

        result = await agent.run("Do two failing things")
        assert result.termination_reason == TerminationReason.END_TURN
        # Agent should continue even with tool errors
