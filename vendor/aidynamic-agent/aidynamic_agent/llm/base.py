from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from aidynamic_agent.core.message import (
    ContentBlockUnion,
    FinishReason,
    Message,
    StreamChunk,
    ToolDefinition,
    ToolUseBlock,
)


class LLMProvider(ABC):
    """LLM Provider abstract base class - async only, no retry logic"""

    @abstractmethod
    async def create(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs,
    ) -> LLMResponse:
        """Non-streaming call"""
        pass

    @abstractmethod
    def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """Streaming call - returns async iterator, must support cleanup on error"""
        pass

    async def close(self):
        """Close underlying connections, release resources.

        Default no-op for providers that hold no resources to release.
        """
        return None


@dataclass
class LLMResponse:
    content: list[ContentBlockUnion]
    stop_reason: FinishReason
    model: str
    usage: dict = field(default_factory=dict)
    raw_response: dict = field(default_factory=dict, repr=False)

    def get_tool_calls(self) -> list[ToolUseBlock]:
        """Return tool use blocks (specific types)"""
        return [block for block in self.content if isinstance(block, ToolUseBlock)]

    @property
    def has_tool_calls(self) -> bool:
        return len(self.get_tool_calls()) > 0
