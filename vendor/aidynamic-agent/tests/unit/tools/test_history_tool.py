"""Unit tests for aidynamic_agent.tools.builtins.history - HistoryTool"""

from __future__ import annotations

import asyncio

from aidynamic_agent.managers.history import ToolHistoryStore
from aidynamic_agent.tools.builtins.history import HistoryTool
from aidynamic_agent.tools.context import ToolContext


class TestHistoryToolWithoutManager:
    """Test HistoryTool when history_store is not configured."""

    def test_execute_without_manager_returns_error(self):
        tool = HistoryTool()
        result = asyncio.run(tool.execute())
        assert result.success is False
        assert "history_store is not configured" in result.content
        assert result.error == "history_store is not configured"


class TestHistoryToolWithStore:
    """Test HistoryTool with a configured history_store."""

    async def test_query_with_results(self):
        store = ToolHistoryStore()
        await store.store("read_file", "hello world", tool_call_id="c1")
        await store.store("search_files", "search results", tool_call_id="c2")

        ctx = ToolContext()
        ctx.set("history_store", store)
        tool = HistoryTool(context=ctx)

        result = await tool.execute()
        assert result.success is True
        assert "read_file" in result.content
        assert "search_files" in result.content

    async def test_query_filters_by_tool_name(self):
        store = ToolHistoryStore()
        await store.store("read_file", "file content here", tool_call_id="c1")
        await store.store("search_files", "some results", tool_call_id="c2")

        ctx = ToolContext()
        ctx.set("history_store", store)
        tool = HistoryTool(context=ctx)

        result = await tool.execute(query="read")
        assert result.success is True
        assert "read_file" in result.content
        assert "search_files" not in result.content

    async def test_query_filters_by_content(self):
        store = ToolHistoryStore()
        await store.store("read_file", "important data", tool_call_id="c1")
        await store.store("write_file", "unrelated content", tool_call_id="c2")

        ctx = ToolContext()
        ctx.set("history_store", store)
        tool = HistoryTool(context=ctx)

        result = await tool.execute(query="important")
        assert result.success is True
        assert "read_file" in result.content
        assert "write_file" not in result.content

    async def test_query_no_results(self):
        store = ToolHistoryStore()
        await store.store("read_file", "hello", tool_call_id="c1")

        ctx = ToolContext()
        ctx.set("history_store", store)
        tool = HistoryTool(context=ctx)

        result = await tool.execute(query="nonexistent")
        assert result.success is True
        assert "No matching history entries found" in result.content

    async def test_limit_applied(self):
        store = ToolHistoryStore()
        for i in range(5):
            await store.store("tool", f"content_{i}", tool_call_id=f"c{i}")

        ctx = ToolContext()
        ctx.set("history_store", store)
        tool = HistoryTool(context=ctx)

        result = await tool.execute(limit=2)
        assert result.success is True
        lines = result.content.strip().split("\n")
        assert len(lines) == 2

    async def test_empty_store(self):
        store = ToolHistoryStore()

        ctx = ToolContext()
        ctx.set("history_store", store)
        tool = HistoryTool(context=ctx)

        result = await tool.execute()
        assert result.success is True
        assert "No matching history entries found" in result.content


class TestHistoryToolDefinition:
    """Test HistoryTool metadata."""

    def test_name(self):
        assert HistoryTool.name == "history"

    def test_description(self):
        assert "Query tool execution history" in HistoryTool.description

    def test_tags(self):
        assert "history" in HistoryTool.tags

    def test_to_tool_definition(self):
        tool = HistoryTool()
        definition = tool.to_tool_definition()
        assert definition.name == "history"
        props = definition.input_schema["properties"]
        assert "query" in props
        assert "limit" in props


class TestHistoryToolRun:
    """Test HistoryTool via the run template method."""

    async def test_run_adds_metadata(self):
        store = ToolHistoryStore()
        ctx = ToolContext()
        ctx.set("history_store", store)
        tool = HistoryTool(context=ctx)

        result = await tool.run()
        assert result.success is True
        assert "execution_time" in result.metadata
        assert result.metadata["tool_name"] == "history"
