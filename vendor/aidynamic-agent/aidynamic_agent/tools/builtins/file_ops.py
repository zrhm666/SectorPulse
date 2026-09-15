from __future__ import annotations

from pathlib import Path
from typing import Any

from aidynamic_agent.tools.base import Tool, ToolResult


class FileOpsTool(Tool):
    """Read, write, patch, and search files."""

    name = "file_ops"
    description = "Read, write, patch, search files"
    parameters = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["read", "write", "patch", "search"],
                "description": "The file operation to perform",
            },
            "path": {
                "type": "string",
                "description": "File path (or directory for search)",
            },
            "content": {
                "type": "string",
                "description": "Content for write/patch operations",
            },
            "old_string": {
                "type": "string",
                "description": "String to replace (patch operation)",
            },
            "new_string": {
                "type": "string",
                "description": "Replacement string (patch operation)",
            },
            "pattern": {
                "type": "string",
                "description": "Regex pattern for search operation",
            },
        },
        "required": ["operation", "path"],
    }
    tags = ["file"]

    async def execute(self, operation: str, path: str, **kwargs: Any) -> ToolResult:  # type: ignore[override]
        """Dispatch to the appropriate file operation."""
        try:
            if operation == "read":
                return await self._read_file(path, **kwargs)
            elif operation == "write":
                return await self._write_file(path, **kwargs)
            elif operation == "patch":
                return await self._patch_file(path, **kwargs)
            elif operation == "search":
                return await self._search_files(path, **kwargs)
            else:
                return ToolResult(
                    content="",
                    success=False,
                    error=f"Unknown operation: {operation}",
                )
        except Exception as e:
            return ToolResult(
                content="",
                success=False,
                error=str(e),
            )

    async def _read_file(
        self, path: str, offset: int = 1, limit: int = 500, **kwargs: Any
    ) -> ToolResult:
        """Read file contents with pagination."""
        file_path = Path(path)
        if not file_path.exists():
            return ToolResult(
                content="",
                success=False,
                error=f"File not found: {path}",
            )
        if not file_path.is_file():
            return ToolResult(
                content="",
                success=False,
                error=f"Not a file: {path}",
            )

        try:
            content = file_path.read_text(encoding="utf-8")
            lines = content.splitlines()

            start = max(0, offset - 1)
            end = start + limit if limit > 0 else len(lines)
            selected = lines[start:end]

            total_lines = len(lines)
            has_more = end < total_lines

            result_lines = []
            for i, line in enumerate(selected, start=start + 1):
                result_lines.append(f"{i}|{line}")

            output = "\n".join(result_lines)
            metadata = {
                "total_lines": total_lines,
                "offset": offset,
                "limit": limit,
            }
            if has_more:
                metadata["has_more"] = True

            return ToolResult(content=output, success=True, metadata=metadata)
        except UnicodeDecodeError:
            return ToolResult(
                content="",
                success=False,
                error=f"Cannot read binary file: {path}",
            )

    async def _write_file(self, path: str, content: str = "", **kwargs: Any) -> ToolResult:
        """Write content to a file, creating parent directories as needed."""
        file_path = Path(path)

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return ToolResult(
                content=f"File written: {path} ({len(content)} bytes)",
                success=True,
            )
        except PermissionError:
            return ToolResult(
                content="",
                success=False,
                error=f"Permission denied: {path}",
            )

    async def _patch_file(
        self,
        path: str,
        old_string: str = "",
        new_string: str = "",
        replace_all: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        """Replace text in a file."""
        file_path = Path(path)
        if not file_path.exists():
            return ToolResult(
                content="",
                success=False,
                error=f"File not found: {path}",
            )

        try:
            content = file_path.read_text(encoding="utf-8")
            if old_string not in content:
                return ToolResult(
                    content="",
                    success=False,
                    error="old_string not found in file",
                )

            if replace_all:
                new_content = content.replace(old_string, new_string)
            else:
                new_content = content.replace(old_string, new_string, 1)

            file_path.write_text(new_content, encoding="utf-8")
            return ToolResult(
                content=f"Patched: {path}",
                success=True,
                metadata={
                    "old_length": len(old_string),
                    "new_length": len(new_string),
                },
            )
        except UnicodeDecodeError:
            return ToolResult(
                content="",
                success=False,
                error=f"Cannot patch binary file: {path}",
            )

    async def _search_files(self, path: str, pattern: str = "", **kwargs: Any) -> ToolResult:
        """Search files for a regex pattern."""
        search_path = Path(path)
        if not search_path.exists():
            return ToolResult(
                content="",
                success=False,
                error=f"Path not found: {path}",
            )

        import re as regex_mod

        try:
            compiled = regex_mod.compile(pattern)
        except regex_mod.error as e:
            return ToolResult(
                content="",
                success=False,
                error=f"Invalid regex pattern: {e}",
            )

        results = []
        if search_path.is_file():
            matches = await self._search_single_file(search_path, compiled)
            results.extend(matches)
        elif search_path.is_dir():
            for file_path in sorted(search_path.rglob("*")):
                if file_path.is_file():
                    matches = await self._search_single_file(file_path, compiled)
                    results.extend(matches)

        if not results:
            return ToolResult(
                content="No matches found",
                success=True,
            )

        output = "\n".join(results)
        return ToolResult(content=output, success=True, metadata={"match_count": len(results)})

    async def _search_single_file(self, file_path: Path, compiled_pattern: Any) -> list[str]:
        """Search a single file for pattern matches."""
        try:
            content = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            return []

        matches = []
        for i, line in enumerate(content.splitlines(), 1):
            if compiled_pattern.search(line):
                matches.append(f"{file_path}:{i}:{line.strip()}")

        return matches
