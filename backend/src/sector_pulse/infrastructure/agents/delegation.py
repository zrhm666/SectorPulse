"""A server-controlled delegation tool for the A0 parent agent."""

from collections.abc import Awaitable, Callable

from aidynamic_agent.tools.base import Tool, ToolResult

Dispatch = Callable[[str, str, str, tuple[str, ...]], Awaitable[ToolResult]]


class RestrictedDelegateTool(Tool):
    name = "delegate"
    description = "Delegate a bounded task to one registered specialist role."
    tags = ["parent_only", "delegation"]
    parameters = {
        "type": "object",
        "properties": {
            "role": {"type": "string", "enum": ["A1", "A2", "A3", "A4"]},
            "goal": {"type": "string", "minLength": 1},
            "scope": {"type": "string", "minLength": 1, "maxLength": 200},
            "artifact_refs": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "maxItems": 100,
            },
        },
        "required": ["role", "goal", "scope"],
        "additionalProperties": False,
    }

    def __init__(self, dispatch: Dispatch) -> None:
        super().__init__()
        self.dispatch = dispatch

    async def execute(self, **kwargs: object) -> ToolResult:
        if set(kwargs) - {"role", "goal", "scope", "artifact_refs"}:
            return ToolResult(
                content="delegation parameters are server controlled",
                success=False,
                error="unsupported delegation parameter",
            )
        role = kwargs.get("role")
        goal = kwargs.get("goal")
        scope = kwargs.get("scope")
        raw_refs = kwargs.get("artifact_refs", [])
        if not isinstance(role, str) or role not in {"A1", "A2", "A3", "A4"}:
            return ToolResult(content="unknown specialist role", success=False, error="role denied")
        if not isinstance(goal, str) or not goal.strip():
            return ToolResult(content="goal is required", success=False, error="invalid goal")
        if not isinstance(scope, str) or not scope.strip() or len(scope) > 200:
            return ToolResult(content="scope is required", success=False, error="invalid scope")
        if (
            not isinstance(raw_refs, list)
            or len(raw_refs) > 100
            or not all(isinstance(item, str) and item for item in raw_refs)
        ):
            return ToolResult(
                content="artifact references are invalid",
                success=False,
                error="invalid artifact references",
            )
        return await self.dispatch(role, goal, scope, tuple(raw_refs))
