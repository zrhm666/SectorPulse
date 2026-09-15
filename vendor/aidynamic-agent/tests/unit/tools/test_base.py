"""Unit tests for aidynamic_agent.tools.base — ToolResult and Tool"""

from __future__ import annotations

import asyncio

import pytest

from aidynamic_agent.tools.base import Tool, ToolResult
from aidynamic_agent.tools.context import ToolContext

# --- ToolResult tests ---


class TestToolResultConstruction:
    """ToolResult construction with defaults"""

    def test_defaults(self):
        r = ToolResult(content="hello")
        assert r.content == "hello"
        assert r.success is True
        assert r.error is None
        assert r.metadata == {}

    def test_full_construction(self):
        r = ToolResult(
            content="output",
            success=False,
            error="boom",
            metadata={"key": "value"},
        )
        assert r.content == "output"
        assert r.success is False
        assert r.error == "boom"
        assert r.metadata == {"key": "value"}

    def test_metadata_is_independent(self):
        """Each instance gets its own metadata dict"""
        r1 = ToolResult(content="a")
        r2 = ToolResult(content="b")
        r1.metadata["x"] = 1
        assert "x" not in r2.metadata


class TestToolResultToContentBlock:
    """ToolResult.to_content_block() returns correct format"""

    def test_success_result(self):
        r = ToolResult(content="data", success=True)
        block = r.to_content_block()
        assert block.tool_call_id == ""  # Filled later by agent core
        assert block.tool_result_content == "data"
        assert block.is_error is False

    def test_error_result_is_error_true(self):
        """ToolResult with error sets is_error=True"""
        r = ToolResult(
            content="Error: fail",
            success=False,
            error="fail",
            metadata={"tool_name": "x"},
        )
        block = r.to_content_block()
        assert block.is_error is True
        assert block.tool_result_content == "fail"  # Uses error when not success


# --- Tool tests ---


class ConcreteTool(Tool):
    """Minimal concrete Tool for testing"""

    name = "test_tool"
    description = "A test tool"
    parameters = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
    }
    tags = ["test"]

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(content=f"ran with {kwargs}")


class FailingTool(Tool):
    """Tool whose execute always raises"""

    name = "failing_tool"
    description = "Always fails"
    parameters = {}

    async def execute(self, **kwargs) -> ToolResult:
        raise RuntimeError("intentional failure")


class TestToolAbstract:
    """Tool is abstract — can't instantiate directly"""

    def test_cannot_instantiate_tool(self):
        with pytest.raises(TypeError):
            Tool()  # type: ignore


class TestToolSubclass:
    """Concrete tool subclass can be instantiated"""

    def test_instantiate_with_defaults(self):
        tool = ConcreteTool()
        assert tool.name == "test_tool"
        assert isinstance(tool.context, ToolContext)

    def test_instantiate_with_context(self):
        ctx = ToolContext()
        ctx.set("foo", "bar")
        tool = ConcreteTool(context=ctx)
        assert tool.context is ctx
        assert tool.context.get("foo") == "bar"


class TestToolRun:
    """Tool.run() template method"""

    def test_run_calls_execute_and_adds_metadata(self):
        tool = ConcreteTool()
        result = asyncio.run(tool.run(value="42"))
        assert result.success is True
        assert "ran with" in result.content
        assert "execution_time" in result.metadata
        assert result.metadata["tool_name"] == "test_tool"
        assert result.metadata["execution_time"] >= 0

    def test_run_catches_exception(self):
        """Tool.run() catches exceptions and returns error ToolResult"""
        tool = FailingTool()
        result = asyncio.run(tool.run())
        assert result.success is False
        assert result.error == "intentional failure"
        assert "Error: intentional failure" in result.content
        assert "execution_time" in result.metadata
        assert result.metadata["tool_name"] == "failing_tool"


class TestToolDefinition:
    """Tool.to_tool_definition() returns correct format"""

    def test_to_tool_definition(self):
        tool = ConcreteTool()
        d = tool.to_tool_definition()
        assert d.name == "test_tool"
        assert d.description == "A test tool"
        assert d.input_schema == {
            "type": "object",
            "properties": {"value": {"type": "string"}},
        }
