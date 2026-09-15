"""Core module."""

from aidynamic_agent.core.agent import AgentError, AgentResult, BaseAgent, TerminationReason
from aidynamic_agent.core.context import AgentContext, CompactConfig, ToolResultSummary
from aidynamic_agent.core.message import (
    ContentBlock,
    ContentBlockUnion,
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
    ToolResultBlock,
    ToolUseBlock,
)
from aidynamic_agent.core.message import (
    ToolResult as MessageToolResult,
)

__all__ = [
    # Agent
    "BaseAgent",
    "AgentResult",
    "AgentError",
    "TerminationReason",
    # Context
    "AgentContext",
    "CompactConfig",
    "ToolResultSummary",
    # Messages
    "Message",
    "StreamChunk",
    "Role",
    "ContentType",
    "FinishReason",
    "ContentBlock",
    "TextBlock",
    "ThinkingBlock",
    "ToolUseBlock",
    "ToolResultBlock",
    "ErrorBlock",
    "ContentBlockUnion",
    "ToolDefinition",
    "ErrorType",
    # Note: ToolResult (from message) is exported as MessageToolResult
    # to avoid conflict with ToolResult from agent.tools
    "MessageToolResult",
]
