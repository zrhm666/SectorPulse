from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ContentType(Enum):
    TEXT = "text"
    THINKING = "thinking"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    ERROR = "error"  # Stream error block


class FinishReason(Enum):
    """Stream response finish reason"""

    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    STOP = "stop"
    STOP_SEQUENCE = "stop_sequence"
    ERROR = "error"
    MAX_TOKENS = "max_tokens"
    CONTENT_FILTER = "content_filter"


class Role(Enum):
    """Message role"""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


# Base class - only common fields
@dataclass(kw_only=True)
class ContentBlock:
    """Content block base class"""

    type: ContentType = field(default=ContentType.TEXT)
    metadata: dict = field(default_factory=dict)


# Subclass design - each type has dedicated fields
@dataclass
class TextBlock(ContentBlock):
    type: ContentType = field(default=ContentType.TEXT, init=False)
    text: str


@dataclass
class ThinkingBlock(ContentBlock):
    type: ContentType = field(default=ContentType.THINKING, init=False)
    thinking: str


@dataclass
class ToolUseBlock(ContentBlock):
    type: ContentType = field(default=ContentType.TOOL_USE, init=False)
    tool_call_id: str
    tool_name: str
    tool_input: dict


@dataclass
class ToolResultBlock(ContentBlock):
    type: ContentType = field(default=ContentType.TOOL_RESULT, init=False)
    tool_call_id: str  # Link to ToolUseBlock
    tool_result_content: str
    is_error: bool = False
    history_key: str | None = None  # Link to ToolHistoryStore


@dataclass
class ErrorBlock(ContentBlock):
    """Stream error block"""

    type: ContentType = field(default=ContentType.ERROR, init=False)
    error_code: str
    error_message: str


# Union type - for type annotations
ContentBlockUnion = TextBlock | ThinkingBlock | ToolUseBlock | ToolResultBlock | ErrorBlock


@dataclass
class Message:
    role: Role
    content: list[ContentBlockUnion]  # Force unified list format
    provider: str | None = None
    raw_response: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_text(cls, role: Role, text: str) -> Message:
        """Create from string (entry normalization)"""
        return cls(role=role, content=[TextBlock(text=text)])


@dataclass
class StreamChunk:
    """Stream response chunk, aligned with ContentBlock types"""

    type: ContentType
    delta: str | dict | None = None
    tool_call_id: str | None = None
    index: int = 0
    finish_reason: FinishReason | None = None


@dataclass
class ToolDefinition:
    name: str
    description: str
    input_schema: dict  # JSON Schema
    provider_config: dict = field(default_factory=dict)


# ToolResult and ErrorType also defined here (feedback point 3)
class ErrorType(Enum):
    SYSTEM_ERROR = "system_error"
    EXECUTION_ERROR = "execution_error"
    VALIDATION_ERROR = "validation_error"
    PERMISSION_ERROR = "permission_error"
    TIMEOUT_ERROR = "timeout_error"
    NOT_FOUND_ERROR = "not_found_error"


@dataclass
class ToolResult:
    """Tool execution result - for internal流转, finally converted to ToolResultBlock"""

    success: bool
    content: str
    tool_call_id: str | None = None  # Filled by Agent core when building ToolResultBlock
    error: str | None = None
    error_type: ErrorType | None = None

    # Token management
    truncated: bool = False
    summary: str | None = None
    original_length: int | None = None
    history_key: str | None = None

    def to_result_block(self, tool_call_id: str) -> ToolResultBlock:
        """Convert to ToolResultBlock for messages, pass history_key"""
        return ToolResultBlock(
            tool_call_id=tool_call_id,
            tool_result_content=self.content if self.success else (self.error or ""),
            is_error=not self.success,
            history_key=self.history_key,
        )
