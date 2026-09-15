"""Mock tool implementations for testing."""

from __future__ import annotations

import asyncio

from aidynamic_agent.tools.base import Tool, ToolResult
from aidynamic_agent.tools.context import ToolContext


class MockTool(Tool):
    """A mock tool that returns predefined responses."""

    name = "mock_tool"
    description = "A mock tool for testing"
    parameters = {
        "type": "object",
        "properties": {
            "input": {"type": "string", "description": "Mock input"},
        },
        "required": [],
    }

    def __init__(self, response: str = "mock result", context: ToolContext | None = None):
        super().__init__(context=context)
        self._response = response
        self.call_count = 0
        self.last_params: dict = {}

    async def execute(self, **params) -> ToolResult:
        self.call_count += 1
        self.last_params = params
        return ToolResult(content=self._response)


class MockToolWithError(Tool):
    """A mock tool that always fails."""

    name = "mock_tool_error"
    description = "A mock tool that always fails"
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, error_message: str = "mock error", context: ToolContext | None = None):
        super().__init__(context=context)
        self._error_message = error_message

    async def execute(self, **params) -> ToolResult:
        raise RuntimeError(self._error_message)


class MockSlowTool(Tool):
    """A mock tool that simulates slow execution."""

    name = "mock_slow_tool"
    description = "A mock tool that simulates slow execution"
    parameters = {
        "type": "object",
        "properties": {
            "delay": {"type": "number", "description": "Delay in seconds"},
        },
        "required": [],
    }

    def __init__(self, delay: float = 1.0, context: ToolContext | None = None):
        super().__init__(context=context)
        self._delay = delay

    async def execute(self, delay: float | None = None, **params) -> ToolResult:
        await asyncio.sleep(delay or self._delay)
        return ToolResult(content=f"Slept for {delay or self._delay}s")
