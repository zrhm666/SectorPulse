from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from aidynamic_agent.core.message import (
    FinishReason,
    Message,
    StreamChunk,
    ToolDefinition,
)
from aidynamic_agent.llm.base import LLMResponse


class MessageAdapter(ABC):
    """Abstract base for message <-> provider format adapters.

    Subclasses must implement:
    - to_provider(messages, tools=None, **kwargs) -> dict
    - from_provider_response(response) -> LLMResponse
    - from_provider_chunk(chunk) -> StreamChunk | None
    - map_exception(exception) -> Exception
    """

    @abstractmethod
    def to_provider(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> dict:
        """Convert internal messages to provider API format."""
        ...

    @abstractmethod
    def from_provider_response(self, response: dict) -> LLMResponse:
        """Convert provider API response to LLMResponse."""
        ...

    @abstractmethod
    def from_provider_chunk(self, chunk: dict) -> StreamChunk | None:
        """Convert a single provider streaming chunk to StreamChunk."""
        ...

    @abstractmethod
    def map_exception(self, exception: Exception) -> Exception:
        """Map provider-specific exceptions to internal LLMError types."""
        ...

    def from_sdk_response(self, response: Any) -> LLMResponse:
        """Convert a typed SDK response object to LLMResponse.

        Concrete subclasses should implement this with specific type annotations.
        Default raises NotImplementedError for backward compatibility.
        """
        raise NotImplementedError(f"{type(self).__name__}.from_sdk_response is not implemented")

    def from_sdk_stream_event(self, event: Any) -> StreamChunk | None:
        """Convert a typed SDK streaming event to StreamChunk.

        Concrete subclasses should implement this with specific type annotations.
        Default raises NotImplementedError for backward compatibility.
        """
        raise NotImplementedError(f"{type(self).__name__}.from_sdk_stream_event is not implemented")

    @staticmethod
    def _map_stop_reason(reason: str | None) -> FinishReason:
        """Map provider stop reason to FinishReason enum."""
        if reason is None:
            return FinishReason.END_TURN
        mapping: dict[str, FinishReason] = {
            "stop": FinishReason.STOP,
            "end_turn": FinishReason.END_TURN,
            "stop_sequence": FinishReason.STOP_SEQUENCE,
            "tool_use": FinishReason.TOOL_USE,
            "tool_calls": FinishReason.TOOL_USE,
            "function_call": FinishReason.TOOL_USE,
            "length": FinishReason.MAX_TOKENS,
            "max_tokens": FinishReason.MAX_TOKENS,
            "content_filter": FinishReason.CONTENT_FILTER,
            "error": FinishReason.ERROR,
        }
        return mapping.get(reason, FinishReason.END_TURN)
