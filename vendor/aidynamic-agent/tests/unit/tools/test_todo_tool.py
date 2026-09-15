"""Unit tests for aidynamic_agent.tools.builtins.todo - TodoTool"""

from __future__ import annotations

import asyncio

from aidynamic_agent.managers.todo import TodoManager
from aidynamic_agent.tools.builtins.todo import TodoTool
from aidynamic_agent.tools.context import ToolContext


def _run(coro):
    """Run async coroutine synchronously."""
    return asyncio.run(coro)


class TestTodoToolWithoutManager:
    """Test TodoTool when todo_manager is not configured."""

    def test_execute_without_manager_returns_error(self):
        tool = TodoTool()
        result = _run(tool.execute(operation="list"))
        assert result.success is False
        assert "todo_manager is not configured" in result.content
        assert result.error == "todo_manager is not configured"


class TestTodoToolCreate:
    """Test TodoTool create operation."""

    def test_create_success(self):
        ctx = ToolContext()
        ctx.set("todo_manager", TodoManager())
        tool = TodoTool(context=ctx)

        result = _run(tool.execute(operation="create", content="Buy groceries"))
        assert result.success is True
        assert "Todo created with ID:" in result.content
        assert "todo_id" in result.metadata

    def test_create_without_content_returns_error(self):
        ctx = ToolContext()
        ctx.set("todo_manager", TodoManager())
        tool = TodoTool(context=ctx)

        result = _run(tool.execute(operation="create"))
        assert result.success is False
        assert "content is required" in result.content

    def test_create_with_empty_content_returns_error(self):
        ctx = ToolContext()
        ctx.set("todo_manager", TodoManager())
        tool = TodoTool(context=ctx)

        result = _run(tool.execute(operation="create", content=""))
        assert result.success is False
        assert "content is required" in result.content


class TestTodoToolUpdate:
    """Test TodoTool update operation."""

    def test_update_success(self):
        ctx = ToolContext()
        mgr = TodoManager()
        ctx.set("todo_manager", mgr)
        tool = TodoTool(context=ctx)

        item_id = mgr.create("Task to update")
        result = _run(tool.execute(operation="update", todo_id=item_id, status="completed"))
        assert result.success is True
        assert "updated to status: completed" in result.content

    def test_update_nonexistent_todo(self):
        ctx = ToolContext()
        ctx.set("todo_manager", TodoManager())
        tool = TodoTool(context=ctx)

        result = _run(tool.execute(operation="update", todo_id="nonexistent", status="completed"))
        assert result.success is False
        assert "not found" in result.content

    def test_update_without_todo_id(self):
        ctx = ToolContext()
        ctx.set("todo_manager", TodoManager())
        tool = TodoTool(context=ctx)

        result = _run(tool.execute(operation="update", status="completed"))
        assert result.success is False
        assert "todo_id is required" in result.content

    def test_update_without_status(self):
        ctx = ToolContext()
        ctx.set("todo_manager", TodoManager())
        tool = TodoTool(context=ctx)

        result = _run(tool.execute(operation="update", todo_id="abc123"))
        assert result.success is False
        assert "status is required" in result.content


class TestTodoToolList:
    """Test TodoTool list operation."""

    def test_list_with_todos(self):
        ctx = ToolContext()
        mgr = TodoManager()
        mgr.create("Task 1")
        mgr.create("Task 2")
        ctx.set("todo_manager", mgr)
        tool = TodoTool(context=ctx)

        result = _run(tool.execute(operation="list"))
        assert result.success is True
        assert "Task 1" in result.content
        assert "Task 2" in result.content

    def test_list_empty(self):
        ctx = ToolContext()
        ctx.set("todo_manager", TodoManager())
        tool = TodoTool(context=ctx)

        result = _run(tool.execute(operation="list"))
        assert result.success is True
        assert "No todos found" in result.content


class TestTodoToolListByStatus:
    """Test TodoTool list_by_status operation."""

    def test_list_by_status_with_results(self):
        ctx = ToolContext()
        mgr = TodoManager()
        mgr.create("Task 1")
        id2 = mgr.create("Task 2")
        mgr.update(id2, "completed")
        ctx.set("todo_manager", mgr)
        tool = TodoTool(context=ctx)

        result = _run(tool.execute(operation="list_by_status", status="pending"))
        assert result.success is True
        assert "Task 1" in result.content
        assert "Task 2" not in result.content

    def test_list_by_status_no_results(self):
        ctx = ToolContext()
        mgr = TodoManager()
        mgr.create("Task 1")
        ctx.set("todo_manager", mgr)
        tool = TodoTool(context=ctx)

        result = _run(tool.execute(operation="list_by_status", status="completed"))
        assert result.success is True
        assert "No todos with status 'completed'" in result.content

    def test_list_by_status_without_status(self):
        ctx = ToolContext()
        ctx.set("todo_manager", TodoManager())
        tool = TodoTool(context=ctx)

        result = _run(tool.execute(operation="list_by_status"))
        assert result.success is False
        assert "status is required" in result.content


class TestTodoToolUnknownOperation:
    """Test TodoTool with unknown operation."""

    def test_unknown_operation_returns_error(self):
        ctx = ToolContext()
        ctx.set("todo_manager", TodoManager())
        tool = TodoTool(context=ctx)

        result = _run(tool.execute(operation="delete"))
        assert result.success is False
        assert "unknown operation" in result.content


class TestTodoToolDefinition:
    """Test TodoTool metadata."""

    def test_name(self):
        assert TodoTool.name == "todo"

    def test_description(self):
        assert "Manage task list" in TodoTool.description

    def test_tags(self):
        assert "todo" in TodoTool.tags

    def test_to_tool_definition(self):
        tool = TodoTool()
        definition = tool.to_tool_definition()
        assert definition.name == "todo"
        assert "operation" in definition.input_schema["properties"]


class TestTodoToolRun:
    """Test TodoTool via the run template method."""

    def test_run_adds_metadata(self):
        ctx = ToolContext()
        ctx.set("todo_manager", TodoManager())
        tool = TodoTool(context=ctx)

        result = _run(tool.run(operation="list"))
        assert result.success is True
        assert "execution_time" in result.metadata
        assert result.metadata["tool_name"] == "todo"
