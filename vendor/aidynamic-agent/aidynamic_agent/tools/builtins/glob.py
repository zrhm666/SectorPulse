from __future__ import annotations

from pathlib import Path
from typing import Any

from aidynamic_agent.tools.base import Tool, ToolResult


class GlobTool(Tool):
    """Find files by name pattern."""

    name = "glob"
    description = "Find files by name pattern"
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern to match (e.g., '*.py', '**/*.json')",
            },
            "path": {
                "type": "string",
                "description": "Root directory to search from (default: current directory)",
            },
        },
        "required": ["pattern"],
    }
    tags = ["file"]

    async def execute(self, pattern: str, path: str | None = None, **kwargs: Any) -> ToolResult:  # type: ignore[override]
        """Find files matching the glob pattern."""
        if not pattern:
            return ToolResult(
                content="",
                success=False,
                error="Pattern is required",
            )

        search_path = Path(path) if path else Path.cwd()

        if not search_path.exists():
            return ToolResult(
                content="",
                success=False,
                error=f"Path not found: {search_path}",
            )

        if not search_path.is_dir():
            return ToolResult(
                content="",
                success=False,
                error=f"Not a directory: {search_path}",
            )

        try:
            matches = self._find_files(search_path, pattern)
            if not matches:
                return ToolResult(
                    content="No files found",
                    success=True,
                )

            output = "\n".join(str(m) for m in matches)
            return ToolResult(
                content=output,
                success=True,
                metadata={"match_count": len(matches)},
            )
        except Exception as e:
            return ToolResult(
                content="",
                success=False,
                error=str(e),
            )

    @staticmethod
    def _find_files(base_path: Path, pattern: str) -> list[Path]:
        """Find files using glob patterns."""
        results: list[Path] = []

        if "**" in pattern:
            # Use rglob for recursive patterns
            # Remove leading **/ if present for rglob
            clean_pattern = pattern
            if clean_pattern.startswith("**/"):
                clean_pattern = clean_pattern[3:]
            try:
                results = sorted(base_path.rglob(clean_pattern))
            except Exception:
                results = []
        else:
            # Use glob for non-recursive patterns
            try:
                results = sorted(base_path.glob(pattern))
            except Exception:
                results = []

        # Filter to only files
        return [p for p in results if p.is_file()]
