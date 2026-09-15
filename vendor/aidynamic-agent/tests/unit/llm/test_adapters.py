"""Unit tests for LLM message adapters."""

from __future__ import annotations

import json

import pytest

from aidynamic_agent.core.message import (
    ContentType,
    FinishReason,
    Message,
    Role,
    StreamChunk,
    TextBlock,
    ThinkingBlock,
    ToolDefinition,
    ToolResultBlock,
    ToolUseBlock,
)
from aidynamic_agent.llm.adapters.anthropic_adapter import AnthropicAdapter
from aidynamic_agent.llm.adapters.base import MessageAdapter
from aidynamic_agent.llm.adapters.openai_adapter import OpenAIAdapter
from aidynamic_agent.llm.base import LLMResponse
from aidynamic_agent.llm.exceptions import (
    AuthenticationError,
    ContextWindowExceededError,
    LLMError,
    ProviderUnavailableError,
    RateLimitError,
)

# ====================================================================
# MessageAdapter abstractness
# ====================================================================


class TestMessageAdapterAbstract:
    def test_cannot_instantiate_abstract_adapter(self):
        with pytest.raises(TypeError):
            MessageAdapter()  # type: ignore[abstract, call-arg]

    def test_concrete_subclass_can_be_instantiated(self):
        class DummyAdapter(MessageAdapter):
            def to_provider(self, messages, tools=None, **kwargs):
                return {}

            def from_provider_response(self, response):
                return LLMResponse(
                    content=[TextBlock(text="ok")],
                    stop_reason=FinishReason.STOP,
                    model="dummy",
                )

            def from_provider_chunk(self, chunk):
                return StreamChunk(type=ContentType.TEXT, delta="")

            def map_exception(self, exception):
                return LLMError(str(exception))

        adapter = DummyAdapter()
        assert isinstance(adapter, MessageAdapter)


# ====================================================================
# AnthropicAdapter – to_provider (text messages)
# ====================================================================


class TestAnthropicAdapterText:
    @pytest.fixture
    def adapter(self):
        return AnthropicAdapter()

    def test_single_user_text_message(self, adapter: AnthropicAdapter):
        messages = [Message.from_text(Role.USER, "Hello")]
        result = adapter.to_provider(messages)

        assert "messages" in result
        assert len(result["messages"]) == 1
        msg = result["messages"][0]
        assert msg["role"] == "user"
        assert msg["content"] == [{"type": "text", "text": "Hello"}]

    def test_single_assistant_text_message(self, adapter: AnthropicAdapter):
        messages = [Message.from_text(Role.ASSISTANT, "Hi there")]
        result = adapter.to_provider(messages)

        msg = result["messages"][0]
        assert msg["role"] == "assistant"
        assert msg["content"] == [{"type": "text", "text": "Hi there"}]

    def test_system_message_becomes_top_level_key(self, adapter: AnthropicAdapter):
        messages = [Message.from_text(Role.SYSTEM, "You are helpful")]
        result = adapter.to_provider(messages)

        assert result["system"] == "You are helpful"
        assert result["messages"] == []

    def test_system_plus_user(self, adapter: AnthropicAdapter):
        messages = [
            Message.from_text(Role.SYSTEM, "Be concise"),
            Message.from_text(Role.USER, "What is 2+2?"),
        ]
        result = adapter.to_provider(messages)

        assert result["system"] == "Be concise"
        assert len(result["messages"]) == 1
        assert result["messages"][0]["role"] == "user"


# ====================================================================
# AnthropicAdapter – to_provider (tool use blocks)
# ====================================================================


class TestAnthropicAdapterToolUse:
    @pytest.fixture
    def adapter(self):
        return AnthropicAdapter()

    def test_tool_use_block_conversion(self, adapter: AnthropicAdapter):
        tool_call = ToolUseBlock(
            tool_call_id="call_abc",
            tool_name="search",
            tool_input={"query": "weather"},
        )
        msg = Message(role=Role.ASSISTANT, content=[tool_call])
        result = adapter.to_provider([msg])

        content = result["messages"][0]["content"][0]
        assert content["type"] == "tool_use"
        assert content["id"] == "call_abc"
        assert content["name"] == "search"
        assert content["input"] == {"query": "weather"}

    def test_tool_result_block_conversion(self, adapter: AnthropicAdapter):
        result_block = ToolResultBlock(
            tool_call_id="call_abc",
            tool_result_content="Sunny, 75F",
            is_error=False,
        )
        msg = Message(role=Role.USER, content=[result_block])
        out = adapter.to_provider([msg])

        content = out["messages"][0]["content"][0]
        assert content["type"] == "tool_result"
        assert content["tool_use_id"] == "call_abc"
        assert content["content"] == "Sunny, 75F"

    def test_tools_parameter(self, adapter: AnthropicAdapter):
        tool_def = ToolDefinition(
            name="search",
            description="Search the web",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        )
        messages = [Message.from_text(Role.USER, "Search for cats")]
        result = adapter.to_provider(messages, tools=[tool_def])

        assert len(result["tools"]) == 1
        assert result["tools"][0]["name"] == "search"
        assert result["tools"][0]["description"] == "Search the web"


