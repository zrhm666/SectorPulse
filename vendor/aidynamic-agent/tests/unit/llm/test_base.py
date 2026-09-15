from __future__ import annotations

import pytest

from aidynamic_agent.core.message import (
    FinishReason,
    TextBlock,
    ToolUseBlock,
)
from aidynamic_agent.llm.base import LLMProvider, LLMResponse

# ---------------------------------------------------------------------------
# LLMProvider is abstract — cannot be instantiated directly
# ---------------------------------------------------------------------------


class TestLLMProviderAbstract:
    def test_cannot_instantiate_llm_provider(self):
        """LLMProvider is abstract and raises TypeError on direct instantiation."""
        with pytest.raises(TypeError):
            LLMProvider()  # type: ignore[abstract, call-arg]

    def test_concrete_subclass_can_be_instantiated(self):
        """A concrete subclass that implements abstract methods can be instantiated."""
        from collections.abc import AsyncIterator

        from aidynamic_agent.core.message import Message, StreamChunk, ToolDefinition

        class DummyProvider(LLMProvider):
            async def create(
                self,
                messages: list[Message],
                tools: list[ToolDefinition] | None = None,
                **kwargs,
            ) -> LLMResponse:
                return LLMResponse(
                    content=[TextBlock(text="ok")],
                    stop_reason=FinishReason.END_TURN,
                    model="dummy",
                )

            async def stream(
                self,
                messages: list[Message],
                tools: list[ToolDefinition] | None = None,
                **kwargs,
            ) -> AsyncIterator[StreamChunk]:
                # pragma: no cover
                if False:
                    yield  # make it an async generator
                return
                yield  # type: ignore[unreachable]

        provider = DummyProvider()
        assert isinstance(provider, LLMProvider)


# ---------------------------------------------------------------------------
# LLMResponse creation and fields
# ---------------------------------------------------------------------------


class TestLLMResponse:
    def test_create_with_all_fields(self):
        response = LLMResponse(
            content=[TextBlock(text="Hello")],
            stop_reason=FinishReason.END_TURN,
            model="gpt-4",
            usage={"input_tokens": 10, "output_tokens": 5},
        )
        assert len(response.content) == 1
        assert response.stop_reason == FinishReason.END_TURN
        assert response.model == "gpt-4"
        assert response.usage == {"input_tokens": 10, "output_tokens": 5}

    def test_create_with_default_usage(self):
        response = LLMResponse(
            content=[TextBlock(text="Hello")],
            stop_reason=FinishReason.STOP,
            model="claude-3",
        )
        assert response.usage == {}


# ---------------------------------------------------------------------------
# LLMResponse.get_tool_calls()
# ---------------------------------------------------------------------------


class TestLLMResponseToolCalls:
    def test_get_tool_calls_returns_only_tool_use_blocks(self):
        content = [
            TextBlock(text="Let me check that."),
            ToolUseBlock(
                tool_call_id="call_1",
                tool_name="search",
                tool_input={"query": "test"},
            ),
            TextBlock(text="Done."),
        ]
        response = LLMResponse(
            content=content,
            stop_reason=FinishReason.TOOL_USE,
            model="gpt-4",
        )
        tool_calls = response.get_tool_calls()
        assert len(tool_calls) == 1
        assert isinstance(tool_calls[0], ToolUseBlock)
        assert tool_calls[0].tool_name == "search"

    def test_get_tool_calls_empty_when_no_tools(self):
        response = LLMResponse(
            content=[TextBlock(text="No tools here")],
            stop_reason=FinishReason.END_TURN,
            model="gpt-4",
        )
        assert response.get_tool_calls() == []

    def test_get_tool_calls_returns_multiple_tool_calls(self):
        tool1 = ToolUseBlock(
            tool_call_id="call_1",
            tool_name="search",
            tool_input={"query": "a"},
        )
        tool2 = ToolUseBlock(
            tool_call_id="call_2",
            tool_name="read_file",
            tool_input={"path": "test.py"},
        )
        response = LLMResponse(
            content=[tool1, TextBlock(text="middle"), tool2],
            stop_reason=FinishReason.TOOL_USE,
            model="gpt-4",
        )
        tool_calls = response.get_tool_calls()
        assert len(tool_calls) == 2
        assert tool_calls[0].tool_name == "search"
        assert tool_calls[1].tool_name == "read_file"


# ---------------------------------------------------------------------------
# LLMResponse.has_tool_calls property
# ---------------------------------------------------------------------------


class TestLLMResponseHasToolCalls:
    def test_has_tool_calls_true_when_tools_present(self):
        response = LLMResponse(
            content=[
                TextBlock(text="Calling tool"),
                ToolUseBlock(
                    tool_call_id="call_1",
                    tool_name="search",
                    tool_input={"query": "test"},
                ),
            ],
            stop_reason=FinishReason.TOOL_USE,
            model="gpt-4",
        )
        assert response.has_tool_calls is True

    def test_has_tool_calls_false_when_no_tools(self):
        response = LLMResponse(
            content=[TextBlock(text="Just text")],
            stop_reason=FinishReason.END_TURN,
            model="gpt-4",
        )
        assert response.has_tool_calls is False

    def test_has_tool_calls_false_with_empty_content(self):
        response = LLMResponse(
            content=[],
            stop_reason=FinishReason.END_TURN,
            model="gpt-4",
        )
        assert response.has_tool_calls is False

    def test_has_tool_calls_true_with_multiple_tool_calls(self):
        response = LLMResponse(
            content=[
                ToolUseBlock(tool_call_id="c1", tool_name="a", tool_input={}),
                ToolUseBlock(tool_call_id="c2", tool_name="b", tool_input={}),
                ToolUseBlock(tool_call_id="c3", tool_name="c", tool_input={}),
            ],
            stop_reason=FinishReason.TOOL_USE,
            model="gpt-4",
        )
        assert response.has_tool_calls is True
        assert len(response.get_tool_calls()) == 3
