from __future__ import annotations

from aidynamic_agent.tools.base import Tool, ToolResult
from aidynamic_agent.tools.context import ToolContext


class SkillTool(Tool):
    """Navigate and display skill information.

    A "navigation" tool that tells the agent what skills are available and where they are.
    The agent should use builtin file tools (bash, file_ops, glob) to actually read files
    or execute scripts in skill directories.

    Supports two operations:
    - list: List all available skills with their absolute paths
    - load: Load a skill's SKILL.md main document (with path hints prepended)
    """

    name = "skill"
    description = "Navigate skills: list available skills and load skill documents"
    parameters = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["list", "load"],
                "description": "Operation: 'list' available skills with paths, 'load' a skill's SKILL.md",
            },
            "name": {
                "type": "string",
                "description": "Skill name (required for load operation)",
            },
        },
        "required": ["operation"],
    }
    tags = ["skill"]

    def __init__(self, context: ToolContext | None = None):
        super().__init__(context)

    async def execute(self, **kwargs) -> ToolResult:
        operation = kwargs.get("operation")
        manager = self.context.skill_manager

        if manager is None:
            return ToolResult(
                content="Error: skill_manager is not configured",
                success=False,
                error="skill_manager is not configured",
            )

        if operation == "list":
            return await self._list(manager)
        elif operation == "load":
            return await self._load(manager, kwargs)
        else:
            return ToolResult(
                content=f"Error: unknown operation '{operation}'",
                success=False,
                error=f"Unknown operation: {operation}",
            )

    async def _list(self, manager) -> ToolResult:
        """List all available skills with their absolute paths."""
        skills = manager.describe_available()
        if not skills:
            return ToolResult(content="No skills available")

        lines = ["Available skills:\n"]
        for s in skills:
            lines.append(f"  **{s['name']}**: {s['description']}")
            lines.append(f"    Path: {s['path']}")
            lines.append(f"    Usage: skill(operation=\"load\", name=\"{s['name']}\")")
            lines.append("")

        return ToolResult(content="\n".join(lines))

    async def _load(self, manager, kwargs: dict) -> ToolResult:
        """Load a skill's SKILL.md with path hints prepended."""
        name = kwargs.get("name")
        if not name:
            return ToolResult(
                content="Error: name is required for load operation",
                success=False,
                error="name is required for load operation",
            )

        text = manager.load_full_text_with_path_hint(name)
        if text is None:
            return ToolResult(
                content=f"Error: skill '{name}' not found",
                success=False,
                error=f"Skill not found: {name}",
            )
        return ToolResult(content=text)
