from __future__ import annotations

import json
import logging
from typing import Any

from openai.types.chat import ChatCompletion, ChatCompletionChunk

from aidynamic_agent.core.message import (
    ContentType,
    FinishReason,
    Message,
    Role,
    StreamChunk,
    TextBlock,
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

logger = logging.getLogger(__name__)


class OpenAIAdapter(MessageAdapter):
    """OpenAI API message adapter.

    Format mappings:
    - system messages: {\"role\": \"system\", \"content\": \"...\"}
    - user messages: {\"role\": \"user\", \"content\": [...]} (array for multi-content)
    - assistant messages: {\"role\": \"assistant\", \"content\": \"...\" or [blocks]}
    - tool calls in message: {\"role\": \"assistant\", \"tool_calls\": [{\"id\": \"...\", \"function\": {...}}]}
    - tool results: {\"role\": \"tool\", \"tool_call_id\": \"...\", \"content\": \"...\"}
    """

    def to_provider(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> dict:
        result: list[dict] = []
        for msg in messages:
            role = self._map_role(msg.role)

            if role == "assistant":
                # Check if message is only tool results -> emit as tool-role
                tool_results = [b for b in msg.content if isinstance(b, ToolResultBlock)]
                has_non_tool_result = any(not isinstance(b, ToolResultBlock) for b in msg.content)

                if tool_results and not has_non_tool_result:
                    # Emit as tool-role messages
                    for tr in tool_results:
                        entry: dict[str, Any] = {
                            "role": "tool",
                            "tool_call_id": tr.tool_call_id,
                            "content": tr.tool_result_content,
                        }
                        result.append(entry)
                    continue

                # Normal assistant message
                texts = [b for b in msg.content if isinstance(b, TextBlock)]
                tool_calls = [b for b in msg.content if isinstance(b, ToolUseBlock)]

                content_parts: list[dict] = []
                for t in texts:
                    content_parts.append({"type": "text", "text": t.text})

                entry = {"role": role}
                entry["content"] = content_parts if content_parts else None
                if tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": tc.tool_call_id,
                            "type": "function",
                            "function": {
                                "name": tc.tool_name,
                                "arguments": json.dumps(tc.tool_input),
                            },
                        }
                        for tc in tool_calls
                    ]
                if not entry.get("content") and not entry.get("tool_calls"):
                    entry["content"] = ""
                result.append(entry)

            elif role == "tool":
                # tool result blocks (explicit Role.TOOL)
                entry = {"role": "tool"}
                blocks = []
                for block in msg.content:
                    if isinstance(block, ToolResultBlock):
                        entry["tool_call_id"] = block.tool_call_id
                        blocks.append(block.tool_result_content)
                    elif isinstance(block, TextBlock):
                        blocks.append(block.text)
                entry["content"] = "\n".join(str(b) for b in blocks)
                result.append(entry)
            else:
                # user or system messages
                entry = {"role": role}
                content_list: list[dict] = []
                tool_results = []

                for block in msg.content:
                    if isinstance(block, TextBlock):
                        content_list.append({"type": "text", "text": block.text})
                    elif isinstance(block, ToolUseBlock):
                        content_list.append(
                            {
                                "type": "tool_call",
                                "tool_call_id": block.tool_call_id,
                                "name": block.tool_name,
                                "input": block.tool_input,
                            }
                        )
                    elif isinstance(block, ToolResultBlock):
                        tool_results.append(block)
                    else:
                        content_list.append({"type": "text", "text": str(block)})

                # OpenAI: user messages containing only ToolResultBlock(s)
                # must be converted to role: "tool" messages
                if role == "user" and tool_results and not content_list:
                    for tr in tool_results:
                        result.append(
                            {
                                "role": "tool",
                                "tool_call_id": tr.tool_call_id,
                                "content": tr.tool_result_content,
                            }
                        )
                    continue

                # System messages: plain string; user messages: array-of-blocks
                if (
                    role == "system"
                    and len(content_list) == 1
                    and content_list[0]["type"] == "text"
                ):
                    entry["content"] = content_list[0]["text"]
                else:
                    # OPENAI fix: user messages with multiple blocks
                    # Some versions may not support array format, flatten to text
                    if role == "user" and len(content_list) > 1:
                        # Flatten to single text for compatibility
                        text_parts = []
                        for item in content_list:
                            if item["type"] == "text":
                                text_parts.append(item["text"])
                            else:
                                text_parts.append(str(item))
                        entry["content"] = "\n".join(text_parts)
                    else:
                        entry["content"] = content_list if content_list else ""
                result.append(entry)

        output: dict[str, Any] = {"messages": result}
        if tools:
            output["tools"] = self.tools_to_provider(tools)
        return output

    def tools_to_provider(self, tools: list[ToolDefinition]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": {
                        **(t.input_schema or {}),
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            }
            for t in tools
        ]

    def from_provider_response(self, raw: dict) -> LLMResponse:
        choice = raw.get("choices", [{}])[0]
        finish_reason = self._map_stop_reason(choice.get("finish_reason"))

        message = choice.get("message", {})
        content: list = []

        text = message.get("content", "")
        if text:
            content.append(TextBlock(text=text))

        tool_calls = message.get("tool_calls", [])
        for tc in tool_calls:
            fn = tc.get("function", {})
            try:
                arguments = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                arguments = {}
            content.append(
                ToolUseBlock(
                    tool_call_id=tc.get("id", ""),
                    tool_name=fn.get("name", ""),
                    tool_input=arguments,
                )
            )

        usage = raw.get("usage")
        return LLMResponse(
            content=content,
            stop_reason=finish_reason,
            model=raw.get("model", "unknown"),
            usage=dict(usage) if usage else {},
            raw_response=raw,
        )

    def from_provider_chunk(self, raw: dict) -> StreamChunk | None:
        choices = raw.get("choices", [])
        if not choices:
            # Usage-only chunk (include_usage=True) — no content to yield
            return None
        choice = choices[0]
        delta = choice.get("delta", {})
        finish_reason = self._map_stop_reason(choice.get("finish_reason"))

        # Check for tool call delta first
        tool_calls = delta.get("tool_calls", [])
        if tool_calls:
            tc = tool_calls[0]
            fn = tc.get("function", {})
            return StreamChunk(
                type=ContentType.TOOL_USE,
                delta=fn,
                tool_call_id=tc.get("id"),
            )

        # Thinking/reasoning content (some OpenAI-compatible APIs send it)
        thinking = delta.get("reasoning_content") or delta.get("reasoning")
        if thinking is not None and thinking != "":
            return StreamChunk(
                type=ContentType.THINKING,
                delta=thinking,
            )

        text = delta.get("content")
        if text is not None and text != "":
            return StreamChunk(
                type=ContentType.TEXT,
                delta=text,
            )

        # If only finish reason, emit it
        if finish_reason != FinishReason.END_TURN:
            return StreamChunk(
                type=ContentType.TEXT,
                delta=None,
                finish_reason=finish_reason,
            )

        return None

    @staticmethod
    def _map_role(role: Role) -> str:
        mapping = {
            Role.SYSTEM: "system",
            Role.USER: "user",
            Role.ASSISTANT: "assistant",
            Role.TOOL: "tool",
        }
        return mapping.get(role, "user")

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
            if "context" in msg and ("exceed" in msg or "maximum context" in msg):
                return ContextWindowExceededError(str(exception))
        return LLMError(str(exception))

    def from_sdk_response(self, response: ChatCompletion) -> LLMResponse:
        """Convert OpenAI SDK ChatCompletion to LLMResponse."""
        choice = response.choices[0]
        finish_reason = self._map_stop_reason(choice.finish_reason)

        message = choice.message
        content: list = []

        if message.content:
            content.append(TextBlock(text=message.content))

        if message.tool_calls:
            for tc in message.tool_calls:
                if tc.type != "function":
                    continue  # only handle standard function calls
                try:
                    arguments = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                content.append(
                    ToolUseBlock(
                        tool_call_id=tc.id or "",
                        tool_name=tc.function.name or "",
                        tool_input=arguments,
                    )
                )

        usage = response.usage.model_dump() if response.usage else {}
        return LLMResponse(
            content=content,
            stop_reason=finish_reason,
            model=response.model or "unknown",
            usage=usage,
            raw_response=response.model_dump(),
        )

    def from_sdk_stream_event(self, chunk: ChatCompletionChunk) -> StreamChunk | None:
        """Convert OpenAI SDK ChatCompletionChunk to StreamChunk."""
        choices = chunk.choices
        if not choices:
            return None

        choice = choices[0]
        delta = choice.delta
        finish_reason = self._map_stop_reason(choice.finish_reason)

        # Tool call delta
        if delta.tool_calls:
            tc = delta.tool_calls[0]
            fn = tc.function
            delta_payload = {"name": fn.name, "arguments": fn.arguments} if fn is not None else {}
            return StreamChunk(
                type=ContentType.TOOL_USE,
                delta=delta_payload,
                tool_call_id=tc.id,
            )

        # Thinking/reasoning content
        reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
        if reasoning is not None and reasoning != "":
            return StreamChunk(
                type=ContentType.THINKING,
                delta=reasoning,
            )

        # Text delta
        if delta.content is not None and delta.content != "":
            return StreamChunk(
                type=ContentType.TEXT,
                delta=delta.content,
            )

        # Finish reason only
        if finish_reason != FinishReason.END_TURN:
            return StreamChunk(
                type=ContentType.TEXT,
                delta=None,
                finish_reason=finish_reason,
            )

        return None
