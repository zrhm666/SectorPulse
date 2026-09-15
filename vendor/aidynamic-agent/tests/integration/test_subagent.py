"""Integration tests for subagent creation and tool filtering."""

import pytest

from aidynamic_agent.agents.factory import AgentFactory
from aidynamic_agent.tools.base import Tool, ToolResult
from aidynamic_agent.tools.registry import ToolRegistry
from tests.mocks.mock_llm import MockLLMProvider


class ParentOnlyTool(Tool):
    """A tool that should only be available to parent agents."""

    name = "parent_only_tool"
    description = "Only for parent agents"
    parameters = {"type": "object", "properties": {}, "required": []}
    tags = ["parent_only"]

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(content="parent executed")


class CommonTool(Tool):
    """A tool available to both parent and sub agents."""

    name = "common_tool"
    description = "Available to all agents"
    parameters = {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(content="common executed")


class TestSubAgent:
    """Test subagent behavior and tool filtering."""

    @pytest.mark.asyncio
    async def test_subagent_has_filtered_tools(self):
        """Sub-agents should not have parent_only tools."""
        parent_tool = ParentOnlyTool()
        common_tool = CommonTool()

        registry = ToolRegistry()
        registry.register(parent_tool)
        registry.register(common_tool)

        provider = MockLLMProvider()
        factory = AgentFactory(provider=provider, tool_registry=registry)

        sub_agent = factory.create_sub_agent(system_prompt="You are a sub-agent.")

        tool_names = [t.name for t in sub_agent.tool_registry.list_all()]
        assert "common_tool" in tool_names
        assert "parent_only_tool" not in tool_names

    @pytest.mark.asyncio
    async def test_parent_agent_has_all_tools(self):
        """Parent agents should have all tools including parent_only."""
        parent_tool = ParentOnlyTool()
        common_tool = CommonTool()

        registry = ToolRegistry()
        registry.register(parent_tool)
        registry.register(common_tool)

        provider = MockLLMProvider()
        factory = AgentFactory(provider=provider, tool_registry=registry)

        parent_agent = factory.create_parent_agent(system_prompt="You are the parent.")

        tool_names = [t.name for t in parent_agent.tool_registry.list_all()]
        assert "common_tool" in tool_names
        assert "parent_only_tool" in tool_names

    @pytest.mark.asyncio
    async def test_subagent_has_tighter_limits(self):
        """Sub-agents should have lower max_loops and timeout."""
        provider = MockLLMProvider()
        factory = AgentFactory(provider=provider)

        sub_agent = factory.create_sub_agent()

        assert sub_agent.config.max_loops == 10
        assert sub_agent.config.total_timeout == 120

    @pytest.mark.asyncio
    async def test_subagent_can_override_limits(self):
        """Caller can override sub-agent defaults."""
        provider = MockLLMProvider()
        factory = AgentFactory(provider=provider)

        sub_agent = factory.create_sub_agent(max_loops=5)

        assert sub_agent.config.max_loops == 5
        assert sub_agent.config.total_timeout == 120  # Default preserved
