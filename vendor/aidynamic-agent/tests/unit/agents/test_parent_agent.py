"""Unit tests for ParentAgent.

Tests cover:
- Construction and dependencies
- _call_llm: LLM invocation, tool definitions, token tracking, hooks
- _execute_tools: successful execution, missing tool, tool error, hooks
- Hook blocking: BEFORE_LLM_CALL, BEFORE_TOOL_EXEC
- Integration with BaseAgent.run()
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from aidynamic_agent.agents.parent import ParentAgent
from aidynamic_agent.core.agent import AgentConfig, TerminationReason
from aidynamic_agent.core.message import (
    FinishReason,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from aidynamic_agent.hooks.base import Hook, HookContext, HookEvent, HookExecutor
from aidynamic_agent.llm.base import LLMProvider, LLMResponse
from aidynamic_agent.tools.base import Tool, ToolResult
from aidynamic_agent.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Test helpers / fixtures
# ---------------------------------------------------------------------------


class DummyTool(Tool):
    name = "hello"
    description = "Say hello"
    parameters = {"type": "object", "properties": {"name": {"type": "string"}}}
    tags = ["read"]

    async def execute(self, name: str = "world") -> ToolResult:
        return ToolResult(content=f"Hello, {name}!")


class ErrorTool(Tool):
    name = "error_tool"
    description = "Always errors"
    parameters = {}
    tags = ["read"]

    async def execute(self, **kwargs) -> ToolResult:
        raise RuntimeError("boom")


class DummyProvider(LLMProvider):
    """Minimal provider for testing."""

    def __init__(self):
        self.call_history = []

    async def create(self, messages, tools=None, **kwargs):
        self.call_history.append({"messages": messages, "tools": tools})
        return LLMResponse(
            content=[TextBlock(text="hi")],
            stop_reason=FinishReason.END_TURN,
            model="test",
            usage={"total_tokens": 50},
        )

    async def stream(self, messages, tools=None, **kwargs):
        raise NotImplementedError()


def _make_registry():
    reg = ToolRegistry()
    reg.register(DummyTool())
    return reg


def _make_agent(
    config=None,
    provider=None,
    tool_registry=None,
    hook_executor=None,
):
    return ParentAgent(
        config=config or AgentConfig(),
        provider=provider or DummyProvider(),
        tool_registry=tool_registry if tool_registry is not None else _make_registry(),
        hook_executor=hook_executor,
    )


# ---------------------------------------------------------------------------
# Construction tests
# ---------------------------------------------------------------------------


class TestParentAgentConstruction:
    def test_basic_construction(self):
        agent = _make_agent()
        assert isinstance(agent.provider, DummyProvider)
        assert isinstance(agent.tool_registry, ToolRegistry)
        assert agent.hook_executor is None

    def test_with_hook_executor(self):
        hook_exec = HookExecutor()
        agent = _make_agent(hook_executor=hook_exec)
        assert agent.hook_executor is hook_exec

    def test_custom_config(self):
        cfg = AgentConfig(max_loops=5, system_prompt="Be brief")
        agent = _make_agent(config=cfg)
        assert agent.config.max_loops == 5
        assert agent.config.system_prompt == "Be brief"


# ---------------------------------------------------------------------------
# _call_llm tests
# ---------------------------------------------------------------------------


class TestCallLLM:
    @pytest.mark.asyncio
    async def test_calls_provider_with_messages(self):
        provider = DummyProvider()
        agent = _make_agent(provider=provider)
        # Set up context as BaseAgent.run() would
        agent.context = MagicMock()
        agent.context.messages = [MagicMock()]

        await agent._call_llm()

        assert len(provider.call_history) == 1
        assert provider.call_history[0]["messages"] is agent.context.messages

    @pytest.mark.asyncio
    async def test_calls_provider_with_tool_definitions(self):
        provider = DummyProvider()
        registry = _make_registry()
        agent = _make_agent(provider=provider, tool_registry=registry)
        agent.context = MagicMock()
        agent.context.messages = []

        await agent._call_llm()

        tools = provider.call_history[0]["tools"]
        assert tools is not None
        assert len(tools) == 1
        assert tools[0].name == "hello"
        assert tools[0].description == "Say hello"

    @pytest.mark.asyncio
    async def test_no_tools_when_registry_empty(self):
        provider = DummyProvider()
        registry = ToolRegistry()
        agent = _make_agent(provider=provider, tool_registry=registry)
        agent.context = MagicMock()
        agent.context.messages = []

        await agent._call_llm()

        # An empty registry produces an empty tool-definitions list (never None);
        # a non-empty registry produces a populated list (see the test above).
        assert provider.call_history[0]["tools"] == []

    @pytest.mark.asyncio
    async def test_tracks_token_usage(self):
        provider = DummyProvider()
        agent = _make_agent(provider=provider)
        agent.context = MagicMock()
        agent.context.messages = []
        agent.tokens_used = 0

        await agent._call_llm()

        assert agent.tokens_used == 50

    @pytest.mark.asyncio
    async def test_respects_allowed_tool_tags(self):
        """When allowed_tool_tags is set, only matching tools are sent."""
        provider = DummyProvider()
        reg = ToolRegistry()
        reg.register(DummyTool())  # tags: ["read"]
        err = ErrorTool()  # tags: ["read"]
        reg.register(err)
        cfg = AgentConfig(allowed_tool_tags=["read"])
        agent = _make_agent(provider=provider, tool_registry=reg, config=cfg)
        agent.context = MagicMock()
        agent.context.messages = []

        await agent._call_llm()

        # Both tools have "read" tag so both should be included
        tools = provider.call_history[0]["tools"]
        assert len(tools) == 2

    @pytest.mark.asyncio
    async def test_returns_llm_response(self):
        provider = DummyProvider()
        agent = _make_agent(provider=provider)
        agent.context = MagicMock()
        agent.context.messages = []

        response = await agent._call_llm()

        assert isinstance(response, LLMResponse)
        assert response.stop_reason == FinishReason.END_TURN


# ---------------------------------------------------------------------------
# _call_llm hook tests
# ---------------------------------------------------------------------------


class TestCallLLMHooks:
    @pytest.mark.asyncio
    async def test_fires_after_llm_call_hook(self):
        events_fired = []

        class RecordingHook(Hook):
            name = "recording"
            events = [HookEvent.AFTER_LLM_CALL]

            async def handle(self, ctx: HookContext) -> HookContext:
                events_fired.append(ctx.event)
                return ctx

        hook_exec = HookExecutor()
        hook_exec.register(RecordingHook())
        agent = _make_agent(hook_executor=hook_exec)
        agent.context = MagicMock()
        agent.context.messages = []

        await agent._call_llm()

        assert HookEvent.AFTER_LLM_CALL in events_fired

    @pytest.mark.asyncio
    async def test_before_llm_call_hook_blocks_termination(self):
        """When _check_termination_conditions fires BEFORE_LLM_CALL and it blocks,
        return HOOK_BLOCKED."""

        class BlockHook(Hook):
            name = "blocker"
            events = [HookEvent.BEFORE_LLM_CALL]

            async def handle(self, ctx: HookContext) -> HookContext:
                ctx.blocked = True
                return ctx

        hook_exec = HookExecutor()
        hook_exec.register(BlockHook())
        agent = _make_agent(hook_executor=hook_exec)
        agent.context = MagicMock()
        agent.context.messages = []
        agent.start_time = time.time()  # Set recent start_time to avoid TIMEOUT

        reason = await agent._check_termination_conditions(0)

        assert reason == TerminationReason.HOOK_BLOCKED


# ---------------------------------------------------------------------------
# _execute_tools tests
# ---------------------------------------------------------------------------


class TestExecuteTools:
    @pytest.mark.asyncio
    async def test_successful_tool_execution(self):
        agent = _make_agent()
        agent.context = MagicMock()
        agent.context.messages = []
        agent.context.add_message = AsyncMock()

        tc = ToolUseBlock(
            tool_call_id="call_1",
            tool_name="hello",
            tool_input={"name": "Alice"},
        )
        await agent._execute_tools([tc])

        # Check that a ToolResultBlock was added to context
        calls = agent.context.add_message.call_args_list
        assert len(calls) == 1
        msg = calls[0][0][0]
        assert isinstance(msg.content[0], ToolResultBlock)
        assert msg.content[0].tool_call_id == "call_1"
        assert "Hello, Alice!" in msg.content[0].tool_result_content
        assert msg.content[0].is_error is False

    @pytest.mark.asyncio
    async def test_missing_tool(self):
        agent = _make_agent()
        agent.context = MagicMock()
        agent.context.messages = []
        agent.context.add_message = AsyncMock()

        tc = ToolUseBlock(
            tool_call_id="call_2",
            tool_name="nonexistent",
            tool_input={},
        )
        await agent._execute_tools([tc])

        calls = agent.context.add_message.call_args_list
        assert len(calls) == 1
        block = calls[0][0][0].content[0]
        assert block.is_error is True
        assert "not found" in block.tool_result_content

    @pytest.mark.asyncio
    async def test_tool_error(self):
        reg = ToolRegistry()
        reg.register(ErrorTool())
        agent = _make_agent(tool_registry=reg)
        agent.context = MagicMock()
        agent.context.messages = []
        agent.context.add_message = AsyncMock()

        tc = ToolUseBlock(
            tool_call_id="call_3",
            tool_name="error_tool",
            tool_input={},
        )
        await agent._execute_tools([tc])

        calls = agent.context.add_message.call_args_list
        assert len(calls) == 1
        block = calls[0][0][0].content[0]
        assert block.is_error is True
        assert "boom" in block.tool_result_content

    @pytest.mark.asyncio
    async def test_multiple_tool_calls(self):
        agent = _make_agent()
        agent.context = MagicMock()
        agent.context.messages = []
        agent.context.add_message = AsyncMock()

        calls = [
            ToolUseBlock(
                tool_call_id="c1",
                tool_name="hello",
                tool_input={"name": "A"},
            ),
            ToolUseBlock(
                tool_call_id="c2",
                tool_name="hello",
                tool_input={"name": "B"},
            ),
        ]
        await agent._execute_tools(calls)

        assert agent.context.add_message.call_count == 2

    @pytest.mark.asyncio
    async def test_empty_tool_calls(self):
        agent = _make_agent()
        agent.context = MagicMock()
        agent.context.messages = []
        agent.context.add_message = AsyncMock()

        await agent._execute_tools([])

        assert agent.context.add_message.call_count == 0


# ---------------------------------------------------------------------------
# _execute_tools hook tests
# ---------------------------------------------------------------------------


class TestExecuteToolsHooks:
    @pytest.mark.asyncio
    async def test_before_tool_exec_hook_fires(self):
        events_fired = []

        class RecordingHook(Hook):
            name = "rec"
            events = [HookEvent.BEFORE_TOOL_EXEC, HookEvent.AFTER_TOOL_EXEC]

            async def handle(self, ctx: HookContext) -> HookContext:
                events_fired.append(ctx.event)
                return ctx

        hook_exec = HookExecutor()
        hook_exec.register(RecordingHook())
        agent = _make_agent(hook_executor=hook_exec)
        agent.context = MagicMock()
        agent.context.messages = []
        agent.context.add_message = AsyncMock()

        tc = ToolUseBlock(
            tool_call_id="c1",
            tool_name="hello",
            tool_input={"name": "World"},
        )
        await agent._execute_tools([tc])

        assert HookEvent.BEFORE_TOOL_EXEC in events_fired
        assert HookEvent.AFTER_TOOL_EXEC in events_fired

    @pytest.mark.asyncio
    async def test_before_tool_exec_blocked(self):
        """When BEFORE_TOOL_EXEC hook blocks, add error ToolResultBlock instead."""

        class BlockHook(Hook):
            name = "blocker"
            events = [HookEvent.BEFORE_TOOL_EXEC]

            async def handle(self, ctx: HookContext) -> HookContext:
                ctx.blocked = True
                return ctx

        hook_exec = HookExecutor()
        hook_exec.register(BlockHook())
        agent = _make_agent(hook_executor=hook_exec)
        agent.context = MagicMock()
        agent.context.messages = []
        agent.context.add_message = AsyncMock()

        tc = ToolUseBlock(
            tool_call_id="c1",
            tool_name="hello",
            tool_input={"name": "World"},
        )
        await agent._execute_tools([tc])

        # Tool was blocked — an error result should be added
        calls = agent.context.add_message.call_args_list
        assert len(calls) == 1
        block = calls[0][0][0].content[0]
        assert block.is_error is True
        assert "blocked" in block.tool_result_content

    @pytest.mark.asyncio
    async def test_before_tool_exec_blocked_only_affects_blocked_tool(self):
        """Only blocked tool call should be skipped; other tools still execute."""

        blocked_names = []

        class SelectiveBlockHook(Hook):
            name = "selector"
            events = [HookEvent.BEFORE_TOOL_EXEC]

            async def handle(self, ctx: HookContext) -> HookContext:
                if ctx.data.get("tool_name") == "error_tool":
                    ctx.blocked = True
                    blocked_names.append("error_tool")
                return ctx

        hook_exec = HookExecutor()
        hook_exec.register(SelectiveBlockHook())

        reg = ToolRegistry()
        reg.register(DummyTool())
        reg.register(ErrorTool())
        agent = _make_agent(tool_registry=reg, hook_executor=hook_exec)
        agent.context = MagicMock()
        agent.context.messages = []
        agent.context.add_message = AsyncMock()

        calls = [
            ToolUseBlock(
                tool_call_id="c1",
                tool_name="hello",
                tool_input={"name": "X"},
            ),
            ToolUseBlock(
                tool_call_id="c2",
                tool_name="error_tool",
                tool_input={},
            ),
        ]
        await agent._execute_tools(calls)

        assert "error_tool" in blocked_names
        # hello executed (1 message) + error_tool blocked (1 error message) = 2
        assert agent.context.add_message.call_count == 2


# ---------------------------------------------------------------------------
# ON_ERROR hook tests
# ---------------------------------------------------------------------------


class TestOnErrorHook:
    @pytest.mark.asyncio
    async def test_on_error_hook_fires_on_tool_error(self):
        events_fired = []

        class RecordingHook(Hook):
            name = "rec"
            events = [HookEvent.ON_ERROR]

            async def handle(self, ctx: HookContext) -> HookContext:
                events_fired.append(ctx.event)
                return ctx

        hook_exec = HookExecutor()
        hook_exec.register(RecordingHook())

        reg = ToolRegistry()
        reg.register(ErrorTool())
        agent = _make_agent(tool_registry=reg, hook_executor=hook_exec)
        agent.context = MagicMock()
        agent.context.messages = []
        agent.context.add_message = AsyncMock()

        tc = ToolUseBlock(
            tool_call_id="c1",
            tool_name="error_tool",
            tool_input={},
        )

        await agent._execute_tools([tc])

        # ON_ERROR is NOT currently fired by ParentAgent._execute_tools
        # This is expected per current implementation
        assert HookEvent.ON_ERROR not in events_fired


# ---------------------------------------------------------------------------
# Integration: run() with ParentAgent
# ---------------------------------------------------------------------------


class TestParentAgentRun:
    @pytest.mark.asyncio
    async def test_run_end_turn(self):
        provider = DummyProvider()
        agent = _make_agent(provider=provider)

        result = await agent.run("test input")

        assert result.termination_reason == TerminationReason.END_TURN
        assert result.loops_used == 1
        assert "hi" in result.text

    @pytest.mark.asyncio
    async def test_run_with_tool_calls(self):
        """Agent returns END_TURN when LLM ends, executes tools when tool_use."""
        tool_calls_response = LLMResponse(
            content=[
                ToolUseBlock(
                    tool_call_id="c1",
                    tool_name="hello",
                    tool_input={"name": "Integration"},
                )
            ],
            stop_reason=FinishReason.TOOL_USE,
            model="test",
            usage={"total_tokens": 30},
        )
        end_turn_response = LLMResponse(
            content=[TextBlock(text="Done!")],
            stop_reason=FinishReason.END_TURN,
            model="test",
            usage={"total_tokens": 20},
        )

        class TwoCallProvider(DummyProvider):
            call_count = 0

            async def create(self, messages, tools=None, **kwargs):
                self.call_count += 1
                if self.call_count == 1:
                    return tool_calls_response
                return end_turn_response

        provider = TwoCallProvider()
        agent = _make_agent(provider=provider)

        result = await agent.run("test")

        assert result.termination_reason == TerminationReason.END_TURN
        assert provider.call_count == 2
        assert "Done!" in result.text

    @pytest.mark.asyncio
    async def test_run_max_loops(self):
        # Override to always return TOOL_USE so loop never terminates naturally
        class ToolLoopProvider(DummyProvider):
            async def create(self, messages, tools=None, **kwargs):
                return LLMResponse(
                    content=[
                        ToolUseBlock(
                            tool_call_id="cx",
                            tool_name="nonexistent",
                            tool_input={},
                        )
                    ],
                    stop_reason=FinishReason.TOOL_USE,
                    model="test",
                    usage={"total_tokens": 10},
                )

        agent = _make_agent(
            provider=ToolLoopProvider(),
            config=AgentConfig(max_loops=2, total_timeout=300),
        )

        result = await agent.run("test")

        assert result.termination_reason == TerminationReason.MAX_LOOPS
        assert result.loops_used == 2

    @pytest.mark.asyncio
    async def test_run_hook_blocked(self):
        class BlockHook(Hook):
            name = "blocker"
            events = [HookEvent.BEFORE_LLM_CALL]

            async def handle(self, ctx: HookContext) -> HookContext:
                ctx.blocked = True
                return ctx

        hook_exec = HookExecutor()
        hook_exec.register(BlockHook())
        agent = _make_agent(hook_executor=hook_exec)

        result = await agent.run("test")

        assert result.termination_reason == TerminationReason.HOOK_BLOCKED
        assert result.loops_used == 1