# ====================================================================
# AnthropicAdapter – from_provider_response
# ====================================================================


class TestAnthropicAdapterFromResponse:
    @pytest.fixture
    def adapter(self):
        return AnthropicAdapter()

    def test_parse_text_response(self, adapter: AnthropicAdapter):
        response = {
            "content": [{"type": "text", "text": "Hello world"}],
            "stop_reason": "end_turn",
            "model": "claude-3-5-sonnet",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        result = adapter.from_provider_response(response)

        assert isinstance(result, LLMResponse)
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextBlock)
        assert result.content[0].text == "Hello world"
        assert result.stop_reason == FinishReason.END_TURN
        assert result.model == "claude-3-5-sonnet"
        assert result.usage == {"input_tokens": 10, "output_tokens": 5}

    def test_parse_tool_use_response(self, adapter: AnthropicAdapter):
        response = {
            "content": [
                {"type": "text", "text": "Let me check."},
                {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "search",
                    "input": {"query": "test"},
                },
            ],
            "stop_reason": "tool_use",
            "model": "claude-3",
        }
        result = adapter.from_provider_response(response)

        assert len(result.content) == 2
        assert isinstance(result.content[0], TextBlock)
        assert isinstance(result.content[1], ToolUseBlock)
        assert result.content[1].tool_call_id == "call_1"
        assert result.content[1].tool_name == "search"
        assert result.stop_reason == FinishReason.TOOL_USE

    def test_parse_thinking_response(self, adapter: AnthropicAdapter):
        response = {
            "content": [
                {"type": "thinking", "thinking": "Hmm, let me think..."},
                {"type": "text", "text": "The answer is 42"},
            ],
            "stop_reason": "end_turn",
            "model": "claude-3",
        }
        result = adapter.from_provider_response(response)

        assert len(result.content) == 2
        assert isinstance(result.content[0], ThinkingBlock)
        assert result.content[0].thinking == "Hmm, let me think..."


# ====================================================================
# AnthropicAdapter – from_provider_chunk (streaming)
# ====================================================================


class TestAnthropicAdapterStreaming:
    @pytest.fixture
    def adapter(self):
        return AnthropicAdapter()

    def test_text_delta(self, adapter: AnthropicAdapter):
        chunk = {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "Hello"},
            "index": 0,
        }
        result = adapter.from_provider_chunk(chunk)

        assert result.type == ContentType.TEXT
        assert result.delta == "Hello"
        assert result.index == 0

    def test_thinking_delta(self, adapter: AnthropicAdapter):
        chunk = {
            "type": "content_block_delta",
            "delta": {"type": "thinking_delta", "thinking": "Thinking..."},
            "index": 0,
        }
        result = adapter.from_provider_chunk(chunk)

        assert result.type == ContentType.THINKING
        assert result.delta == "Thinking..."

    def test_tool_use_start(self, adapter: AnthropicAdapter):
        chunk = {
            "type": "content_block_start",
            "index": 0,
            "content_block": {
                "type": "tool_use",
                "id": "call_1",
                "name": "search",
                "input": {},
            },
        }
        result = adapter.from_provider_chunk(chunk)

        assert result.type == ContentType.TOOL_USE
        assert result.tool_call_id == "call_1"

    def test_message_delta_stop(self, adapter: AnthropicAdapter):
        chunk = {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
        }
        result = adapter.from_provider_chunk(chunk)

        assert result.finish_reason == FinishReason.END_TURN


# ====================================================================
# AnthropicAdapter – map_exception
# ====================================================================


