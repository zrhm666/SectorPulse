"""Tests for agent/tools/registry.py - ToolRegistry."""

from __future__ import annotations

from typing import Any

import pytest

from aidynamic_agent.tools.base import Tool, ToolContext, ToolResult
from aidynamic_agent.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Concrete tool implementations for testing
# ---------------------------------------------------------------------------


class DummyTool(Tool):
    """A concrete tool for testing."""

    def __init__(
        self,
        name: str = "",
        description: str = "",
        tags: list[str] | None = None,
        parameters: dict | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.tags = tags or []
        if parameters is not None:
            self.parameters = parameters

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(content="ok")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestToolRegistryInitialization:
    """Test ToolRegistry default state."""

    def test_default_context_is_tool_context(self):
        reg = ToolRegistry()
        assert isinstance(reg.context, ToolContext)

    def test_custom_context(self):
        ctx = ToolContext()
        ctx.set("foo", "bar")
        reg = ToolRegistry(context=ctx)
        assert reg.context is ctx

    def test_empty_on_init(self):
        reg = ToolRegistry()
        assert len(reg) == 0


class TestRegisterAndGet:
    """Test register and get tool by name."""

    def test_register_and_get(self):
        reg = ToolRegistry()
        tool = DummyTool(name="search", description="Search files")
        reg.register(tool)
        assert reg.get("search") is tool

    def test_get_unknown_returns_none(self):
        reg = ToolRegistry()
        assert reg.get("unknown") is None

    def test_register_tool_without_name_raises_value_error(self):
        reg = ToolRegistry()
        tool = DummyTool(name="", description="no name")
        with pytest.raises(ValueError, match="Tool must have a name"):
            reg.register(tool)

    def test_register_tool_with_empty_name_raises_value_error(self):
        reg = ToolRegistry()
        tool = DummyTool(name="", description="empty name")
        with pytest.raises(ValueError, match="Tool must have a name"):
            reg.register(tool)

    def test_context_injection_on_register(self):
        """Registered tools get shared context."""
        ctx = ToolContext()
        ctx.set("key", "shared_value")
        reg = ToolRegistry(context=ctx)
        tool = DummyTool(name="foo")
        reg.register(tool)
        assert tool.context is ctx
        assert tool.context.get("key") == "shared_value"


class TestListAll:
    """Test list_all returns all tools."""

    def test_list_all_empty(self):
        reg = ToolRegistry()
        assert reg.list_all() == []

    def test_list_all_returns_all(self):
        reg = ToolRegistry()
        t1 = DummyTool(name="a")
        t2 = DummyTool(name="b")
        t3 = DummyTool(name="c")
        reg.register(t1)
        reg.register(t2)
        reg.register(t3)
        tools = reg.list_all()
        assert len(tools) == 3
        assert {t.name for t in tools} == {"a", "b", "c"}


class TestListAvailable:
    """Test list_available filters by tags."""

    def test_list_available_no_filter_returns_all(self):
        reg = ToolRegistry()
        t1 = DummyTool(name="a", tags=["read"])
        t2 = DummyTool(name="b", tags=["write"])
        reg.register(t1)
        reg.register(t2)
        result = reg.list_available(allowed_tags=None)
        assert len(result) == 2

    def test_list_available_empty_filter_returns_all(self):
        reg = ToolRegistry()
        t1 = DummyTool(name="a", tags=["read"])
        t2 = DummyTool(name="b", tags=["write"])
        reg.register(t1)
        reg.register(t2)
        result = reg.list_available(allowed_tags=[])
        assert len(result) == 2

    def test_list_available_filters_by_tag(self):
        reg = ToolRegistry()
        t1 = DummyTool(name="read_file", tags=["read", "fs"])
        t2 = DummyTool(name="write_file", tags=["write", "fs"])
        t3 = DummyTool(name="search", tags=["search"])
        reg.register(t1)
        reg.register(t2)
        reg.register(t3)
        result = reg.list_available(allowed_tags=["read"])
        assert len(result) == 1
        assert result[0].name == "read_file"

    def test_list_available_multiple_tags(self):
        reg = ToolRegistry()
        t1 = DummyTool(name="read_file", tags=["read", "fs"])
        t2 = DummyTool(name="write_file", tags=["write", "fs"])
        t3 = DummyTool(name="search", tags=["search"])
        reg.register(t1)
        reg.register(t2)
        reg.register(t3)
        result = reg.list_available(allowed_tags=["read", "search"])
        assert len(result) == 2
        assert {t.name for t in result} == {"read_file", "search"}

    def test_list_available_tool_with_no_tags_excluded(self):
        reg = ToolRegistry()
        t1 = DummyTool(name="tagged", tags=["fs"])
        t2 = DummyTool(name="untagged", tags=[])
        reg.register(t1)
        reg.register(t2)
        result = reg.list_available(allowed_tags=["fs"])
        assert len(result) == 1
        assert result[0].name == "tagged"


class TestToToolDefinitions:
    """Test to_tool_definitions converts to LLM format."""

    def test_empty_registry(self):
        reg = ToolRegistry()
        assert reg.to_tool_definitions() == []

    def test_converts_to_llm_format(self):
        reg = ToolRegistry()
        tool = DummyTool(
            name="search",
            description="Search for files",
            tags=["fs"],
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        )
        reg.register(tool)
        defs = reg.to_tool_definitions()
        assert len(defs) == 1
        definition = defs[0]
        assert definition.name == "search"
        assert definition.description == "Search for files"
        assert definition.input_schema["properties"]["query"]["type"] == "string"

    def test_to_tool_definitions_respects_tags(self):
        reg = ToolRegistry()
        t1 = DummyTool(name="read", tags=["fs"], description="Read")
        t2 = DummyTool(name="write", tags=["fs"], description="Write")
        t3 = DummyTool(name="http_get", tags=["net"], description="HTTP GET")
        reg.register(t1)
        reg.register(t2)
        reg.register(t3)
        defs = reg.to_tool_definitions(allowed_tags=["fs"])
        assert len(defs) == 2
        assert {d.name for d in defs} == {"read", "write"}

    def test_to_tool_definitions_no_filter(self):
        reg = ToolRegistry()
        t1 = DummyTool(name="a", tags=["x"])
        t2 = DummyTool(name="b", tags=["y"])
        reg.register(t1)
        reg.register(t2)
        defs = reg.to_tool_definitions()
        assert len(defs) == 2


class TestRemove:
    """Test remove tool by name."""

    def test_remove_existing_returns_true(self):
        reg = ToolRegistry()
        tool = DummyTool(name="foo")
        reg.register(tool)
        assert reg.remove("foo") is True
        assert reg.get("foo") is None

    def test_remove_nonexistent_returns_false(self):
        reg = ToolRegistry()
        assert reg.remove("nonexistent") is False

    def test_remove_reduces_length(self):
        reg = ToolRegistry()
        reg.register(DummyTool(name="a"))
        reg.register(DummyTool(name="b"))
        assert len(reg) == 2
        reg.remove("a")
        assert len(reg) == 1


class TestClear:
    """Test clear removes all tools."""

    def test_clear_removes_all(self):
        reg = ToolRegistry()
        reg.register(DummyTool(name="a"))
        reg.register(DummyTool(name="b"))
        reg.register(DummyTool(name="c"))
        reg.clear()
        assert len(reg) == 0
        assert reg.list_all() == []

    def test_clear_on_empty(self):
        reg = ToolRegistry()
        reg.clear()
        assert len(reg) == 0


class TestLenAndContains:
    """Test len and __contains__."""

    def test_len_empty(self):
        reg = ToolRegistry()
        assert len(reg) == 0

    def test_len_after_register(self):
        reg = ToolRegistry()
        reg.register(DummyTool(name="a"))
        reg.register(DummyTool(name="b"))
        assert len(reg) == 2

    def test_contains_existing(self):
        reg = ToolRegistry()
        reg.register(DummyTool(name="foo"))
        assert "foo" in reg

    def test_contains_nonexisting(self):
        reg = ToolRegistry()
        reg.register(DummyTool(name="foo"))
        assert "bar" not in reg


class TestContextInjection:
    """Test that registered tools get the shared context."""

    def test_all_tools_share_same_context(self):
        ctx = ToolContext()
        ctx.set("shared_key", "shared_value")
        reg = ToolRegistry(context=ctx)
        t1 = DummyTool(name="t1")
        t2 = DummyTool(name="t2")
        reg.register(t1)
        reg.register(t2)
        assert t1.context is t2.context
        assert t1.context is ctx
        assert t1.context.get("shared_key") == "shared_value"

    def test_context_updated_after_registration(self):
        ctx = ToolContext()
        reg = ToolRegistry(context=ctx)
        tool = DummyTool(name="test_tool")
        reg.register(tool)
        # The tool's context should point to the registry's context
        assert tool.context is reg.context
