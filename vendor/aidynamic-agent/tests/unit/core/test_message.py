"""Tests for agent/core/message.py - Message model classes."""

from aidynamic_agent.core.message import (
    ContentType,
    ErrorBlock,
    ErrorType,
    FinishReason,
    Message,
    Role,
    StreamChunk,
    TextBlock,
    ThinkingBlock,
    ToolDefinition,
    ToolResult,
    ToolResultBlock,
    ToolUseBlock,
)

# --- Enum Tests ---


class TestContentType:
    """Test ContentType enum values."""

    def test_text_value(self):
        assert ContentType.TEXT.value == "text"

    def test_thinking_value(self):
        assert ContentType.THINKING.value == "thinking"

    def test_tool_use_value(self):
        assert ContentType.TOOL_USE.value == "tool_use"

    def test_tool_result_value(self):
        assert ContentType.TOOL_RESULT.value == "tool_result"

    def test_error_value(self):
        assert ContentType.ERROR.value == "error"

    def test_all_members_exist(self):
        members = {e.name for e in ContentType}
        assert members == {"TEXT", "THINKING", "TOOL_USE", "TOOL_RESULT", "ERROR"}


class TestFinishReason:
    """Test FinishReason enum values."""

    def test_end_turn_value(self):
        assert FinishReason.END_TURN.value == "end_turn"

    def test_tool_use_value(self):
        assert FinishReason.TOOL_USE.value == "tool_use"

    def test_stop_value(self):
        assert FinishReason.STOP.value == "stop"

    def test_error_value(self):
        assert FinishReason.ERROR.value == "error"

    def test_max_tokens_value(self):
        assert FinishReason.MAX_TOKENS.value == "max_tokens"


class TestRole:
    """Test Role enum values."""

    def test_system_value(self):
        assert Role.SYSTEM.value == "system"

    def test_user_value(self):
        assert Role.USER.value == "user"

    def test_assistant_value(self):
        assert Role.ASSISTANT.value == "assistant"


class TestErrorType:
    """Test ErrorType enum values."""

    def test_system_error(self):
        assert ErrorType.SYSTEM_ERROR.value == "system_error"

    def test_execution_error(self):
        assert ErrorType.EXECUTION_ERROR.value == "execution_error"

    def test_validation_error(self):
        assert ErrorType.VALIDATION_ERROR.value == "validation_error"

    def test_permission_error(self):
        assert ErrorType.PERMISSION_ERROR.value == "permission_error"

    def test_timeout_error(self):
        assert ErrorType.TIMEOUT_ERROR.value == "timeout_error"

    def test_not_found_error(self):
        assert ErrorType.NOT_FOUND_ERROR.value == "not_found_error"


# --- ContentBlock Subclass Tests ---


class TestTextBlock:
    """Test TextBlock creation."""

    def test_create_text_block(self):
        block = TextBlock(text="hello world")
        assert block.type == ContentType.TEXT
        assert block.text == "hello world"

    def test_text_block_has_default_metadata(self):
        block = TextBlock(text="test")
        assert block.metadata == {}

    def test_text_block_with_metadata(self):
        block = TextBlock(text="test", metadata={"key": "value"})
        assert block.metadata == {"key": "value"}

    def test_text_block_type_is_init_false(self):
        """Verify type field is not passed via __init__."""
        block = TextBlock(text="test")
        assert block.type == ContentType.TEXT


class TestThinkingBlock:
    """Test ThinkingBlock creation."""

    def test_create_thinking_block(self):
        block = ThinkingBlock(thinking="let me think...")
        assert block.type == ContentType.THINKING
        assert block.thinking == "let me think..."

    def test_thinking_block_has_default_metadata(self):
        block = ThinkingBlock(thinking="thinking")
        assert block.metadata == {}


class TestToolUseBlock:
    """Test ToolUseBlock creation."""

    def test_create_tool_use_block(self):
        block = ToolUseBlock(
            tool_call_id="call_123",
            tool_name="search",
            tool_input={"query": "python"},
        )
        assert block.type == ContentType.TOOL_USE
        assert block.tool_call_id == "call_123"
        assert block.tool_name == "search"
        assert block.tool_input == {"query": "python"}

    def test_tool_use_block_has_default_metadata(self):
        block = ToolUseBlock(
            tool_call_id="call_1",
            tool_name="test",
            tool_input={},
        )
        assert block.metadata == {}


class TestToolResultBlock:
    """Test ToolResultBlock creation."""

    def test_create_tool_result_block(self):
        block = ToolResultBlock(
            tool_call_id="call_123",
            tool_result_content="result data",
        )
        assert block.type == ContentType.TOOL_RESULT
        assert block.tool_call_id == "call_123"
        assert block.tool_result_content == "result data"
        assert block.is_error is False
        assert block.history_key is None

    def test_create_error_tool_result_block(self):
        block = ToolResultBlock(
            tool_call_id="call_123",
            tool_result_content="error message",
            is_error=True,
        )
        assert block.is_error is True

    def test_tool_result_block_with_history_key(self):
        block = ToolResultBlock(
            tool_call_id="call_123",
            tool_result_content="result",
            history_key="hist_key_1",
        )
        assert block.history_key == "hist_key_1"


class TestErrorBlock:
    """Test ErrorBlock creation."""

    def test_create_error_block(self):
        block = ErrorBlock(error_code="E001", error_message="Something went wrong")
        assert block.type == ContentType.ERROR
        assert block.error_code == "E001"
        assert block.error_message == "Something went wrong"


# --- Message Tests ---