class TestAnthropicAdapterMapException:
    @pytest.fixture
    def adapter(self):
        return AnthropicAdapter()

    def test_authentication_error(self, adapter: AnthropicAdapter):
        exc = self._fake_exception("anthropic.AuthenticationError", "Invalid API key")
        mapped = adapter.map_exception(exc)
        assert isinstance(mapped, AuthenticationError)
        assert mapped.recoverable is False

    def test_rate_limit_error(self, adapter: AnthropicAdapter):
        exc = self._fake_exception("anthropic.RateLimitError", "Rate limited")
        mapped = adapter.map_exception(exc)
        assert isinstance(mapped, RateLimitError)
        assert mapped.recoverable is True

    def test_api_error(self, adapter: AnthropicAdapter):
        exc = self._fake_exception("anthropic.APIError", "Server error")
        mapped = adapter.map_exception(exc)
        assert isinstance(mapped, ProviderUnavailableError)

    def test_context_window_exceeded(self, adapter: AnthropicAdapter):
        exc = self._fake_exception(
            "anthropic.BadRequestError", "prompt is too long: context window exceeded"
        )
        mapped = adapter.map_exception(exc)
        assert isinstance(mapped, ContextWindowExceededError)

    def test_unknown_error(self, adapter: AnthropicAdapter):
        exc = ValueError("something weird")
        mapped = adapter.map_exception(exc)
        assert isinstance(mapped, LLMError)

    @staticmethod
    def _fake_exception(full_name: str, msg: str) -> Exception:
        mod, cls_name = full_name.rsplit(".", 1)
        exc_cls = type(cls_name, (Exception,), {})
        return exc_cls(msg)


# ====================================================================
# OpenAIAdapter – to_provider (text messages)
# ====================================================================


class TestOpenAIAdapterText:
    @pytest.fixture
    def adapter(self):
        return OpenAIAdapter()

    def test_single_user_text_message(self, adapter: OpenAIAdapter):
        messages = [Message.from_text(Role.USER, "Hello")]
        result = adapter.to_provider(messages)

        assert "messages" in result
        msg = result["messages"][0]
        assert msg["role"] == "user"
        assert msg["content"] == [{"type": "text", "text": "Hello"}]

    def test_single_assistant_text_message(self, adapter: OpenAIAdapter):
        messages = [Message.from_text(Role.ASSISTANT, "Hi there")]
        result = adapter.to_provider(messages)

        msg = result["messages"][0]
        assert msg["role"] == "assistant"
        assert msg["content"] == [{"type": "text", "text": "Hi there"}]

    def test_system_message(self, adapter: OpenAIAdapter):
        messages = [Message.from_text(Role.SYSTEM, "Be concise")]
        result = adapter.to_provider(messages)

        msg = result["messages"][0]
        assert msg["role"] == "system"
        assert msg["content"] == "Be concise"

    def test_multiple_messages(self, adapter: OpenAIAdapter):
        messages = [
            Message.from_text(Role.SYSTEM, "You are helpful"),
            Message.from_text(Role.USER, "What is 2+2?"),
            Message.from_text(Role.ASSISTANT, "It's 4"),
        ]
        result = adapter.to_provider(messages)

        assert len(result["messages"]) == 3
        assert result["messages"][0]["role"] == "system"
        assert result["messages"][1]["role"] == "user"
        assert result["messages"][2]["role"] == "assistant"


# ====================================================================
# OpenAIAdapter – to_provider (tool use blocks)
# ====================================================================


class TestOpenAIAdapterToolUse:
    @pytest.fixture
    def adapter(self):
        return OpenAIAdapter()

    def test_tool_use_in_assistant_message(self, adapter: OpenAIAdapter):
        tool_call = ToolUseBlock(
            tool_call_id="call_xyz",
            tool_name="search",
            tool_input={"query": "weather"},
        )
        msg = Message(role=Role.ASSISTANT, content=[tool_call])
        result = adapter.to_provider([msg])

        assistant_msg = result["messages"][0]
        assert "tool_calls" in assistant_msg
        tc = assistant_msg["tool_calls"][0]
        assert tc["id"] == "call_xyz"
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "search"
        assert json.loads(tc["function"]["arguments"]) == {"query": "weather"}

    def test_tool_result_becomes_role_tool(self, adapter: OpenAIAdapter):
        result_block = ToolResultBlock(
            tool_call_id="call_xyz",
            tool_result_content="Sunny",
        )
        # ToolResultBlock in an assistant message still gets emitted as a
        # separate tool-role message by the OpenAI adapter.
        msg = Message(role=Role.ASSISTANT, content=[result_block])
        result = adapter.to_provider([msg])

        tool_msg = result["messages"][0]
        assert tool_msg["role"] == "tool"
        assert tool_msg["tool_call_id"] == "call_xyz"
        assert tool_msg["content"] == "Sunny"

    def test_tools_parameter(self, adapter: OpenAIAdapter):
        tool_def = ToolDefinition(
            name="search",
            description="Search the web",
            input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
        )
        messages = [Message.from_text(Role.USER, "Search")]
        result = adapter.to_provider(messages, tools=[tool_def])

        assert result["tools"][0]["type"] == "function"
        assert result["tools"][0]["function"]["name"] == "search"


# ====================================================================
# OpenAIAdapter – from_provider_response
# ====================================================================


