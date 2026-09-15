from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class HookEvent(Enum):
    """Events that hooks can subscribe to."""

    BEFORE_LLM_CALL = "before_llm_call"
    AFTER_LLM_CALL = "after_llm_call"
    BEFORE_TOOL_EXEC = "before_tool_exec"
    AFTER_TOOL_EXEC = "after_tool_exec"
    BEFORE_LOOP = "before_loop"
    AFTER_LOOP = "after_loop"
    ON_ERROR = "on_error"
    ON_TERMINATION = "on_termination"


class HookFailMode(Enum):
    """What to do when a hook raises an exception."""

    SKIP = "skip"  # Log warning, continue to next hook
    RAISE = "raise"  # Propagate the exception


@dataclass
class HookContext:
    """Context passed to hooks on execution."""

    event: HookEvent
    data: dict[str, Any] = field(default_factory=dict)
    blocked: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    # Convenience accessors for common data keys
    @property
    def messages(self) -> list | None:
        return self.data.get("messages")

    @property
    def iteration(self) -> int:
        return self.data.get("iteration", 0)

    @property
    def tool_name(self) -> str | None:
        return self.data.get("tool_name")

    @property
    def tool_input(self) -> dict | None:
        return self.data.get("tool_input")

    @property
    def tool_call_id(self) -> str | None:
        return self.data.get("tool_call_id")

    @property
    def response(self) -> Any:
        return self.data.get("response")

    @property
    def result(self) -> str | None:
        return self.data.get("result")

    @property
    def is_error(self) -> bool:
        return self.data.get("is_error", False)

    @property
    def error(self) -> Any:
        return self.data.get("error")


# Events that support blocking (returning False stops execution)
BLOCKING_EVENTS: frozenset[HookEvent] = frozenset(
    {
        HookEvent.BEFORE_LLM_CALL,
        HookEvent.BEFORE_TOOL_EXEC,
    }
)


class Hook(ABC):
    """Base class for hooks. Return False from handle() to block on blocking events."""

    name: str = ""
    description: str = ""
    priority: int = 100  # Lower = runs first
    _registration_order: int = 0  # Set by HookExecutor on registration

    def __init__(self):
        # Subscribed events -- subclasses override or set explicitly.
        # If the subclass defines its own `events`, respect it;
        # otherwise default to all events.
        if "events" not in type(self).__dict__:
            self.events: list[HookEvent] = list(HookEvent)

    @abstractmethod
    async def handle(self, ctx: HookContext) -> HookContext:
        """Handle a hook event. Return the context (possibly modified).
        Set ctx.blocked = True to block (only on blocking events)."""
        ...

    def can_handle(self, event: HookEvent) -> bool:
        """Whether this hook handles the given event."""
        return event in self.events


class HookExecutor:
    """Executes hooks for a given event, handling sorting, errors, and blocking."""

    def __init__(self, fail_mode: HookFailMode = HookFailMode.SKIP):
        self.fail_mode = fail_mode
        self.hooks: list[Hook] = []
        self._next_order = 0

    def register(self, hook: Hook) -> None:
        """Register a hook, recording its registration order."""
        hook._registration_order = self._next_order
        self._next_order += 1
        self.hooks.append(hook)

    def _sort_hooks(self) -> list[Hook]:
        """Stable sort: priority ascending, then registration order."""
        return sorted(
            self.hooks,
            key=lambda h: (h.priority, h._registration_order),
        )

    def list_hooks(self, event: HookEvent | None = None) -> list[Hook]:
        """Return all hooks, or filter by event."""
        if event is None:
            return [h for h in self.hooks if h.events]
        return [h for h in self.hooks if event in h.events]

    def remove(self, hook: Hook) -> None:
        """Remove hook from all events (from the hooks list)."""
        self.hooks = [h for h in self.hooks if h is not hook]

    def clear(self) -> None:
        """Clear all hooks."""
        self.hooks.clear()

    async def execute(
        self,
        event: HookEvent,
        data: dict[str, Any] | None = None,
    ) -> HookContext:
        """Execute all hooks for the given event.

        Returns a HookContext with .blocked set to True if any hook returned
        a blocked context on a blocking event.
        """
        ctx = HookContext(event=event, data=data or {})
        is_blocking = event in BLOCKING_EVENTS

        for hook in self._sort_hooks():
            if not hook.can_handle(event):
                continue

            try:
                result = await hook.handle(ctx)
                if result.blocked and is_blocking:
                    return ctx  # Short-circuit on blocking event
            except Exception as e:
                if self.fail_mode == HookFailMode.RAISE:
                    raise
                logger.warning("Hook %s failed on %s: %s", hook.name, event.value, e)
                continue

        return ctx
