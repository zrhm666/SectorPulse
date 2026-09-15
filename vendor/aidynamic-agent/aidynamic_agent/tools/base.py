from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from aidynamic_agent.core.message import ToolDefinition, ToolResultBlock
from aidynamic_agent.tools.context import ToolContext


@dataclass
class ToolResult:
    """Tool execution result"""

    content: str
    success: bool = True
    error: str | None = None
    metadata: dict = field(default_factory=dict)

    def to_content_block(self) -> ToolResultBlock:
        """Convert to ToolResultBlock format for message context.

        Note: tool_call_id is left empty here and filled by agent core later.
        """
        return ToolResultBlock(
            tool_call_id="",  # Filled by agent core when adding to message
            tool_result_content=self.content if self.success else (self.error or ""),
            is_error=not self.success,
        )


class Tool(ABC):
    """Abstract base class for tools - template method pattern"""

    name: str = ""
    description: str = ""
    parameters: dict = {}  # JSON Schema for tool parameters
    tags: list[str] = []  # Permission tags

    def __init__(self, context: ToolContext | None = None):
        self.context = context or ToolContext()

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Implement tool logic"""
        pass

    async def run(self, **kwargs) -> ToolResult:
        """Template method with error handling and timing"""
        start_time = time.time()
        try:
            result = await self.execute(**kwargs)
            result.metadata["execution_time"] = time.time() - start_time
            result.metadata["tool_name"] = self.name
            return result
        except Exception as e:
            return ToolResult(
                content=f"Error: {e}",
                success=False,
                error=str(e),
                metadata={"execution_time": time.time() - start_time, "tool_name": self.name},
            )

    def to_tool_definition(self) -> ToolDefinition:
        """Convert to ToolDefinition format for LLM"""
        return ToolDefinition(
            name=self.name, description=self.description, input_schema=self.parameters
        )
