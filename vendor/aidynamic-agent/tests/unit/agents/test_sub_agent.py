"""Unit tests for SubAgent, SubAgentRequest, and SubAgentResponse."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from aidynamic_agent.agents.sub import SubAgent, SubAgentRequest, SubAgentResponse
from aidynamic_agent.core.agent import AgentConfig, AgentResult, TerminationReason
from aidynamic_agent.core.message import FinishReason, TextBlock
from aidynamic_agent.hooks.base import HookEvent, HookExecutor
from aidynamic_agent.llm.base import LLMProvider, LLMResponse
from aidynamic_agent.tools.base import Tool, ToolResult
from aidynamic_agent.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Stub tool implementations for testing
# ---------------------------------------------------------------------------


class ReadFileTool(Tool):
    name = "read_file"
    description = "Read a file"
    parameters = {"type": "object", "properties": {"path": {"type": "string"}}}
    tags = ["read"]

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(content="file content", success=True)


class WriteFileTool(Tool):
    name = "write_file"
    description = "Write a file"
    parameters = {"type": "object", "properties": {"path": {"type": "string"}}}
    tags = ["write"]

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(content="written", success=True)


class ParentOnlyTool(Tool):
    name = "parent_only_tool"
    description = "Only parent agents can use this"
    parameters = {}
    tags = ["parent_only"]

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(content="should not reach here", success=True)


class TaskToolStub(Tool):
    """Stub mimicking the real TaskTool — sub-agents must NOT call this."""

    name = "task"
    description = "Delegate a task"
    parameters = {"type": "object", "properties": {"description": {"type": "string"}}}
    tags = ["delegation"]

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(content="delegated", success=True)


# ---------------------------------------------------------------------------
# SubAgentRequest tests
# ---------------------------------------------------------------------------


class TestSubAgentRequest:
    def test_minimal_construction(self):
        req = SubAgentRequest(task_description="summarize file")
        assert req.task_description == "summarize file"
        assert req.context_files is None
        assert req.constraints is None

    def test_full_construction(self):
        req = SubAgentRequest(
            task_description="fix bugs",
            context_files=["main.py", "utils.py"],
            constraints={"max_lines": 50},
        )
        assert req.task_description == "fix bugs"
        assert req.context_files == ["main.py", "utils.py"]
        assert req.constraints == {"max_lines": 50}


# ---------------------------------------------------------------------------
# SubAgentResponse tests
# ---------------------------------------------------------------------------


class TestSubAgentResponse:
    def test_success(self):
        resp = SubAgentResponse(
            success=True,
            result_text="done",
            termination_reason=TerminationReason.END_TURN,
        )
        assert resp.success is True
        assert resp.result_text == "done"
        assert resp.termination_reason == TerminationReason.END_TURN
        assert resp.error is None

    def test_with_error(self):
        resp = SubAgentResponse(
            success=False,
            result_text="",
            termination_reason=TerminationReason.ERROR,
            error="something broke",
        )
        assert resp.success is False
        assert resp.error == "something broke"


# ---------------------------------------------------------------------------
# SubAgent default config tests
# ---------------------------------------------------------------------------


class TestSubAgentDefaults:
    def test_default_config_values(self):
        agent = SubAgent()
        assert agent.config.max_loops == 10
        assert agent.config.total_timeout == 120
        assert agent.config.token_budget == 50000

    def test_custom_config_override(self):
        custom = AgentConfig(max_loops=5, total_timeout=30, token_budget=1000)
        agent = SubAgent(config=custom)
        assert agent.config.max_loops == 5
        assert agent.config.total_timeout == 30
        assert agent.config.token_budget == 1000


# ---------------------------------------------------------------------------
# SubAgent tool filtering tests
# ---------------------------------------------------------------------------


class TestSubAgentToolFiltering:
    def _make_registry(self) -> ToolRegistry:
        reg = ToolRegistry()
        reg.register(ReadFileTool())
        reg.register(WriteFileTool())
        reg.register(ParentOnlyTool())
        reg.register(TaskToolStub())
        return reg

    def test_excludes_parent_only_tools(self):
        reg = self._make_registry()
        agent = SubAgent(tool_registry=reg)
        available = agent._get_available_tools()
        names = [t.name for t in available]
        assert "read_file" in names
        assert "write_file" in names
        assert "parent_only_tool" not in names

    def test_excludes_task_tool(self):
        reg = self._make_registry()
        agent = SubAgent(tool_registry=reg)
        assert not agent._is_tool_allowed("task")

    def test_is_tool_allowed_regular_tool(self):
        reg = self._make_registry()
        agent = SubAgent(tool_registry=reg)
        assert agent._is_tool_allowed("read_file")
        assert agent._is_tool_allowed("write_file")

    def test_is_tool_allowed_unknown_tool(self):
        reg = self._make_registry()
        agent = SubAgent(tool_registry=reg)
        assert not agent._is_tool_allowed("nonexistent_tool")

    def test_is_tool_allowed_parent_only(self):
        reg = self._make_registry()
        agent = SubAgent(tool_registry=reg)
        assert not agent._is_tool_allowed("parent_only_tool")

    def test_forbidden_tool_names_constant(self):
        assert "task" in SubAgent.FORBIDDEN_TOOL_NAMES


# ---------------------------------------------------------------------------
# SubAgent _call_llm tests
# ---------------------------------------------------------------------------


class TestSubAgentCallLLM:
    def _setup(self) -> tuple[SubAgent, AsyncMock]:
        mock_provider = AsyncMock(spec=LLMProvider)
        mock_provider.create.return_value = LLMResponse(
            content=[TextBlock(text="ok")],
            stop_reason=FinishReason.END_TURN,
            model="test-model",
        )
        reg = ToolRegistry()
        reg.register(ReadFileTool())
        agent = SubAgent(provider=mock_provider, tool_registry=reg)
        agent.context = MagicMock()
        agent.context.messages = []
        return agent, mock_provider

    @pytest.mark.asyncio
    async def test_call_llm_calls_provider(self):
        agent, mock_provider = self._setup()
        response = await agent._call_llm()
        mock_provider.create.assert_called_once()
        assert response.stop_reason == FinishReason.END_TURN

    @pytest.mark.asyncio
    async def test_call_llm_raises_without_provider(self):
        agent = SubAgent()
        agent.context = MagicMock()
        agent.context.messages = []
        with pytest.raises(RuntimeError, match="no provider was set"):
            await agent._call_llm()

    @pytest.mark.asyncio
    async def test_call_llm_raises_without_context(self):
        mock_provider = AsyncMock(spec=LLMProvider)
        agent = SubAgent(provider=mock_provider)
        agent.context = None
        with pytest.raises(RuntimeError, match="context is not initialised"):
            await agent._call_llm()

    @pytest.mark.asyncio
    async def test_call_llm_passes_tool_definitions(self):
        agent, mock_provider = self._setup()
        await agent._call_llm()
        call_kwargs = mock_provider.create.call_args
        # tools kwarg should have been passed
        assert "tools" in call_kwargs.kwargs


# ---------------------------------------------------------------------------
# SubAgent _execute_tools tests
# ---------------------------------------------------------------------------


class TestSubAgentExecuteTools:
    def _setup(self):
        reg = ToolRegistry()
        reg.register(ReadFileTool())
        reg.register(TaskToolStub())
        agent = SubAgent(tool_registry=reg)
        agent.context = MagicMock()
        agent.context.messages = []
        agent.context.add_message = AsyncMock()
        agent.context.loop_count = 0
        return agent, reg

    @pytest.mark.asyncio
    async def test_execute_allowed_tool(self):
        agent, _ = self._setup()
        tool_call = MagicMock()
        tool_call.tool_name = "read_file"
        tool_call.tool_input = {"path": "test.txt"}
        tool_call.tool_call_id = "tc1"

        await agent._execute_tools([tool_call])
        # Context should have received a tool result message
        agent.context.add_message.assert_called()

    @pytest.mark.asyncio
    async def test_execute_forbidden_task_tool_records_error(self):
        agent, _ = self._setup()
        tool_call = MagicMock()
        tool_call.tool_name = "task"
        tool_call.tool_input = {"description": "do something"}
        tool_call.tool_call_id = "tc2"

        await agent._execute_tools([tool_call])
        assert len(agent._errors) == 1
        assert "task" in agent._errors[0].message
        assert agent._errors[0].tool_name == "task"

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self):
        agent, _ = self._setup()
        tool_call = MagicMock()
        tool_call.tool_name = "unknown"
        tool_call.tool_input = {}
        tool_call.tool_call_id = "tc3"

        await agent._execute_tools([tool_call])
        # Should add an error result to context
        agent.context.add_message.assert_called()

    @pytest.mark.asyncio
    async def test_execute_raises_without_context(self):
        agent = SubAgent()
        agent.context = None
        tool_call = MagicMock()
        tool_call.tool_name = "read_file"
        tool_call.tool_input = {}
        tool_call.tool_call_id = "tc4"
        with pytest.raises(RuntimeError, match="context is not initialised"):
            await agent._execute_tools([tool_call])


# ---------------------------------------------------------------------------
# SubAgent build_response test
# ---------------------------------------------------------------------------


class TestBuildResponse:
    def test_build_response_success(self):
        result = AgentResult(
            text="hello",
            termination_reason=TerminationReason.END_TURN,
            loops_used=3,
            tokens_used=200,
            time_elapsed=1.5,
        )
        resp = SubAgent.build_response(result)
        assert resp.success is True
        assert resp.result_text == "hello"
        assert resp.termination_reason == TerminationReason.END_TURN
        assert resp.error is None

    def test_build_response_error(self):
        result = AgentResult(
            text="",
            termination_reason=TerminationReason.ERROR,
            loops_used=1,
            tokens_used=0,
            time_elapsed=0.5,
            error="llm failed",
        )
        resp = SubAgent.build_response(result)
        assert resp.success is False
        assert resp.error == "llm failed"


# ---------------------------------------------------------------------------
# SubAgent create_request test
# ---------------------------------------------------------------------------


class TestCreateRequest:
    def test_create_request(self):
        agent = SubAgent()
        req = agent.create_request("analyze data", context_files=["data.csv"])
        assert req.task_description == "analyze data"
        assert req.context_files == ["data.csv"]


# ---------------------------------------------------------------------------
# SubAgent integration-style test (with hooks)
# ---------------------------------------------------------------------------


class TestSubAgentWithHooks:
    @pytest.mark.asyncio
    async def test_hook_executor_blocks_llm_call(self):
        from aidynamic_agent.hooks.base import Hook

        class BlockingHook(Hook):
            name = "blocking"
            events = [HookEvent.BEFORE_LLM_CALL]

            async def handle(self, ctx):
                ctx.blocked = True
                return ctx

        executor = HookExecutor()
        executor.register(BlockingHook())

        agent = SubAgent(hook_executor=executor)
        agent.context = MagicMock()
        agent.context.messages = []
        agent.context.loop_count = 0

        with pytest.raises(RuntimeError, match="blocked by hook"):
            await agent._call_llm()
