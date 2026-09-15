"""Unit tests for agent/hooks/builtin.py"""

from __future__ import annotations

import asyncio
import logging

import pytest

from aidynamic_agent.hooks.base import HookContext, HookEvent
from aidynamic_agent.hooks.builtin import (
    DebugHook,
    LoggingHook,
    MetricsData,
    MetricsHook,
    RateLimitHandlerHook,
    SafetyCheckHook,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(event: HookEvent, **overrides) -> HookContext:
    """Build a HookContext with the given overrides."""
    ctx = HookContext(event=event)
    for k, v in overrides.items():
        setattr(ctx, k, v)
    return ctx


# ---------------------------------------------------------------------------
# LoggingHook
# ---------------------------------------------------------------------------


class TestLoggingHook:
    def test_name_and_description(self):
        hook = LoggingHook()
        assert hook.name == "logging"
        assert hook.description == "Logs agent lifecycle events at appropriate log levels"
        assert hook.priority == 10

    def test_subscribed_events(self):
        hook = LoggingHook()
        expected = {
            HookEvent.BEFORE_LOOP,
            HookEvent.BEFORE_LLM_CALL,
            HookEvent.AFTER_LLM_CALL,
            HookEvent.BEFORE_TOOL_EXEC,
            HookEvent.AFTER_TOOL_EXEC,
            HookEvent.ON_ERROR,
            HookEvent.ON_TERMINATION,
        }
        assert set(hook.events) == expected

    @pytest.mark.asyncio
    async def test_before_loop_logs_info(self, caplog):
        hook = LoggingHook()
        ctx = _ctx(HookEvent.BEFORE_LOOP)
        with caplog.at_level(logging.INFO):
            await hook.handle(ctx)
        assert "Agent started" in caplog.text

    @pytest.mark.asyncio
    async def test_before_llm_call_logs_info_with_iteration(self, caplog):
        hook = LoggingHook()
        ctx = _ctx(HookEvent.BEFORE_LLM_CALL, data={"iteration": 3})
        with caplog.at_level(logging.INFO):
            await hook.handle(ctx)
        assert "LLM call #3" in caplog.text

    @pytest.mark.asyncio
    async def test_before_llm_call_missing_iteration(self, caplog):
        hook = LoggingHook()
        ctx = _ctx(HookEvent.BEFORE_LLM_CALL, data={})
        with caplog.at_level(logging.INFO):
            await hook.handle(ctx)
        assert "LLM call #?" in caplog.text

    @pytest.mark.asyncio
    async def test_after_llm_call_logs_debug(self, caplog):
        hook = LoggingHook()
        ctx = _ctx(HookEvent.AFTER_LLM_CALL, data={"stop_reason": "stop"})
        with caplog.at_level(logging.DEBUG):
            await hook.handle(ctx)
        assert "LLM response: stop" in caplog.text

    @pytest.mark.asyncio
    async def test_after_llm_call_unknown_stop_reason(self, caplog):
        hook = LoggingHook()
        ctx = _ctx(HookEvent.AFTER_LLM_CALL, data={})
        with caplog.at_level(logging.DEBUG):
            await hook.handle(ctx)
        assert "LLM response: unknown" in caplog.text

    @pytest.mark.asyncio
    async def test_before_tool_exec_logs_info(self, caplog):
        hook = LoggingHook()
        ctx = _ctx(HookEvent.BEFORE_TOOL_EXEC, data={"tool_name": "bash"})
        with caplog.at_level(logging.INFO):
            await hook.handle(ctx)
        assert "Tool call: bash" in caplog.text

    @pytest.mark.asyncio
    async def test_after_tool_exec_success(self, caplog):
        hook = LoggingHook()
        ctx = _ctx(
            HookEvent.AFTER_TOOL_EXEC,
            data={"tool_name": "read_file", "success": True},
        )
        with caplog.at_level(logging.INFO):
            await hook.handle(ctx)
        assert "Tool 'read_file' completed successfully" in caplog.text

    @pytest.mark.asyncio
    async def test_after_tool_exec_failure(self, caplog):
        hook = LoggingHook()
        ctx = _ctx(
            HookEvent.AFTER_TOOL_EXEC,
            data={"tool_name": "bash", "success": False, "error": "permission denied"},
        )
        with caplog.at_level(logging.ERROR):
            await hook.handle(ctx)
        assert "Tool 'bash' failed: permission denied" in caplog.text

    @pytest.mark.asyncio
    async def test_on_error_logs_error(self, caplog):
        hook = LoggingHook()
        ctx = _ctx(HookEvent.ON_ERROR, data={"error": "connection timeout"})
        with caplog.at_level(logging.ERROR):
            await hook.handle(ctx)
        assert "Agent error: connection timeout" in caplog.text

    @pytest.mark.asyncio
    async def test_on_termination_logs_info(self, caplog):
        hook = LoggingHook()
        ctx = _ctx(HookEvent.ON_TERMINATION, data={"reason": "goal_reached"})
        with caplog.at_level(logging.INFO):
            await hook.handle(ctx)
        assert "Agent terminated: goal_reached" in caplog.text

    @pytest.mark.asyncio
    async def test_never_blocks(self):
        hook = LoggingHook()
        for event in HookEvent:
            ctx = _ctx(event)
            result = await hook.handle(ctx)
            assert result.blocked is False

    @pytest.mark.asyncio
    async def test_returns_context_unchanged(self):
        hook = LoggingHook()
        ctx = _ctx(HookEvent.BEFORE_LOOP, data={"iteration": 1})
        result = await hook.handle(ctx)
        assert result is ctx


# ---------------------------------------------------------------------------
# MetricsHook
# ---------------------------------------------------------------------------


class TestMetricsHook:
    def test_name_and_description(self):
        hook = MetricsHook()
        assert hook.name == "metrics"
        assert "metrics" in hook.description.lower()
        assert hook.priority == 50

    def test_subscribed_events(self):
        hook = MetricsHook()
        expected = {
            HookEvent.BEFORE_LOOP,
            HookEvent.BEFORE_LLM_CALL,
            HookEvent.AFTER_LLM_CALL,
            HookEvent.BEFORE_TOOL_EXEC,
            HookEvent.AFTER_TOOL_EXEC,
            HookEvent.ON_ERROR,
            HookEvent.ON_TERMINATION,
        }
        assert set(hook.events) == expected

    @pytest.mark.asyncio
    async def test_before_loop_increments_total_loops(self):
        hook = MetricsHook()
        ctx = _ctx(HookEvent.BEFORE_LOOP)
        await hook.handle(ctx)
        assert hook.get_metrics().total_loops == 1

    @pytest.mark.asyncio
    async def test_multiple_before_loops_accumulate(self):
        hook = MetricsHook()
        for _ in range(5):
            await hook.handle(_ctx(HookEvent.BEFORE_LOOP))
        assert hook.get_metrics().total_loops == 5

    @pytest.mark.asyncio
    async def test_before_loop_sets_start_time(self):
        hook = MetricsHook()
        ctx = _ctx(HookEvent.BEFORE_LOOP)
        await hook.handle(ctx)
        assert hook.get_metrics().start_time > 0

    @pytest.mark.asyncio
    async def test_before_llm_call_increments_counter(self):
        hook = MetricsHook()
        await hook.handle(_ctx(HookEvent.BEFORE_LLM_CALL))
        assert hook.get_metrics().total_llm_calls == 1

    @pytest.mark.asyncio
    async def test_after_llm_call_accumulates_tokens(self):
        hook = MetricsHook()
        ctx = _ctx(
            HookEvent.AFTER_LLM_CALL,
            data={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        )
        await hook.handle(ctx)
        m = hook.get_metrics()
        assert m.total_input_tokens == 100
        assert m.total_output_tokens == 50
        assert m.total_tokens == 150

    @pytest.mark.asyncio
    async def test_after_llm_call_missing_tokens_default_zero(self):
        hook = MetricsHook()
        await hook.handle(_ctx(HookEvent.AFTER_LLM_CALL, data={}))
        m = hook.get_metrics()
        assert m.total_input_tokens == 0
        assert m.total_output_tokens == 0
        assert m.total_tokens == 0

    @pytest.mark.asyncio
    async def test_before_tool_exec_increments_and_tracks_name(self):
        hook = MetricsHook()
        await hook.handle(_ctx(HookEvent.BEFORE_TOOL_EXEC, data={"tool_name": "bash"}))
        m = hook.get_metrics()
        assert m.total_tool_calls == 1
        assert m.tool_call_counts == {"bash": 1}

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_accumulate(self):
        hook = MetricsHook()
        await hook.handle(_ctx(HookEvent.BEFORE_TOOL_EXEC, data={"tool_name": "bash"}))
        await hook.handle(_ctx(HookEvent.BEFORE_TOOL_EXEC, data={"tool_name": "bash"}))
        await hook.handle(_ctx(HookEvent.BEFORE_TOOL_EXEC, data={"tool_name": "read_file"}))
        m = hook.get_metrics()
        assert m.total_tool_calls == 3
        assert m.tool_call_counts == {"bash": 2, "read_file": 1}

    @pytest.mark.asyncio
    async def test_after_tool_exec_failure_tracks_error(self):
        hook = MetricsHook()
        await hook.handle(
            _ctx(
                HookEvent.AFTER_TOOL_EXEC,
                data={"tool_name": "bash", "success": False},
            )
        )
        m = hook.get_metrics()
        assert m.tool_error_counts == {"bash": 1}

    @pytest.mark.asyncio
    async def test_after_tool_exec_success_no_error(self):
        hook = MetricsHook()
        await hook.handle(
            _ctx(
                HookEvent.AFTER_TOOL_EXEC,
                data={"tool_name": "bash", "success": True},
            )
        )
        m = hook.get_metrics()
        assert m.tool_error_counts == {}

    @pytest.mark.asyncio
    async def test_on_error_increments(self):
        hook = MetricsHook()
        ctx = _ctx(HookEvent.ON_ERROR, data={"error_type": "connection_error"})
        await hook.handle(ctx)
        m = hook.get_metrics()
        assert m.total_errors == 1
        assert m.error_counts == {"connection_error": 1}

    @pytest.mark.asyncio
    async def test_multiple_errors_accumulate(self):
        hook = MetricsHook()
        await hook.handle(_ctx(HookEvent.ON_ERROR, data={"error_type": "timeout"}))
        await hook.handle(_ctx(HookEvent.ON_ERROR, data={"error_type": "timeout"}))
        await hook.handle(_ctx(HookEvent.ON_ERROR, data={"error_type": "auth_error"}))
        m = hook.get_metrics()
        assert m.total_errors == 3
        assert m.error_counts == {"timeout": 2, "auth_error": 1}

    @pytest.mark.asyncio
    async def test_on_termination_sets_end_time(self):
        hook = MetricsHook()
        await hook.handle(_ctx(HookEvent.BEFORE_LOOP))
        await hook.handle(_ctx(HookEvent.ON_TERMINATION))
        m = hook.get_metrics()
        assert m.end_time > 0
        assert m.total_duration >= 0

    @pytest.mark.asyncio
    async def test_llm_duration_tracking(self):
        hook = MetricsHook()
        await hook.handle(_ctx(HookEvent.BEFORE_LLM_CALL))
        # Simulate some work
        await asyncio.sleep(0.01)
        await hook.handle(_ctx(HookEvent.AFTER_LLM_CALL, data={}))
        m = hook.get_metrics()
        assert m.llm_duration > 0

    @pytest.mark.asyncio
    async def test_tool_duration_tracking(self):
        hook = MetricsHook()
        await hook.handle(_ctx(HookEvent.BEFORE_TOOL_EXEC, data={"tool_name": "bash"}))
        await asyncio.sleep(0.01)
        await hook.handle(
            _ctx(HookEvent.AFTER_TOOL_EXEC, data={"tool_name": "bash", "success": True})
        )
        m = hook.get_metrics()
        assert m.tool_duration > 0

    @pytest.mark.asyncio
    async def test_get_metrics_returns_metrics_data(self):
        hook = MetricsHook()
        metrics = hook.get_metrics()
        assert isinstance(metrics, MetricsData)

    @pytest.mark.asyncio
    async def test_never_blocks(self):
        hook = MetricsHook()
        for event in HookEvent:
            ctx = _ctx(event)
            result = await hook.handle(ctx)
            assert result.blocked is False

    @pytest.mark.asyncio
    async def test_returns_context(self):
        hook = MetricsHook()
        ctx = _ctx(HookEvent.BEFORE_LOOP)
        result = await hook.handle(ctx)
        assert result is ctx


# ---------------------------------------------------------------------------
# SafetyCheckHook
# ---------------------------------------------------------------------------


class TestSafetyCheckHook:
    def test_name_and_description(self):
        hook = SafetyCheckHook()
        assert hook.name == "safety_check"
        assert "blocks" in hook.description.lower()
        assert hook.priority == 1

    def test_subscribed_events(self):
        hook = SafetyCheckHook()
        assert hook.events == [HookEvent.BEFORE_TOOL_EXEC]

    def test_default_blocked_tools_empty(self):
        hook = SafetyCheckHook()
        assert hook.blocked_tools == set()

    def test_custom_blocked_tools(self):
        hook = SafetyCheckHook(blocked_tools=["bash", "rm"])
        assert hook.blocked_tools == {"bash", "rm"}

    @pytest.mark.asyncio
    async def test_allowed_tool_not_blocked(self):
        hook = SafetyCheckHook(blocked_tools=["dangerous_tool"])
        ctx = _ctx(HookEvent.BEFORE_TOOL_EXEC, data={"tool_name": "safe_tool"})
        result = await hook.handle(ctx)
        assert result.blocked is False
        assert "safety_blocked" not in result.metadata

    @pytest.mark.asyncio
    async def test_blocked_tool_sets_blocked(self):
        hook = SafetyCheckHook(blocked_tools=["dangerous_tool"])
        ctx = _ctx(HookEvent.BEFORE_TOOL_EXEC, data={"tool_name": "dangerous_tool"})
        result = await hook.handle(ctx)
        assert result.blocked is True
        assert result.metadata.get("safety_blocked") is True
        assert result.metadata.get("blocked_tool") == "dangerous_tool"

    @pytest.mark.asyncio
    async def test_add_blocked(self):
        hook = SafetyCheckHook()
        hook.add_blocked("new_tool")
        assert "new_tool" in hook.blocked_tools

    @pytest.mark.asyncio
    async def test_remove_blocked(self):
        hook = SafetyCheckHook(blocked_tools=["a", "b"])
        hook.remove_blocked("a")
        assert "a" not in hook.blocked_tools
        assert "b" in hook.blocked_tools

    @pytest.mark.asyncio
    async def test_remove_non_existent(self):
        hook = SafetyCheckHook(blocked_tools=["a"])
        hook.remove_blocked("z")  # Should not raise
        assert "a" in hook.blocked_tools

    @pytest.mark.asyncio
    async def test_non_tool_exec_event_ignored(self):
        """Events other than BEFORE_TOOL_EXEC should not block."""
        hook = SafetyCheckHook(blocked_tools=["bash"])
        ctx = _ctx(HookEvent.BEFORE_LLM_CALL)
        result = await hook.handle(ctx)
        assert result.blocked is False

    @pytest.mark.asyncio
    async def test_missing_tool_name_not_blocked(self):
        hook = SafetyCheckHook(blocked_tools=["bash"])
        ctx = _ctx(HookEvent.BEFORE_TOOL_EXEC, data={})
        result = await hook.handle(ctx)
        assert result.blocked is False


# ---------------------------------------------------------------------------
# DebugHook
# ---------------------------------------------------------------------------


class TestDebugHook:
    def test_name_and_description(self):
        hook = DebugHook()
        assert hook.name == "debug"
        assert "debug" in hook.description.lower()
        assert hook.priority == 200

    def test_subscribed_all_events(self):
        hook = DebugHook()
        assert set(hook.events) == set(HookEvent)

    @pytest.mark.asyncio
    async def test_all_events_handled(self):
        hook = DebugHook()
        for event in HookEvent:
            ctx = _ctx(event, data={"key": "val"}, metadata={"m": 1})
            result = await hook.handle(ctx)
            assert result.blocked is False

    @pytest.mark.asyncio
    async def test_never_blocks(self):
        hook = DebugHook()
        for event in HookEvent:
            ctx = _ctx(event)
            result = await hook.handle(ctx)
            assert result.blocked is False

    @pytest.mark.asyncio
    async def test_returns_context(self):
        hook = DebugHook()
        ctx = _ctx(HookEvent.BEFORE_LOOP)
        result = await hook.handle(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_logs_debug(self, caplog):
        hook = DebugHook()
        ctx = _ctx(HookEvent.BEFORE_LOOP, data={"k": "v"})
        with caplog.at_level(logging.DEBUG):
            await hook.handle(ctx)
        assert "DebugHook" in caplog.text
        assert "before_loop" in caplog.text


# ---------------------------------------------------------------------------
# RateLimitHandlerHook
# ---------------------------------------------------------------------------


class TestRateLimitHandlerHook:
    def test_name_and_description(self):
        hook = RateLimitHandlerHook()
        assert hook.name == "rate_limit_handler"
        assert hook.priority == 20

    def test_subscribed_events(self):
        hook = RateLimitHandlerHook()
        assert hook.events == [HookEvent.ON_ERROR]

    def test_default_retry_delay(self):
        hook = RateLimitHandlerHook()
        assert hook.default_retry_delay == 60.0

    def test_custom_retry_delay(self):
        hook = RateLimitHandlerHook(default_retry_delay=120.0)
        assert hook.default_retry_delay == 120.0

    @pytest.mark.asyncio
    async def test_detects_rate_limit_keyword(self):
        hook = RateLimitHandlerHook()
        ctx = _ctx(
            HookEvent.ON_ERROR,
            data={"error": "rate limit exceeded"},
        )
        result = await hook.handle(ctx)
        assert result.metadata.get("is_rate_limit") is True
        assert "suggested_retry_delay" in result.metadata

    @pytest.mark.asyncio
    async def test_detects_429(self):
        hook = RateLimitHandlerHook()
        ctx = _ctx(
            HookEvent.ON_ERROR,
            data={"error": "HTTP 429 too many requests"},
        )
        result = await hook.handle(ctx)
        assert result.metadata.get("is_rate_limit") is True

    @pytest.mark.asyncio
    async def test_detects_throttle(self):
        hook = RateLimitHandlerHook()
        ctx = _ctx(
            HookEvent.ON_ERROR,
            data={"error": "throttled by API"},
        )
        result = await hook.handle(ctx)
        assert result.metadata.get("is_rate_limit") is True

    @pytest.mark.asyncio
    async def test_detects_quota_exceeded(self):
        hook = RateLimitHandlerHook()
        ctx = _ctx(
            HookEvent.ON_ERROR,
            data={"error": "quota exceeded"},
        )
        result = await hook.handle(ctx)
        assert result.metadata.get("is_rate_limit") is True

    @pytest.mark.asyncio
    async def test_non_rate_limit_error(self):
        hook = RateLimitHandlerHook()
        ctx = _ctx(
            HookEvent.ON_ERROR,
            data={"error": "connection timeout"},
        )
        result = await hook.handle(ctx)
        assert "is_rate_limit" not in result.metadata

    @pytest.mark.asyncio
    async def test_uses_retry_after_from_data(self):
        hook = RateLimitHandlerHook(default_retry_delay=60.0)
        ctx = _ctx(
            HookEvent.ON_ERROR,
            data={"error": "rate limit", "retry_after": 30.0},
        )
        result = await hook.handle(ctx)
        assert result.metadata["suggested_retry_delay"] == 30.0

    @pytest.mark.asyncio
    async def test_uses_default_retry_delay(self):
        hook = RateLimitHandlerHook(default_retry_delay=120.0)
        ctx = _ctx(
            HookEvent.ON_ERROR,
            data={"error": "rate limit"},
        )
        result = await hook.handle(ctx)
        assert result.metadata["suggested_retry_delay"] == 120.0

    @pytest.mark.asyncio
    async def test_never_blocks(self):
        hook = RateLimitHandlerHook()
        ctx = _ctx(HookEvent.ON_ERROR, data={"error": "rate limit"})
        result = await hook.handle(ctx)
        assert result.blocked is False

    @pytest.mark.asyncio
    async def test_returns_context(self):
        hook = RateLimitHandlerHook()
        ctx = _ctx(HookEvent.ON_ERROR, data={"error": "timeout"})
        result = await hook.handle(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_rate_limit_underscore_variant(self):
        hook = RateLimitHandlerHook()
        ctx = _ctx(
            HookEvent.ON_ERROR,
            data={"error": "Error: rate_limit hit"},
        )
        result = await hook.handle(ctx)
        assert result.metadata.get("is_rate_limit") is True

    @pytest.mark.asyncio
    async def test_too_many_requests_variant(self):
        hook = RateLimitHandlerHook()
        ctx = _ctx(
            HookEvent.ON_ERROR,
            data={"error": "Too Many Requests. Try again later."},
        )
        result = await hook.handle(ctx)
        assert result.metadata.get("is_rate_limit") is True
