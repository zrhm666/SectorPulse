from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from aidynamic_agent.hooks.base import Hook, HookContext, HookEvent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LoggingHook
# ---------------------------------------------------------------------------


class LoggingHook(Hook):
    """Logs agent lifecycle events at appropriate log levels."""

    name = "logging"
    description = "Logs agent lifecycle events at appropriate log levels"
    priority = 10

    def __init__(self):
        super().__init__()
        self.events = [
            HookEvent.BEFORE_LOOP,
            HookEvent.BEFORE_LLM_CALL,
            HookEvent.AFTER_LLM_CALL,
            HookEvent.BEFORE_TOOL_EXEC,
            HookEvent.AFTER_TOOL_EXEC,
            HookEvent.ON_ERROR,
            HookEvent.ON_TERMINATION,
        ]

    async def handle(self, ctx: HookContext) -> HookContext:
        event = ctx.event
        data = ctx.data

        if event == HookEvent.BEFORE_LOOP:
            logger.info("Agent started")
        elif event == HookEvent.BEFORE_LLM_CALL:
            iteration = data.get("iteration")
            iteration_str = str(iteration) if iteration is not None else "?"
            logger.info(f"LLM call #{iteration_str}")
        elif event == HookEvent.AFTER_LLM_CALL:
            stop_reason = data.get("stop_reason", "unknown")
            logger.debug(f"LLM response: {stop_reason}")
        elif event == HookEvent.BEFORE_TOOL_EXEC:
            tool_name = data.get("tool_name", "unknown")
            logger.info(f"Tool call: {tool_name}")
        elif event == HookEvent.AFTER_TOOL_EXEC:
            tool_name = data.get("tool_name", "unknown")
            success = data.get("success", True)
            if success:
                logger.info(f"Tool '{tool_name}' completed successfully")
            else:
                error = data.get("error", "unknown error")
                logger.error(f"Tool '{tool_name}' failed: {error}")
        elif event == HookEvent.ON_ERROR:
            error = data.get("error", "unknown")
            logger.error(f"Agent error: {error}")
        elif event == HookEvent.ON_TERMINATION:
            reason = data.get("reason", "unknown")
            logger.info(f"Agent terminated: {reason}")

        return ctx


# ---------------------------------------------------------------------------
# MetricsHook
# ---------------------------------------------------------------------------


@dataclass
class MetricsData:
    """Container for collected metrics."""

    total_loops: int = 0
    total_llm_calls: int = 0
    total_tool_calls: int = 0
    total_tokens: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_errors: int = 0
    start_time: float = 0.0
    end_time: float = 0.0
    total_duration: float = 0.0
    llm_duration: float = 0.0
    tool_duration: float = 0.0
    tool_call_counts: dict[str, int] = field(default_factory=dict)
    tool_error_counts: dict[str, int] = field(default_factory=dict)
    error_counts: dict[str, int] = field(default_factory=dict)

    # Internal timing state
    _llm_start: float = 0.0
    _tool_start: float = 0.0
    _tool_name_for_duration: str = ""


