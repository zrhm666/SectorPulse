from __future__ import annotations

from aidynamic_agent.tools.base import Tool, ToolResult
from aidynamic_agent.tools.context import ToolContext


class HistoryTool(Tool):
    """Query tool execution history"""

    name = "history"
    description = "Query tool execution history"
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Query string to search in tool execution history",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of results to return",
                "default": 10,
            },
        },
    }
    tags = ["history"]

    def __init__(self, context: ToolContext | None = None):
        super().__init__(context)

    async def execute(self, **kwargs) -> ToolResult:
        store = self.context.history_store

        if store is None:
            return ToolResult(
                content="Error: history_store is not configured",
                success=False,
                error="history_store is not configured",
            )

        limit = kwargs.get("limit", 10)
        query = kwargs.get("query", "")

        if not hasattr(store, "_store"):
            return ToolResult(
                content="Error: history_store does not support querying",
                success=False,
                error="history_store does not support querying",
            )

        entries = list(store._store.values())

        # Filter by query if provided
        if query:
            entries = [
                e
                for e in entries
                if query.lower() in e.tool_name.lower() or query.lower() in e.content.lower()
            ]

        # Sort by timestamp descending (most recent first)
        entries.sort(key=lambda e: e.timestamp, reverse=True)

        # Apply limit
        entries = entries[:limit]

        if not entries:
            return ToolResult(content="No matching history entries found")

        lines = []
        for e in entries:
            lines.append(f"[{e.timestamp:.0f}] {e.tool_name} ({e.tool_call_id}): {e.content[:100]}")
        return ToolResult(content="\n".join(lines))