class TestMessage:
    """Test Message creation and from_text()."""

    def test_create_message_with_content_list(self):
        msg = Message(
            role=Role.USER,
            content=[TextBlock(text="hello")],
        )
        assert msg.role == Role.USER
        assert len(msg.content) == 1
        assert isinstance(msg.content[0], TextBlock)
        assert msg.provider is None
        assert msg.raw_response == {}

    def test_message_from_text(self):
        msg = Message.from_text(Role.ASSISTANT, "response text")
        assert msg.role == Role.ASSISTANT
        assert len(msg.content) == 1
        assert isinstance(msg.content[0], TextBlock)
        assert msg.content[0].text == "response text"

    def test_message_content_is_always_list(self):
        """Message.content is always a list."""
        msg = Message.from_text(Role.USER, "test")
        assert isinstance(msg.content, list)

    def test_message_with_provider(self):
        msg = Message(
            role=Role.SYSTEM,
            content=[TextBlock(text="system prompt")],
            provider="anthropic",
        )
        assert msg.provider == "anthropic"

    def test_message_with_raw_response(self):
        msg = Message(
            role=Role.ASSISTANT,
            content=[TextBlock(text="hi")],
            raw_response={"id": "msg_123"},
        )
        assert msg.raw_response == {"id": "msg_123"}

    def test_message_with_mixed_content_blocks(self):
        msg = Message(
            role=Role.ASSISTANT,
            content=[
                ThinkingBlock(thinking="thinking..."),
                TextBlock(text="here is the answer"),
                ToolUseBlock(
                    tool_call_id="call_1",
                    tool_name="search",
                    tool_input={"q": "test"},
                ),
            ],
        )
        assert len(msg.content) == 3
        assert isinstance(msg.content[0], ThinkingBlock)
        assert isinstance(msg.content[1], TextBlock)
        assert isinstance(msg.content[2], ToolUseBlock)


# --- StreamChunk Tests ---


class TestStreamChunk:
    """Test StreamChunk creation."""

    def test_create_stream_chunk_with_delta(self):
        chunk = StreamChunk(type=ContentType.TEXT, delta="partial text", index=0)
        assert chunk.type == ContentType.TEXT
        assert chunk.delta == "partial text"
        assert chunk.index == 0
        assert chunk.tool_call_id is None
        assert chunk.finish_reason is None

    def test_create_stream_chunk_with_finish_reason(self):
        chunk = StreamChunk(
            type=ContentType.TEXT,
            delta="",
            finish_reason=FinishReason.END_TURN,
        )
        assert chunk.finish_reason == FinishReason.END_TURN

    def test_create_stream_chunk_with_tool_call_id(self):
        chunk = StreamChunk(
            type=ContentType.TOOL_USE,
            tool_call_id="call_abc",
            delta={"query": "test"},
        )
        assert chunk.tool_call_id == "call_abc"
        assert chunk.delta == {"query": "test"}

    def test_stream_chunk_default_values(self):
        chunk = StreamChunk(type=ContentType.TEXT)
        assert chunk.delta is None
        assert chunk.tool_call_id is None
        assert chunk.index == 0
        assert chunk.finish_reason is None


# --- ToolDefinition Tests ---


class TestToolDefinition:
    """Test ToolDefinition creation."""

    def test_create_tool_definition(self):
        td = ToolDefinition(
            name="search",
            description="Search the web",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        )
        assert td.name == "search"
        assert td.description == "Search the web"
        assert td.input_schema == {
            "type": "object",
            "properties": {"query": {"type": "string"}},
        }
        assert td.provider_config == {}

    def test_tool_definition_with_provider_config(self):
        td = ToolDefinition(
            name="search",
            description="Search",
            input_schema={"type": "object"},
            provider_config={"parallel": False},
        )
        assert td.provider_config == {"parallel": False}


# --- ToolResult Tests ---


class TestToolResult:
    """Test ToolResult creation and to_result_block()."""

    def test_create_successful_tool_result(self):
        result = ToolResult(success=True, content="output data", tool_call_id="call_1")
        assert result.success is True
        assert result.content == "output data"
        assert result.tool_call_id == "call_1"
        assert result.error is None
        assert result.error_type is None
        assert result.truncated is False
        assert result.summary is None

    def test_create_failed_tool_result(self):
        result = ToolResult(
            success=False,
            content="",
            error="command failed",
            error_type=ErrorType.EXECUTION_ERROR,
        )
        assert result.success is False
        assert result.error == "command failed"
        assert result.error_type == ErrorType.EXECUTION_ERROR

    def test_tool_result_with_truncation_info(self):
        result = ToolResult(
            success=True,
            content="truncated...",
            truncated=True,
            summary="shortened version",
            original_length=5000,
            history_key="hist_1",
        )
        assert result.truncated is True
        assert result.summary == "shortened version"
        assert result.original_length == 5000
        assert result.history_key == "hist_1"

    def test_to_result_block_on_success(self):
        result = ToolResult(
            success=True,
            content="tool output",
            history_key="hist_key_1",
        )
        block = result.to_result_block("call_123")
        assert isinstance(block, ToolResultBlock)
        assert block.tool_call_id == "call_123"
        assert block.tool_result_content == "tool output"
        assert block.is_error is False
        assert block.history_key == "hist_key_1"

    def test_to_result_block_on_error(self):
        result = ToolResult(
            success=False,
            content="",
            error="something broke",
            error_type=ErrorType.SYSTEM_ERROR,
        )
        block = result.to_result_block("call_456")
        assert isinstance(block, ToolResultBlock)
        assert block.tool_call_id == "call_456"
        assert block.tool_result_content == "something broke"
        assert block.is_error is True
        assert block.history_key is None

    def test_to_result_block_passes_history_key(self):
        result = ToolResult(
            success=True,
            content="data",
            history_key="stored_history",
        )
        block = result.to_result_block("call_789")
        assert block.history_key == "stored_history"
