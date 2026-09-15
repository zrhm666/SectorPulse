"""
Agent SDK — A modular, extensible AI Agent framework with multi-provider support
and plugin architecture.

Install via: pip install aidynamic-agent
"""

__version__ = "0.3.0"

# Config
# Agents
from aidynamic_agent.agents import (
    AgentFactory,
    HookBlockedException,
    ParentAgent,
    SubAgent,
    SubAgentRequest,
    SubAgentResponse,
)
from aidynamic_agent.config import AgentConfig as AppConfigAgentConfig
from aidynamic_agent.config import AppConfig, ProviderConfig, ToolConfig

# Core
from aidynamic_agent.core import (
    AgentContext,
    AgentError,
    AgentResult,
    BaseAgent,
    CompactConfig,
    ContentBlock,
    ContentType,
    ErrorBlock,
    ErrorType,
    FinishReason,
    Message,
    MessageToolResult,
    Role,
    StreamChunk,
    TerminationReason,
    TextBlock,
    ThinkingBlock,
    ToolDefinition,
    ToolResultBlock,
    ToolResultSummary,
    ToolUseBlock,
)

# Hooks
from aidynamic_agent.hooks import (
    BLOCKING_EVENTS,
    Hook,
    HookContext,
    HookEvent,
    HookExecutor,
    HookFailMode,
)
from aidynamic_agent.hooks.builtin import (
    DebugHook,
    LoggingHook,
    MetricsData,
    MetricsHook,
    RateLimitHandlerHook,
    SafetyCheckHook,
)

# LLM
from aidynamic_agent.llm import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    ContextWindowExceededError,
    LLMError,
    LLMProvider,
    LLMResponse,
    ProviderFactory,
    ProviderUnavailableError,
    RateLimitError,
)

# LLM Providers
from aidynamic_agent.llm.adapters import AnthropicAdapter, MessageAdapter, OpenAIAdapter
from aidynamic_agent.llm.providers import AnthropicProvider, OpenAIProvider

# Managers
from aidynamic_agent.managers import (
    SkillManager,
    StateManager,
    TodoItem,
    TodoManager,
    ToolHistoryEntry,
    ToolHistoryStore,
)

# Tools
from aidynamic_agent.tools import Tool, ToolContext, ToolRegistry
from aidynamic_agent.tools import ToolResult as ToolToolResult

# Tools - Builtins
from aidynamic_agent.tools.builtins import BashTool, FileOpsTool

__all__ = [
    # Config
    "AppConfig",
    "AppConfigAgentConfig",  # aidynamic_agent.config.AgentConfig (distinct from core.AgentConfig)
    "ProviderConfig",
    "ToolConfig",
    # Core Agent
    "BaseAgent",
    "AgentResult",
    "AgentError",
    "TerminationReason",
    # Core Context
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
    "ToolDefinition",
    "ErrorType",
    "MessageToolResult",
    # LLM
    "LLMProvider",
    "LLMResponse",
    "ProviderFactory",
    "LLMError",
    "RateLimitError",
    "ContextWindowExceededError",
    "AuthenticationError",
    "ProviderUnavailableError",
    "APIError",
    "APIConnectionError",
    # LLM Providers
    "OpenAIProvider",
    "AnthropicProvider",
    # LLM Adapters
    "MessageAdapter",
    "OpenAIAdapter",
    "AnthropicAdapter",
    # Tools
    "Tool",
    "ToolToolResult",  # aidynamic_agent.tools.ToolResult
    "ToolContext",
    "ToolRegistry",
    # Tools - Builtins
    "BashTool",
    "FileOpsTool",
    # Agents
    "AgentFactory",
    "ParentAgent",
    "HookBlockedException",
    "SubAgent",
    "SubAgentRequest",
    "SubAgentResponse",
    # Hooks
    "Hook",
    "HookEvent",
    "HookFailMode",
    "HookContext",
    "HookExecutor",
    "BLOCKING_EVENTS",
    "LoggingHook",
    "MetricsData",
    "MetricsHook",
    "SafetyCheckHook",
    "DebugHook",
    "RateLimitHandlerHook",
    # Managers
    "StateManager",
    "TodoItem",
    "TodoManager",
    "SkillManager",
    "ToolHistoryEntry",
    "ToolHistoryStore",
]
