"""Mock LLM Provider for testing."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from aidynamic_agent.core.message import (
    ContentBlockUnion,
    ContentType,
    FinishReason,
    Message,
    StreamChunk,
    TextBlock,
    ToolUseBlock,
)
from aidynamic_agent.llm.base import LLMProvider, LLMResponse
from aidynamic_agent.llm.exceptions import LLMError


@dataclass
class MockResponseConfig:
    """Configure a single mock response."""

    content: list[ContentBlockUnion]
    stop_reason: FinishReason = FinishReason.END_TURN
    usage: dict = field(default_factory=lambda: {"total_tokens": 100})
    error: LLMError | None = None  # If set, raise this error instead


class MockLLMProvider(LLMProvider):
    """Mock LLM Provider for testing.

    Can be configured to return specific responses in sequence,
    or raise exceptions to test error handling.
    """

    def __init__(self):
        self.response_sequence: list[MockResponseConfig] = []
        self.call_count: int = 0
        self.recorded_calls: list[tuple[list[Message], list | None]] = []

    def set_responses(self, responses: list[MockResponseConfig]):
        """Set response sequence - returns in call order."""
        self.response_sequence = responses
        self.call_count = 0
        self.recorded_calls = []

    def set_response(self, content: list[ContentBlockUnion], **kwargs):
        """Convenience: set a single response."""
        self.set_responses([MockResponseConfig(content=content, **kwargs)])

    async def create(
        self,
        messages: list[Message],
        tools: list | None = None,
        **kwargs,
    ) -> LLMResponse:
        """Return preset response, record call."""
        self.recorded_calls.append((messages, tools or []))

        if self.call_count < len(self.response_sequence):
            config = self.response_sequence[self.call_count]
            self.call_count += 1

            if config.error:
                raise config.error

            return LLMResponse(
                content=config.content,
                stop_reason=config.stop_reason,
                model="mock-model",
                usage=config.usage,
            )

        # Default response: text end turn
        return LLMResponse(
            content=[TextBlock(text="Mock default response")],
            stop_reason=FinishReason.END_TURN,
            model="mock-model",
            usage={"total_tokens": 50},
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list | None = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """Streaming mock - yields chunks character by character."""
        response = await self.create(messages, tools, **kwargs)

        for i, block in enumerate(response.content):
            if isinstance(block, TextBlock):
                for j, char in enumerate(block.text):
                    yield StreamChunk(
                        type=ContentType.TEXT,
                        delta=char,
                        index=j,
                    )
            elif isinstance(block, ToolUseBlock):
                yield StreamChunk(
                    type=ContentType.TOOL_USE,
                    delta={"name": block.tool_name, "input": block.tool_input},
                    tool_call_id=block.tool_call_id,
                    index=i,
                )

        yield StreamChunk(
            type=ContentType.TEXT,
            finish_reason=response.stop_reason,
        )

    async def close(self):
        """Close mock provider (no-op)."""
        pass
