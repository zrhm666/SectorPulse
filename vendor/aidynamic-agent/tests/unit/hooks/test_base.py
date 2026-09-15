"""Unit tests for agent/hooks/base.py"""

from __future__ import annotations

import pytest

from aidynamic_agent.hooks.base import (
    Hook,
    HookContext,
    HookEvent,
    HookExecutor,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class NoOpHook(Hook):
    """Concrete hook that does nothing (for testing)."""

    name = "noop"
    description = "A hook that does nothing"
    events: list[HookEvent] = []

    async def handle(self, ctx: HookContext) -> HookContext:
        return ctx


class BlockingHook(Hook):
    """Concrete hook that blocks execution."""

    name = "blocking"
    description = "A hook that blocks"
    events: list[HookEvent] = []

    async def handle(self, ctx: HookContext) -> HookContext:
        ctx.blocked = True
        return ctx


class ModifyingHook(Hook):
    """Concrete hook that modifies context data."""

    name = "modifying"
    description = "A hook that modifies data"
    events: list[HookEvent] = []

    async def handle(self, ctx: HookContext) -> HookContext:
        ctx.data["modified"] = True
        return ctx


# ---------------------------------------------------------------------------
# HookEvent tests
# ---------------------------------------------------------------------------


class TestHookEvent:
    def test_enum_values(self):
        """All expected HookEvent values exist and have correct string values."""
        assert HookEvent.BEFORE_LLM_CALL.value == "before_llm_call"
        assert HookEvent.AFTER_LLM_CALL.value == "after_llm_call"
        assert HookEvent.BEFORE_TOOL_EXEC.value == "before_tool_exec"
        assert HookEvent.AFTER_TOOL_EXEC.value == "after_tool_exec"
        assert HookEvent.BEFORE_LOOP.value == "before_loop"
        assert HookEvent.AFTER_LOOP.value == "after_loop"
        assert HookEvent.ON_ERROR.value == "on_error"
        assert HookEvent.ON_TERMINATION.value == "on_termination"

    def test_enum_member_count(self):
        """HookEvent has exactly 8 members."""
        assert len(HookEvent) == 8


# ---------------------------------------------------------------------------
# HookContext tests
# ---------------------------------------------------------------------------


class TestHookContext:
    def test_creation_defaults(self):
        """HookContext initializes with sensible defaults."""
        ctx = HookContext(event=HookEvent.BEFORE_LLM_CALL)
        assert ctx.event == HookEvent.BEFORE_LLM_CALL
        assert ctx.data == {}
        assert ctx.blocked is False
        assert ctx.metadata == {}

    def test_creation_with_data(self):
        """HookContext accepts custom data."""
        ctx = HookContext(event=HookEvent.AFTER_LLM_CALL, data={"key": "value"})
        assert ctx.data == {"key": "value"}

    def test_blocked_flag(self):
        """HookContext blocked flag can be set."""
        ctx = HookContext(event=HookEvent.ON_ERROR, blocked=True)
        assert ctx.blocked is True

    def test_timestamp_is_set(self):
        """HookContext timestamp is automatically set to current time."""
        ctx = HookContext(event=HookEvent.BEFORE_LOOP)
        assert isinstance(ctx.timestamp, float)
        assert ctx.timestamp > 0

    def test_metadata(self):
        """HookContext metadata can be provided."""
        ctx = HookContext(
            event=HookEvent.ON_TERMINATION,
            metadata={"user": "test"},
        )
        assert ctx.metadata == {"user": "test"}


# ---------------------------------------------------------------------------
# Hook abstract class tests
# ---------------------------------------------------------------------------


class TestHook:
    def test_hook_is_abstract(self):
        """Hook cannot be instantiated directly."""
        with pytest.raises(TypeError):
            Hook()

    def test_concrete_subclass_instantiable(self):
        """A concrete subclass can be instantiated."""
        hook = NoOpHook()
        assert hook.name == "noop"
        assert hook.description == "A hook that does nothing"

    @pytest.mark.asyncio
    async def test_handle_returns_context(self):
        """handle() returns the (possibly modified) context."""
        hook = NoOpHook()
        ctx = HookContext(event=HookEvent.BEFORE_LLM_CALL)
        result = await hook.handle(ctx)
        assert result is ctx


# ---------------------------------------------------------------------------
# HookExecutor tests
# ---------------------------------------------------------------------------


class TestHookExecutor:
    def setup_method(self):
        self.executor = HookExecutor()

    # --- register ---

    def test_register_noop_hook(self):
        """Registering a hook with no events does nothing."""
        hook = NoOpHook()
        self.executor.register(hook)
        assert self.executor.list_hooks() == []

    def test_register_hook_with_single_event(self):
        """Registering a hook with one event stores it."""
        hook = NoOpHook()
        hook.events = [HookEvent.BEFORE_LLM_CALL]
        self.executor.register(hook)
        assert self.executor.list_hooks(HookEvent.BEFORE_LLM_CALL) == [hook]

    def test_register_hook_with_multiple_events(self):
        """Registering a hook with multiple events stores it under each."""
        hook = NoOpHook()
        hook.events = [HookEvent.BEFORE_LLM_CALL, HookEvent.AFTER_LLM_CALL]
        self.executor.register(hook)
        assert self.executor.list_hooks(HookEvent.BEFORE_LLM_CALL) == [hook]
        assert self.executor.list_hooks(HookEvent.AFTER_LLM_CALL) == [hook]

    def test_register_same_hook_twice(self):
        """Registering the same hook twice appends duplicates."""
        hook = NoOpHook()
        hook.events = [HookEvent.BEFORE_LLM_CALL]
        self.executor.register(hook)
        self.executor.register(hook)
        assert self.executor.list_hooks(HookEvent.BEFORE_LLM_CALL) == [hook, hook]

    # --- execute ---

    @pytest.mark.asyncio
    async def test_execute_no_hooks(self):
        """Execute with no registered hooks returns untouched context."""
        ctx = await self.executor.execute(HookEvent.BEFORE_LLM_CALL)
        assert ctx.event == HookEvent.BEFORE_LLM_CALL
        assert ctx.data == {}
        assert ctx.blocked is False

    @pytest.mark.asyncio
    async def test_execute_passes_data(self):
        """Execute passes provided data into the context."""
        ctx = await self.executor.execute(HookEvent.BEFORE_LLM_CALL, data={"input": "hello"})
        assert ctx.data == {"input": "hello"}

    @pytest.mark.asyncio
    async def test_execute_calls_hook(self):
        """Execute calls registered hook and returns modified context."""
        hook = ModifyingHook()
        hook.events = [HookEvent.BEFORE_LLM_CALL]
        self.executor.register(hook)

        ctx = await self.executor.execute(HookEvent.BEFORE_LLM_CALL)
        assert ctx.data["modified"] is True

    @pytest.mark.asyncio
    async def test_execute_stops_when_blocked(self):
        """Execution stops when a hook sets blocked=True."""
        blocking = BlockingHook()
        blocking.events = [HookEvent.BEFORE_LLM_CALL]

        modifying = ModifyingHook()
        modifying.events = [HookEvent.BEFORE_LLM_CALL]

        # Register blocking first so it runs before modifying
        self.executor.register(blocking)
        self.executor.register(modifying)

        ctx = await self.executor.execute(HookEvent.BEFORE_LLM_CALL)
        assert ctx.blocked is True
        # modifying hook should not have run
        assert "modified" not in ctx.data

    @pytest.mark.asyncio
    async def test_execute_multiple_hooks_chain(self):
        """Multiple hooks are called in registration order."""
        hook_a = ModifyingHook()
        hook_a.name = "a"
        hook_a.events = [HookEvent.BEFORE_LLM_CALL]

        hook_b = ModifyingHook()
        hook_b.name = "b"
        hook_b.events = [HookEvent.BEFORE_LLM_CALL]

        self.executor.register(hook_a)
        self.executor.register(hook_b)

        ctx = await self.executor.execute(HookEvent.BEFORE_LLM_CALL)
        # Both hooks ran (blocking not set by either)
        assert ctx.data.get("modified") is True

    # --- list_hooks ---

    def test_list_hooks_no_filter(self):
        """list_hooks() without filter returns all hooks across all events."""
        hook_a = NoOpHook()
        hook_a.events = [HookEvent.BEFORE_LLM_CALL]
        hook_b = NoOpHook()
        hook_b.events = [HookEvent.AFTER_LLM_CALL]

        self.executor.register(hook_a)
        self.executor.register(hook_b)

        all_hooks = self.executor.list_hooks()
        assert hook_a in all_hooks
        assert hook_b in all_hooks
        assert len(all_hooks) == 2

    def test_list_hooks_with_event_filter(self):
        """list_hooks(event) returns only hooks for that event."""
        hook_a = NoOpHook()
        hook_a.events = [HookEvent.BEFORE_LLM_CALL]
        hook_b = NoOpHook()
        hook_b.events = [HookEvent.AFTER_LLM_CALL]

        self.executor.register(hook_a)
        self.executor.register(hook_b)

        result = self.executor.list_hooks(HookEvent.BEFORE_LLM_CALL)
        assert result == [hook_a]

    def test_list_hooks_empty_event(self):
        """list_hooks(event) returns [] when no hooks registered for event."""
        result = self.executor.list_hooks(HookEvent.ON_ERROR)
        assert result == []

    # --- remove ---

    def test_remove_hook(self):
        """remove() removes the hook from all events."""
        hook = NoOpHook()
        hook.events = [HookEvent.BEFORE_LLM_CALL, HookEvent.AFTER_LLM_CALL]
        self.executor.register(hook)

        self.executor.remove(hook)
        assert self.executor.list_hooks(HookEvent.BEFORE_LLM_CALL) == []
        assert self.executor.list_hooks(HookEvent.AFTER_LLM_CALL) == []

    def test_remove_hook_not_registered(self):
        """remove() does nothing if hook was never registered."""
        hook = NoOpHook()
        hook.events = [HookEvent.BEFORE_LLM_CALL]
        # Don't register
        self.executor.remove(hook)  # Should not raise
        assert self.executor.list_hooks() == []

    # --- clear ---

    def test_clear(self):
        """clear() removes all hooks."""
        hook_a = NoOpHook()
        hook_a.events = [HookEvent.BEFORE_LLM_CALL]
        hook_b = NoOpHook()
        hook_b.events = [HookEvent.AFTER_LLM_CALL]
        self.executor.register(hook_a)
        self.executor.register(hook_b)

        self.executor.clear()
        assert self.executor.list_hooks() == []
        assert self.executor.list_hooks(HookEvent.BEFORE_LLM_CALL) == []
