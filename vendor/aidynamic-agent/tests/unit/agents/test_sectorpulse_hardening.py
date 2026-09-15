"""Security and lifecycle regressions for the embedded runtime."""

import asyncio

import pytest

from aidynamic_agent.agents.factory import AgentFactory
from aidynamic_agent.core.agent import AgentConfig, TerminationReason
from aidynamic_agent.core.message import FinishReason, TextBlock, ToolUseBlock
from aidynamic_agent.tools.base import Tool, ToolResult
from aidynamic_agent.tools.builtins.task import TaskTool
from aidynamic_agent.tools.registry import ToolRegistry
from tests.mocks.mock_llm import MockLLMProvider, MockResponseConfig


class MarketTool(Tool):
    name = "market"
    tags = ["market"]

    def __init__(self):
        super().__init__()
        self.effects = []

    async def execute(self, **kwargs):
        self.effects.append("queried")
        return ToolResult(content="snapshot")


def tool_response():
    return MockResponseConfig(
        content=[ToolUseBlock(tool_call_id="call-1", tool_name="market", tool_input={})],
        stop_reason=FinishReason.TOOL_USE,
    )


def fixture_factory(config=None):
    provider = MockLLMProvider()
    registry = ToolRegistry()
    market = MarketTool()
    registry.register(market)
    factory = AgentFactory(provider, config=config, tool_registry=registry)
    return factory, provider, market


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["parent", "sub"])
async def test_hidden_tool_cannot_be_executed_by_forged_model_call(role):
    factory, provider, market = fixture_factory(AgentConfig(allowed_tool_tags=["news"]))
    provider.set_responses([tool_response()])
    agent = (factory.create_parent_agent if role == "parent" else factory.create_sub_agent)()
    await agent.run("inspect news")
    assert market.effects == []
    results = [b for m in agent.context.messages for b in m.content if hasattr(b, "is_error")]
    assert any(b.is_error for b in results)


@pytest.mark.asyncio
async def test_delegation_toolsets_are_enforced_at_execution():
    factory, provider, market = fixture_factory()
    delegate = TaskTool(factory.tool_registry.context)
    provider.set_responses([tool_response()])
    await delegate.run(goal="inspect", toolsets=["news"])
    assert market.effects == []


@pytest.mark.asyncio
async def test_delegate_cannot_expand_parent_permissions():
    factory, provider, market = fixture_factory(AgentConfig(allowed_tool_tags=["news"]))
    provider.set_responses([tool_response()])
    await TaskTool(factory.tool_registry.context).run(goal="inspect", toolsets=["market"])
    assert market.effects == []


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["parent", "sub"])
async def test_token_limit_prevents_pending_tool_side_effect(role):
    factory, provider, market = fixture_factory(AgentConfig(token_budget=50))
    provider.set_responses([tool_response()])  # model usage is 100
    agent = (factory.create_parent_agent if role == "parent" else factory.create_sub_agent)()
    result = await agent.run("inspect")
    assert result.termination_reason == TerminationReason.TOKEN_BUDGET
    assert result.tokens_used == 100
    assert market.effects == []


class WaitingProvider(MockLLMProvider):
    async def create(self, *args, **kwargs):
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_timeout_interrupts_inflight_llm_without_waiting_for_next_loop():
    factory = AgentFactory(WaitingProvider(), config=AgentConfig(total_timeout=0.02))
    # Outer deadline catches the old broken implementation; production deadline must win.
    result = await asyncio.wait_for(factory.create_parent_agent().run("inspect"), timeout=0.5)
    assert result.termination_reason == TerminationReason.TIMEOUT


@pytest.mark.asyncio
async def test_task_reports_exhausted_subagent_as_failure():
    factory, provider, _ = fixture_factory()
    provider.set_responses(
        [
            MockResponseConfig(
                content=[TextBlock(text="continue")], stop_reason=FinishReason.MAX_TOKENS
            )
            for _ in range(10)
        ]
    )
    result = await TaskTool(factory.tool_registry.context).run(goal="inspect")
    assert result.success is False
    assert result.error


@pytest.mark.asyncio
async def test_task_without_requested_toolsets_keeps_allowed_tools():
    factory, provider, market = fixture_factory()
    provider.set_responses([tool_response()])
    result = await TaskTool(factory.tool_registry.context).run(goal="inspect")
    assert result.success is True
    assert market.effects == ["queried"]


@pytest.mark.asyncio
async def test_cancellation_propagates_instead_of_becoming_success():
    agent = AgentFactory(WaitingProvider()).create_parent_agent()
    task = asyncio.create_task(agent.run("inspect"))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