class TestOpenAIAdapterFromResponse:
    @pytest.fixture
    def adapter(self):
        return OpenAIAdapter()

    def test_parse_text_response(self, adapter: OpenAIAdapter):
        response = {
            "model": "gpt-4o",
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Hello world"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        result = adapter.from_provider_response(response)

        assert isinstance(result, LLMResponse)
        assert len(result.content) == 1
        assert isinstance(result.content[0], TextBlock)
        assert result.content[0].text == "Hello world"
        assert result.stop_reason == FinishReason.STOP
        assert result.model == "gpt-4o"
        assert result.usage == {"prompt_tokens": 10, "completion_tokens": 5}

    def test_parse_tool_use_response(self, adapter: OpenAIAdapter):
        response = {
            "model": "gpt-4o",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "search",
                                    "arguments": '{"query": "test"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }
        result = adapter.from_provider_response(response)

        assert len(result.content) == 1
        assert isinstance(result.content[0], ToolUseBlock)
        assert result.content[0].tool_call_id == "call_1"
        assert result.content[0].tool_name == "search"
        assert result.content[0].tool_input == {"query": "test"}
        assert result.stop_reason == FinishReason.TOOL_USE

    def test_parse_text_and_tools(self, adapter: OpenAIAdapter):
        response = {
            "model": "gpt-4o",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Let me look that up.",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "search",
                                    "arguments": '{"q": "cats"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }
        result = adapter.from_provider_response(response)

        assert len(result.content) == 2
        assert isinstance(result.content[0], TextBlock)
        assert isinstance(result.content[1], ToolUseBlock)


# ====================================================================
# OpenAIAdapter – from_provider_chunk (streaming)
# ====================================================================


class TestOpenAIAdapterStreaming:
    @pytest.fixture
    def adapter(self):
        return OpenAIAdapter()

    def test_text_delta(self, adapter: OpenAIAdapter):
        chunk = {
            "choices": [
                {
                    "delta": {"content": "Hello"},
                    "finish_reason": None,
                    "index": 0,
                }
            ]
        }
        result = adapter.from_provider_chunk(chunk)

        assert result.type == ContentType.TEXT
        assert result.delta == "Hello"

    def test_tool_call_delta(self, adapter: OpenAIAdapter):
        chunk = {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {
                                    "name": "search",
                                    "arguments": '{"query":',
                                },
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        }
        result = adapter.from_provider_chunk(chunk)

        assert result.type == ContentType.TOOL_USE
        assert result.tool_call_id == "call_1"
        assert result.delta["name"] == "search"

    def test_finish_delta(self, adapter: OpenAIAdapter):
        chunk = {
            "choices": [
                {
                    "delta": {},
                    "finish_reason": "stop",
                    "index": 0,
                }
            ]
        }
        result = adapter.from_provider_chunk(chunk)

        assert result.finish_reason == FinishReason.STOP
        assert result.delta is None


# ====================================================================
# OpenAIAdapter – map_exception
# ====================================================================


class TestOpenAIAdapterMapException:
    @pytest.fixture
    def adapter(self):
        return OpenAIAdapter()

    def test_authentication_error(self, adapter: OpenAIAdapter):
        exc = self._fake_exception("openai.AuthenticationError", "Invalid key")
        mapped = adapter.map_exception(exc)
        assert isinstance(mapped, AuthenticationError)

    def test_rate_limit_error(self, adapter: OpenAIAdapter):
        exc = self._fake_exception("openai.RateLimitError", "Too many requests")
        mapped = adapter.map_exception(exc)
        assert isinstance(mapped, RateLimitError)

    def test_api_error(self, adapter: OpenAIAdapter):
        exc = self._fake_exception("openai.APIError", "Server down")
        mapped = adapter.map_exception(exc)
        assert isinstance(mapped, ProviderUnavailableError)

    def test_api_connection_error(self, adapter: OpenAIAdapter):
        exc = self._fake_exception("openai.APIConnectionError", "Connection refused")
        mapped = adapter.map_exception(exc)
        assert isinstance(mapped, ProviderUnavailableError)

    def test_context_window_exceeded(self, adapter: OpenAIAdapter):
        exc = self._fake_exception("openai.BadRequestError", "maximum context length exceeded")
        mapped = adapter.map_exception(exc)
        assert isinstance(mapped, ContextWindowExceededError)

    def test_unknown_error(self, adapter: OpenAIAdapter):
        exc = ValueError("weird")
        mapped = adapter.map_exception(exc)
        assert isinstance(mapped, LLMError)

    @staticmethod
    def _fake_exception(full_name: str, msg: str) -> Exception:
        mod, cls_name = full_name.rsplit(".", 1)
        exc_cls = type(cls_name, (Exception,), {})
        return exc_cls(msg)
