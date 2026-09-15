from __future__ import annotations

from typing import Any

from anthropic.types import Message as AnthropicMessage

from aidynamic_agent.core.message import (
    ContentType,
    Message,
    Role,
    StreamChunk,
    TextBlock,
    ThinkingBlock,
    ToolDefinition,
    ToolResultBlock,
    ToolUseBlock,
)
from aidynamic_agent.llm.adapters.base import MessageAdapter
from aidynamic_agent.llm.base import LLMResponse
from aidynamic_agent.llm.exceptions import (
    AuthenticationError,
    ContextWindowExceededError,
    LLMError,
    ProviderUnavailableError,
    RateLimitError,
)


class AnthropicAdapter(MessageAdapter):
    """Anthropic Claude API message adapter.

    Format mappings:
    - system is a separate top-level key: {\"system\": \"...\", \"messages\": [...]}
    - user messages: {\"role\": \"user\", \"content\": [{\"type\": \"text\", \"text\": \"...\"}]}
    - assistant messages: {\"role\": \"assistant\", \"content\": [...]}
    - tool use blocks: {\"type\": \"tool_use\", \"id\": \"...\", \"name\": \"...\", \"input\": {...}}
    - tool result blocks: {\"type\": \"tool_result\", \"tool_use_id\": \"...\", \"content\": \"...\"}
    - thinking blocks: {\"type\": \"thinking\", \"thinking\": \"...\"}
    """

    def to_provider(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> dict:
        """Convert messages to Anthropic format.

        Returns: {\"system\": \"...\", \"messages\": [...], \"tools\": [...]}
        """
        system_parts: list[str] = []
        result: list[dict] = []

        i = 0
        while i < len(messages):
            msg = messages[i]

            if msg.role == Role.SYSTEM:
                for block in msg.content:
                    if hasattr(block, "text"):
                        system_parts.append(block.text)
                i += 1
                continue

            # For user messages, check if next messages are tool results
            if msg.role == Role.USER:
                content_blocks: list[dict[str, Any]] = []
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        content_blocks.append({"type": "text", "text": block.text})
                    elif isinstance(block, ToolResultBlock):
                        content_blocks.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.tool_call_id,
                                "content": block.tool_result_content,
                                "is_error": block.is_error,
                            }
                        )

                result.append({"role": "user", "content": content_blocks})
                i += 1
                continue

            # Assistant messages
            elif msg.role == Role.ASSISTANT:
                content_blocks = []
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        content_blocks.append({"type": "text", "text": block.text})
                    elif isinstance(block, ThinkingBlock):
                        content_blocks.append(
                            {
                                "type": "thinking",
                                "thinking": block.thinking,
                            }
                        )
                    elif isinstance(block, ToolUseBlock):
                        content_blocks.append(
                            {
                                "type": "tool_use",
                                "id": block.tool_call_id,
                                "name": block.tool_name,
                                "input": block.tool_input,
                            }
                        )

                result.append({"role": "assistant", "content": content_blocks})
                i += 1
                continue

            # Fallback
            result.append({"role": "user", "content": [{"type": "text", "text": str(msg)}]})
            i += 1

        output: dict[str, Any] = {"messages": result}
        if system_parts:
            output["system"] = "\n\n".join(system_parts)
        if tools:
            output["tools"] = self.tools_to_provider(tools)
        return output

    def tools_to_provider(self, tools: list[ToolDefinition]) -> list[dict]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema or {"type": "object", "properties": {}},
                "strict": True,
            }
            for t in tools
        ]

    def from_provider_response(self, raw: dict) -> LLMResponse:
        content_block = raw.get("content", [])
        stop_reason = self._map_stop_reason(raw.get("stop_reason"))

        content: list = []
        for block in content_block:
            block_type = block.get("type", "text")

            if block_type == "text":
                content.append(TextBlock(text=block.get("text", "")))
            elif block_type == "tool_use":
                content.append(
                    ToolUseBlock(
                        tool_call_id=block.get("id", ""),
                        tool_name=block.get("name", ""),
                        tool_input=block.get("input", {}),
                    )
                )
            elif block_type == "thinking":
                content.append(
                    ThinkingBlock(
                        thinking=block.get("thinking", ""),
                    )
                )

        usage = raw.get("usage")
        return LLMResponse(
            content=content,
            stop_reason=stop_reason,
            model=raw.get("model", "unknown"),
            usage=dict(usage) if usage else {},
            raw_response=raw,
        )

    def from_provider_chunk(self, raw: dict) -> StreamChunk | None:
        event_type = raw.get("type", "")

        if event_type == "message_start":
            return None

        if event_type == "content_block_start":
            block = raw.get("content_block", {})
            block_type = block.get("type", "")
            index = raw.get("index", 0)

            if block_type == "tool_use":
                return StreamChunk(
                    type=ContentType.TOOL_USE,
                    tool_call_id=block.get("id", ""),
                    index=index,
                )
            if block_type == "thinking":
                return StreamChunk(
                    type=ContentType.THINKING,
                    delta="",
                    index=index,
                )
            return None

        if event_type == "content_block_delta":
            delta = raw.get("delta", {})
            delta_type = delta.get("type", "")
            index = raw.get("index", 0)

            if delta_type == "text_delta":
                return StreamChunk(
                    type=ContentType.TEXT,
                    delta=delta.get("text", ""),
                    index=index,
                )
            if delta_type == "thinking_delta":
                return StreamChunk(
                    type=ContentType.THINKING,
                    delta=delta.get("thinking", ""),
                    index=index,
                )
            if delta_type == "input_json_delta":
                return StreamChunk(
                    type=ContentType.TOOL_USE,
                    delta=delta.get("partial_json", ""),
                    index=index,
                )
            return None

        if event_type == "message_delta":
            delta = raw.get("delta", {})
            stop_reason = delta.get("stop_reason")
            if stop_reason:
                return StreamChunk(
                    type=ContentType.TEXT,
                    finish_reason=self._map_stop_reason(stop_reason),
                )
            return None

        return None

    @staticmethod
    def map_exception(exception: Exception) -> Exception:
        """Map provider-specific exceptions to internal LLMError types."""
        exc_type_name = type(exception).__name__
        msg = str(exception).lower()

        if exc_type_name in ("AuthenticationError",):
            err: LLMError = AuthenticationError(str(exception))
            err.recoverable = False
            return err
        if exc_type_name in ("RateLimitError",):
            err = RateLimitError(str(exception))
            err.recoverable = True
            return err
        if exc_type_name in ("APIError", "APIConnectionError"):
            return ProviderUnavailableError(str(exception))
        if exc_type_name in ("BadRequestError",):
            if "context" in msg and ("exceed" in msg or "too_long" in msg):
                return ContextWindowExceededError(str(exception))
        return LLMError(str(exception))

    def from_sdk_response(self, response: AnthropicMessage) -> LLMResponse:
        """Convert Anthropic SDK Message to LLMResponse."""
        content: list = []
        for block in response.content:
            if block.type == "text":
                content.append(TextBlock(text=block.text))
            elif block.type == "tool_use":
                content.append(
                    ToolUseBlock(
                        tool_call_id=block.id or "",
                        tool_name=block.name or "",
                        tool_input=block.input or {},
                    )
                )
            elif block.type == "thinking":
                content.append(
                    ThinkingBlock(
                        thinking=block.thinking or "",
                    )
                )

        usage = response.usage.model_dump() if response.usage else {}
        return LLMResponse(
            content=content,
            stop_reason=self._map_stop_reason(response.stop_reason),
            model=response.model or "unknown",
            usage=usage,
            raw_response=response.model_dump(),
        )

    def from_sdk_stream_event(self, event: Any) -> StreamChunk | None:
        """Convert an Anthropic SDK stream event to StreamChunk.

        ``client.messages.stream()`` yields a mix of raw events and
        convenience events (TextEvent, ThinkingEvent, ...), so the event
        is duck-typed via ``event.type`` and ``getattr``.
        """
        event_type = event.type

        if event_type == "text":
            return StreamChunk(
                type=ContentType.TEXT,
                delta=event.text,
            )

        if event_type == "thinking":
            return StreamChunk(
                type=ContentType.THINKING,
                delta=event.thinking,
            )

        if event_type == "input_json":
            return StreamChunk(
                type=ContentType.TOOL_USE,
                delta=event.partial_json,
            )

        if event_type == "content_block_start":
            block = event.content_block
            if block.type == "tool_use":
                return StreamChunk(
                    type=ContentType.TOOL_USE,
                    tool_call_id=getattr(block, "id", ""),
                )
            if block.type == "thinking":
                return StreamChunk(
                    type=ContentType.THINKING,
                    delta="",
                )
            return None

        if event_type == "content_block_delta":
            delta = event.delta
            delta_type = getattr(delta, "type", "")
            index = getattr(event, "index", 0)

            if delta_type == "text_delta":
                return StreamChunk(
                    type=ContentType.TEXT,
                    delta=getattr(delta, "text", ""),
                    index=index,
                )
            if delta_type == "thinking_delta":
                return StreamChunk(
                    type=ContentType.THINKING,
                    delta=getattr(delta, "thinking", ""),
                    index=index,
                )
            if delta_type == "input_json_delta":
                return StreamChunk(
                    type=ContentType.TOOL_USE,
                    delta=getattr(delta, "partial_json", ""),
                    index=index,
                )
            return None

        if event_type == "message_delta":
            delta = event.delta
            stop_reason = getattr(delta, "stop_reason", None)
            if stop_reason:
                return StreamChunk(
                    type=ContentType.TEXT,
                    finish_reason=self._map_stop_reason(stop_reason),
                )
            return None

        # content_block_stop, message_start, etc. — no content to yield
        return None
