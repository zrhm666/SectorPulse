"""DashScope Adapter - fix tool_result compatibility for Alibaba Qwen models."""

from __future__ import annotations

import json
from typing import Any

from aidynamic_agent.core.message import (
    Message,
    TextBlock,
    ThinkingBlock,
    ToolDefinition,
    ToolResultBlock,
    ToolUseBlock,
)
from aidynamic_agent.llm.adapters.openai_adapter import OpenAIAdapter


class DashScopeAdapter(OpenAIAdapter):
    """Adapter for DashScope/Qwen API.

    Inherits from OpenAIAdapter, fixes tool_result compatibility.
    DashScope doesn't support {"type": "tool_result"}, only text/image_url/video_url/video.

    Key difference: ToolResultBlock is converted to text format instead of tool_result type.
    """

    def to_provider(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> dict:
        """Convert messages to DashScope-compatible format.

        Uses parent class logic but converts ToolResultBlock to text format.
        """
        result: list[dict] = []

        for msg in messages:
            role = self._map_role(msg.role)

            if role == "assistant":
                # Check if message is only tool results -> emit as tool-role
                tool_results = [b for b in msg.content if isinstance(b, ToolResultBlock)]
                has_non_tool_result = any(not isinstance(b, ToolResultBlock) for b in msg.content)

                if tool_results and not has_non_tool_result:
                    # DashScope fix: emit tool results as text, not tool_result type
                    # Convert to a text message describing the tool result
                    for tr in tool_results:
                        entry: dict[str, Any] = {
                            "role": "tool",
                            "tool_call_id": tr.tool_call_id,
                            # DashScope requires content as string, not {"type": "tool_result"}
                            "content": tr.tool_result_content,
                        }
                        result.append(entry)
                    continue

                # Normal assistant message - use parent class logic
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
                # Tool result blocks - DashScope fix: use plain text content
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
                # system and user roles
                entry = {"role": role}
                content_list: list[dict] = []

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
                        # DashScope fix: convert tool_result to text format
                        # This is the key difference from OpenAIAdapter
                        content_list.append(
                            {
                                "type": "text",
                                "text": f"[Tool Result for {block.tool_call_id}]: {block.tool_result_content}",
                            }
                        )
                    elif isinstance(block, ThinkingBlock):
                        # DashScope may not support thinking, convert to text
                        content_list.append(
                            {
                                "type": "text",
                                "text": f"[Thinking]: {block.thinking}",
                            }
                        )
                    else:
                        content_list.append({"type": "text", "text": str(block)})

                # System messages: plain string; user messages: array-of-blocks
                if (
                    role == "system"
                    and len(content_list) == 1
                    and content_list[0]["type"] == "text"
                ):
                    entry["content"] = content_list[0]["text"]
                else:
                    # DashScope fix: user messages with multiple blocks
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

    # Reuse parent class methods for from_provider_response, from_provider_chunk, etc.
    # DashScope uses OpenAI-compatible response format, so no override needed.