class MetricsHook(Hook):
    """Collects and tracks agent metrics."""

    name = "metrics"
    description = "Collects and tracks agent execution metrics"
    priority = 50

    def __init__(self):
        super().__init__()
        self.events = [
            HookEvent.BEFORE_LOOP,
            HookEvent.BEFORE_LLM_CALL,
            HookEvent.AFTER_LLM_CALL,
            HookEvent.BEFORE_TOOL_EXEC,
            HookEvent.AFTER_TOOL_EXEC,
            HookEvent.ON_ERROR,
            HookEvent.ON_TERMINATION,
        ]
        self._metrics = MetricsData()

    async def handle(self, ctx: HookContext) -> HookContext:
        event = ctx.event
        data = ctx.data

        if event == HookEvent.BEFORE_LOOP:
            self._metrics.total_loops += 1
            if self._metrics.start_time == 0.0:
                self._metrics.start_time = time.monotonic()

        elif event == HookEvent.BEFORE_LLM_CALL:
            self._metrics.total_llm_calls += 1
            self._metrics._llm_start = time.monotonic()

        elif event == HookEvent.AFTER_LLM_CALL:
            if self._metrics._llm_start > 0:
                self._metrics.llm_duration += time.monotonic() - self._metrics._llm_start
            self._metrics.total_input_tokens += data.get("input_tokens", 0)
            self._metrics.total_output_tokens += data.get("output_tokens", 0)
            self._metrics.total_tokens += data.get("total_tokens", 0)

        elif event == HookEvent.BEFORE_TOOL_EXEC:
            self._metrics.total_tool_calls += 1
            tool_name = data.get("tool_name", "unknown")
            self._metrics.tool_call_counts[tool_name] = (
                self._metrics.tool_call_counts.get(tool_name, 0) + 1
            )
            self._metrics._tool_start = time.monotonic()
            self._metrics._tool_name_for_duration = tool_name

        elif event == HookEvent.AFTER_TOOL_EXEC:
            tool_name = data.get("tool_name", "")
            if self._metrics._tool_name_for_duration == tool_name and self._metrics._tool_start > 0:
                self._metrics.tool_duration += time.monotonic() - self._metrics._tool_start
            if not data.get("success", True):
                self._metrics.tool_error_counts[tool_name] = (
                    self._metrics.tool_error_counts.get(tool_name, 0) + 1
                )

        elif event == HookEvent.ON_ERROR:
            self._metrics.total_errors += 1
            error_type = data.get("error_type", "unknown")
            self._metrics.error_counts[error_type] = (
                self._metrics.error_counts.get(error_type, 0) + 1
            )

        elif event == HookEvent.ON_TERMINATION:
            self._metrics.end_time = time.monotonic()
            if self._metrics.start_time > 0:
                self._metrics.total_duration = self._metrics.end_time - self._metrics.start_time

        return ctx

    def get_metrics(self) -> MetricsData:
        """Return the current metrics snapshot."""
        return self._metrics


# ---------------------------------------------------------------------------
# SafetyCheckHook
# ---------------------------------------------------------------------------


class SafetyCheckHook(Hook):
    """Blocks execution of dangerous tools."""

    name = "safety_check"
    description = "Blocks execution of dangerous or disallowed tools"
    priority = 1

    def __init__(self, blocked_tools: list[str] | None = None):
        super().__init__()
        self.events = [HookEvent.BEFORE_TOOL_EXEC]
        self.blocked_tools: set[str] = set(blocked_tools or [])

    async def handle(self, ctx: HookContext) -> HookContext:
        tool_name = ctx.data.get("tool_name")
        if tool_name and tool_name in self.blocked_tools:
            ctx.blocked = True
            ctx.metadata["safety_blocked"] = True
            ctx.metadata["blocked_tool"] = tool_name
        return ctx

    def add_blocked(self, tool_name: str) -> None:
        """Add a tool to the blocked list."""
        self.blocked_tools.add(tool_name)

    def remove_blocked(self, tool_name: str) -> None:
        """Remove a tool from the blocked list."""
        self.blocked_tools.discard(tool_name)


# ---------------------------------------------------------------------------
# DebugHook
# ---------------------------------------------------------------------------


class DebugHook(Hook):
    """Debug hook that logs all events at debug level."""

    name = "debug"
    description = "Debug hook that logs all events for inspection"
    priority = 200

    def __init__(self):
        super().__init__()
        self.events = list(HookEvent)

    async def handle(self, ctx: HookContext) -> HookContext:
        event_name = ctx.event.value
        logger.debug(f"DebugHook: {event_name}, data={ctx.data}")
        return ctx


# ---------------------------------------------------------------------------
# RateLimitHandlerHook
# ---------------------------------------------------------------------------


class RateLimitHandlerHook(Hook):
    """Detects rate limit errors and suggests retry delays."""

    name = "rate_limit_handler"
    description = "Detects rate limit errors and suggests retry delays"
    priority = 20

    _RATE_LIMIT_KEYWORDS = [
        "rate_limit",
        "rate limit",
        "429",
        "throttl",
        "quota exceeded",
        "too many requests",
    ]

    def __init__(self, default_retry_delay: float = 60.0):
        super().__init__()
        self.events = [HookEvent.ON_ERROR]
        self.default_retry_delay = default_retry_delay

    async def handle(self, ctx: HookContext) -> HookContext:
        error_str = str(ctx.data.get("error", "")).lower()

        is_rate_limit = any(kw in error_str for kw in self._RATE_LIMIT_KEYWORDS)

        if is_rate_limit:
            retry_after = ctx.data.get("retry_after")
            if retry_after is not None:
                delay = float(retry_after)
            else:
                delay = self.default_retry_delay

            ctx.metadata["is_rate_limit"] = True
            ctx.metadata["suggested_retry_delay"] = delay

        return ctx
