from __future__ import annotations

from aidynamic_agent.tools.base import Tool, ToolResult
from aidynamic_agent.tools.context import ToolContext


class TodoTool(Tool):
    """Manage task list"""

    name = "todo"
    description = "Manage task list"
    parameters = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["create", "update", "list", "list_by_status"],
                "description": "Operation to perform",
            },
            "content": {
                "type": "string",
                "description": "Todo content (required for create)",
            },
            "todo_id": {
                "type": "string",
                "description": "Todo ID (required for update)",
            },
            "status": {
                "type": "string",
                "description": "New status (required for update) or filter (for list_by_status)",
            },
        },
        "required": ["operation"],
    }
    tags = ["todo"]

    def __init__(self, context: ToolContext | None = None):
        super().__init__(context)

    async def execute(self, **kwargs) -> ToolResult:
        operation = kwargs.get("operation")
        manager = self.context.todo_manager

        if manager is None:
            return ToolResult(
                content="Error: todo_manager is not configured",
                success=False,
                error="todo_manager is not configured",
            )

        if operation == "create":
            return await self._create(manager, kwargs)
        elif operation == "update":
            return await self._update(manager, kwargs)
        elif operation == "list":
            return await self._list(manager)
        elif operation == "list_by_status":
            return await self._list_by_status(manager, kwargs)
        else:
            return ToolResult(
                content=f"Error: unknown operation '{operation}'",
                success=False,
                error=f"Unknown operation: {operation}",
            )

    async def _create(self, manager, kwargs: dict) -> ToolResult:
        content = kwargs.get("content")
        if not content:
            return ToolResult(
                content="Error: content is required for create operation",
                success=False,
                error="content is required for create operation",
            )
        item_id = manager.create(content)
        return ToolResult(
            content=f"Todo created with ID: {item_id}",
            metadata={"todo_id": item_id},
        )

    async def _update(self, manager, kwargs: dict) -> ToolResult:
        todo_id = kwargs.get("todo_id")
        status = kwargs.get("status")
        if not todo_id:
            return ToolResult(
                content="Error: todo_id is required for update operation",
                success=False,
                error="todo_id is required for update operation",
            )
        if not status:
            return ToolResult(
                content="Error: status is required for update operation",
                success=False,
                error="status is required for update operation",
            )
        success = manager.update(todo_id, status)
        if success:
            return ToolResult(
                content=f"Todo {todo_id} updated to status: {status}",
            )
        else:
            return ToolResult(
                content=f"Error: todo with ID '{todo_id}' not found",
                success=False,
                error=f"Todo not found: {todo_id}",
            )

    async def _list(self, manager) -> ToolResult:
        todos = manager.list_all()
        if not todos:
            return ToolResult(content="No todos found")
        lines = []
        for t in todos:
            lines.append(f"[{t.id}] {t.content} (status: {t.status})")
        return ToolResult(content="\n".join(lines))

    async def _list_by_status(self, manager, kwargs: dict) -> ToolResult:
        status = kwargs.get("status")
        if not status:
            return ToolResult(
                content="Error: status is required for list_by_status operation",
                success=False,
                error="status is required for list_by_status operation",
            )
        todos = manager.get_by_status(status)
        if not todos:
            return ToolResult(content=f"No todos with status '{status}'")
        lines = []
        for t in todos:
            lines.append(f"[{t.id}] {t.content} (status: {t.status})")
        return ToolResult(content="\n".join(lines))
