"""Common test fixtures."""

from __future__ import annotations

import pytest

from aidynamic_agent.core.message import (
    FinishReason,
    Message,
    Role,
    TextBlock,
    ToolUseBlock,
)
from aidynamic_agent.llm.base import LLMResponse
from aidynamic_agent.llm.exceptions import (
    AuthenticationError,
    ContextWindowExceededError,
    RateLimitError,
)
from aidynamic_agent.tools.context import ToolContext
from tests.mocks.mock_llm import MockLLMProvider


@pytest.fixture
def mock_provider():
    """Provide a MockLLMProvider."""
    return MockLLMProvider()


@pytest.fixture
def tool_context(tmp_path):
    """Provide a ToolContext with a temp directory."""
    return ToolContext(workdir=str(tmp_path))


@pytest.fixture
def sample_messages():
    """Sample conversation messages."""
    return [
        Message(role=Role.SYSTEM, content=[TextBlock(text="You are a helpful assistant.")]),
        Message(role=Role.USER, content=[TextBlock(text="Hello!")]),
    ]


@pytest.fixture
def sample_tool_use_block():
    """Sample ToolUseBlock."""
    return ToolUseBlock(
        tool_call_id="call_1",
        tool_name="bash",
        tool_input={"command": "echo hello"},
    )


@pytest.fixture
def sample_llm_response():
    """Sample LLMResponse with tool calls."""
    return LLMResponse(
        content=[
            ToolUseBlock(
                tool_call_id="call_1",
                tool_name="bash",
                tool_input={"command": "ls"},
            ),
        ],
        stop_reason=FinishReason.TOOL_USE,
        model="mock-model",
        usage={"total_tokens": 100},
    )


@pytest.fixture
def sample_text_response():
    """Sample LLMResponse with text."""
    return LLMResponse(
        content=[TextBlock(text="Task completed successfully.")],
        stop_reason=FinishReason.END_TURN,
        model="mock-model",
        usage={"total_tokens": 50},
    )


@pytest.fixture
def rate_limit_error():
    """Sample rate limit error."""
    return RateLimitError("Rate limit exceeded", retry_after=30)


@pytest.fixture
def auth_error():
    """Sample authentication error."""
    return AuthenticationError("Invalid API key")


@pytest.fixture
def context_window_error():
    """Sample context window exceeded error."""
    return ContextWindowExceededError("Context window exceeded")
