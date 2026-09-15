from __future__ import annotations

from aidynamic_agent.core.message import ToolDefinition
from aidynamic_agent.tools.base import Tool
from aidynamic_agent.tools.context import ToolContext


class ToolRegistry:
    """Tool registry with permission filtering"""

    def __init__(self, context: ToolContext | None = None):
        self._tools: dict[str, Tool] = {}
        self.context = context or ToolContext()

    def register(self, tool: Tool) -> None:
        """Register a tool instance"""
        if not tool.name:
            raise ValueError("Tool must have a name")
        tool.context = self.context  # Inject shared context
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_all(self) -> list[Tool]:
        return list(self._tools.values())

    def list_available(self, allowed_tags: list[str] | None = None) -> list[Tool]:
        """Filter by permission tags. If no allowed_tags, return all"""
        if not allowed_tags:
            return self.list_all()
        return [t for t in self._tools.values() if any(tag in allowed_tags for tag in t.tags)]

    def to_tool_definitions(self, allowed_tags: list[str] | None = None) -> list[ToolDefinition]:
        """Convert available tools to LLM ToolDefinition format"""
        return [t.to_tool_definition() for t in self.list_available(allowed_tags)]

    def remove(self, name: str) -> bool:
        """Remove tool by name, return True if found"""
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def clear(self) -> None:
        self._tools.clear()

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
