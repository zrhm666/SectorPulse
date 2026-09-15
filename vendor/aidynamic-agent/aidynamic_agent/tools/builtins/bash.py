from __future__ import annotations

import asyncio
import logging
from typing import Any

from aidynamic_agent.tools.base import Tool, ToolResult
from aidynamic_agent.tools.context import ToolContext

logger = logging.getLogger(__name__)

# Dangerous command patterns that should be rejected
_DANGEROUS_PATTERNS = [
    "rm -rf /",
    "rm -rf /*",
    "rm -rf ~",
    "mkfs",
    "dd if=/dev/zero",
    "dd if=/dev/random",
    "sudo reboot",
    "sudo shutdown",
    "init 0",
    ":(){:|:&};:",  # fork bomb
]


class BashTool(Tool):
    """Execute shell commands safely with timeout and output limits."""

    name = "bash"
    description = "Execute a shell command and return its output"
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute",
            },
        },
        "required": ["command"],
    }
    tags = ["shell", "terminal"]

    MAX_OUTPUT_CHARS = 50_000  # Limit output to prevent context overflow

    def __init__(self, context: ToolContext | None = None, timeout: float = 30.0):
        super().__init__(context=context)
        self.timeout = timeout

    def _is_dangerous(self, command: str) -> str | None:
        """Check if command matches dangerous patterns. Returns reason or None."""
        cmd = command.strip()
        cmd_lower = cmd.lower()

        # Special handling for rm -rf: only reject when target is / or /* or ~
        import re

        rm_match = re.match(
            r"rm\s+(-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*|-[a-zA-Z]*f[a-zA-Z]*r[a-zA-Z]*)\s+(.+)",
            cmd_lower,
        )
        if rm_match:
            target = rm_match.group(2).strip()
            # Split on whitespace to get the first target argument
            first_target = target.split()[0] if target.split() else ""
            if first_target in ("/", "/*", "~", "$HOME", "${home}"):
                return f"dangerous command pattern detected: rm -rf {first_target}"

        for pattern in _DANGEROUS_PATTERNS:
            if pattern.lower().startswith("rm "):
                continue  # Already handled above
            if pattern.lower() in cmd_lower:
                return f"dangerous command pattern detected: {pattern}"
        return None

    async def execute(  # type: ignore[override]
        self,
        command: str,
        **kwargs: Any,
    ) -> ToolResult:
        """Execute the shell command via asyncio subprocess."""
        if not command or not command.strip():
            return ToolResult(
                content="",
                success=False,
                error="Empty command",
            )

        # Check for dangerous commands
        dangerous_reason = self._is_dangerous(command)
        if dangerous_reason:
            return ToolResult(
                content="",
                success=False,
                error=dangerous_reason,
            )

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=self.timeout
                )
            except TimeoutError:
                proc.kill()
                await proc.wait()
                return ToolResult(
                    content="",
                    success=False,
                    error=f"Command timed out after {self.timeout}s",
                    metadata={"returncode": -1, "timed_out": True},
                )

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            exit_code = proc.returncode or 0

            # Build output - strip trailing newline from stdout for clean comparison
            content = stdout.rstrip("\n")
            if stderr:
                content = (
                    content + "\nSTDERR:\n" + stderr.rstrip("\n")
                    if content
                    else stderr.rstrip("\n")
                )

            # Truncate output if too long
            truncated = False
            if len(content) > self.MAX_OUTPUT_CHARS:
                content = content[: self.MAX_OUTPUT_CHARS] + "\n... [output truncated]"
                truncated = True

            return ToolResult(
                content=content,
                success=exit_code == 0,
                error=stderr.strip() if exit_code != 0 else None,
                metadata={
                    "returncode": exit_code,
                    "truncated": truncated,
                    "stdout_length": len(stdout),
                    "stderr_length": len(stderr),
                },
            )

        except Exception as e:
            return ToolResult(
                content="",
                success=False,
                error=str(e),
            )
