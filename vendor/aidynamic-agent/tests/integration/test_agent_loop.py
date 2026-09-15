"""Integration tests - agent loop with mock LLM."""

import pytest

from aidynamic_agent.agents.factory import AgentFactory
from aidynamic_agent.core.agent import AgentConfig, TerminationReason
from aidynamic_agent.core.message import FinishReason, TextBlock, ToolUseBlock
from aidynamic_agent.tools.registry import ToolRegistry
from tests.mocks.mock_llm import MockLLMProvider, MockResponseConfig
from tests.mocks.mock_tools import MockTool


class TestAgentLoop:
    """Test the full agent loop with mock LLM and tools."""

    @pytest.mark.asyncio
    async def test_text_only_response_ends_loop(self):
        """Text-only response should end the loop immediately."""
        provider = MockLLMProvider()
        provider.set_responses(
            [
                MockResponseConfig(content=[TextBlock(text="Hello there!")]),
            ]
        )
        registry = ToolRegistry()
        factory = AgentFactory(provider=provider, tool_registry=registry)
        agent = factory.create_parent_agent(system_prompt="You are helpful.")

        result = await agent.run("Say hello")
        assert result.termination_reason == TerminationReason.END_TURN
        assert "Hello there!" in result.text
        assert result.loops_used == 1

    @pytest.mark.asyncio
    async def test_tool_use_then_end_turn(self):
        """Tool use followed by end_turn should complete successfully."""
        tool = MockTool(response="tool output")
        provider = MockLLMProvider()
        provider.set_responses(
            [
                MockResponseConfig(
                    content=[
                        ToolUseBlock(
                            tool_call_id="call_1",
                            tool_name="mock_tool",
                            tool_input={"input": "test"},
                        )
                    ],
                    stop_reason=FinishReason.TOOL_USE,
                ),
                MockResponseConfig(
                    content=[TextBlock(text="Done!")],
                    stop_reason=FinishReason.END_TURN,
                ),
            ]
        )
        registry = ToolRegistry()
        registry.register(tool)

        factory = AgentFactory(provider=provider, tool_registry=registry)
        agent = factory.create_parent_agent(system_prompt="You are helpful.")

        result = await agent.run("Do something")
        assert result.termination_reason == TerminationReason.END_TURN
        assert "Done!" in result.text
        assert result.loops_used == 2

    @pytest.mark.asyncio
    async def test_max_loops_termination(self):
        """Agent should stop after max_loops."""
        tool = MockTool(response="ok")
        provider = MockLLMProvider()
        # Keep returning tool_use to force more loops
        for i in range(10):
            provider.response_sequence.append(
                MockResponseConfig(
                    content=[
                        ToolUseBlock(
                            tool_call_id=f"call_{i}",
                            tool_name="mock_tool",
                            tool_input={"input": "loop"},
                        )
                    ],
                    stop_reason=FinishReason.TOOL_USE,
                ),
            )
        registry = ToolRegistry()
        registry.register(tool)

        config = AgentConfig(max_loops=5)
        factory = AgentFactory(provider=provider, config=config, tool_registry=registry)
        agent = factory.create_parent_agent()

        result = await agent.run("keep going")
        assert result.termination_reason == TerminationReason.MAX_LOOPS
        assert result.loops_used == 5

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_all_execute(self):
        """Multiple tool calls in one response should all execute."""
        tool = MockTool(response="result")
        provider = MockLLMProvider()
        provider.set_responses(
            [
                MockResponseConfig(
                    content=[
                        ToolUseBlock(
                            tool_call_id="c1", tool_name="mock_tool", tool_input={"input": "a"}
                        ),
                        ToolUseBlock(
                            tool_call_id="c2", tool_name="mock_tool", tool_input={"input": "b"}
                        ),
                    ],
                    stop_reason=FinishReason.TOOL_USE,
                ),
                MockResponseConfig(
                    content=[TextBlock(text="All done")],
                ),
            ]
        )
        registry = ToolRegistry()
        registry.register(tool)

        factory = AgentFactory(provider=provider, tool_registry=registry)
        agent = factory.create_parent_agent()

        result = await agent.run("Do two things")
        assert result.termination_reason == TerminationReason.END_TURN
        assert tool.call_count == 2
