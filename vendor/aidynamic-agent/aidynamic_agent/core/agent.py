from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

from aidynamic_agent.core.context import AgentContext, CompactConfig
from aidynamic_agent.core.message import FinishReason, Message, Role


class TerminationReason(Enum):
    END_TURN = "end_turn"
    MAX_LOOPS = "max_loops"
    TIMEOUT = "timeout"
    TOKEN_BUDGET = "token_budget"
    ERROR = "error"
    HOOK_BLOCKED = "hook_blocked"  # Hook blocks execution


@dataclass
class AgentError:
    """Single error record"""

    error_type: str  # "llm_error", "tool_error", "validation_error", "timeout"
    message: str
    loop_iteration: int
    tool_name: str | None = None
    recoverable: bool = False


@dataclass
class AgentConfig:
    max_loops: int = 30
    max_tokens: int = 8000
    system_prompt: str = ""  # Converted to Message at startup

    # Termination control
    total_timeout: int = 300
    token_budget: int = 100000

    # Tool permissions
    allowed_tool_tags: list[str] = field(default_factory=list)

    # Retry config
    max_retries: int = 3


@dataclass
class AgentResult:
    text: str
    termination_reason: TerminationReason
    loops_used: int
    tokens_used: int
    time_elapsed: float
    error: str | None = None
    error_detail: list[AgentError] = field(default_factory=list)


class BaseAgent(ABC):
    """Abstract base agent with async loop + termination + retry"""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.context: AgentContext | None = None
        self.start_time: float = 0
        self.tokens_used: int = 0
        self._errors: list[AgentError] = []

    async def _ensure_context(self) -> AgentContext:
        """Create the agent context on first use.

        Only initializes when None to preserve multi-turn conversation history
        across repeated ``run()`` calls.
        """
        if self.context is None:
            self.context = AgentContext(
                compact_config=CompactConfig(
                    trigger_token_threshold=int(self.config.token_budget * 0.8)
                )
            )
            if self.config.system_prompt:
                await self.context.add_message(
                    Message.from_text(Role.SYSTEM, self.config.system_prompt)
                )
        return self.context

    async def run(self, initial_input: str) -> AgentResult:
        """Enforce the deadline across model, retry and tool awaits.

        Caller cancellation deliberately propagates; only our own deadline is
        converted to a timeout result.
        """
        self._active_iteration = -1
        deadline = asyncio.timeout(self.config.total_timeout)
        try:
            async with deadline:
                return await self._run(initial_input)
        except TimeoutError:
            if not deadline.expired():
                raise
            return self._build_result(TerminationReason.TIMEOUT, self._active_iteration)

    async def _run(self, initial_input: str) -> AgentResult:
        """Main entry point"""
        self.start_time = time.time()
        self._errors = []  # Reset errors for each run

        context = await self._ensure_context()

        # Add new user message to existing context
        await context.add_message(Message.from_text(Role.USER, initial_input))

        # 2. Main loop
        for iteration in range(self.config.max_loops):
            self._active_iteration = iteration
            # Termination check at start of each iteration (feedback point 13)
            reason = await self._check_termination_conditions(iteration)
            if reason:
                return self._build_result(reason, iteration)

            # LLM call (with retry)
            try:
                response = await self._call_llm_with_retry()
            except Exception as e:
                self._record_error("llm_error", str(e), iteration, recoverable=False)
                return self._build_result(TerminationReason.ERROR, iteration, str(e))

            # Add LLM response to context as assistant message
            if not response.content and not response.has_tool_calls:
                # Empty response: if the provider signalled end-of-turn, this is a
                # terminal state (e.g. a retry that recovered with no output);
                # otherwise skip the turn and keep looping.
                if response.stop_reason in [FinishReason.END_TURN, FinishReason.STOP]:
                    return self._build_result(TerminationReason.END_TURN, iteration)
                continue
            await context.add_message(Message(role=Role.ASSISTANT, content=response.content))

            # A response may consume the remaining budget; do not perform its
            # requested side effects after the limit has been reached.
            if self.tokens_used >= self.config.token_budget:
                return self._build_result(TerminationReason.TOKEN_BUDGET, iteration)

            # Termination check after LLM returns (feedback point 13)
            # Only terminate if there are no pending tool calls to execute
            if not response.has_tool_calls and response.stop_reason in [
                FinishReason.END_TURN,
                FinishReason.STOP,
            ]:
                return self._build_result(TerminationReason.END_TURN, iteration)

            # Execute tools (if any)
            if response.has_tool_calls:
                await self._execute_tools(response.get_tool_calls())
                # Check compaction after tool execution
                await context.compact_if_needed()

        return self._build_result(TerminationReason.MAX_LOOPS, self.config.max_loops - 1)

    async def _check_termination_conditions(self, iteration: int) -> TerminationReason | None:
        """Check at start of each iteration (feedback point 13)"""
        elapsed = time.time() - self.start_time
        if elapsed > self.config.total_timeout:
            return TerminationReason.TIMEOUT

        if self.tokens_used >= self.config.token_budget:
            return TerminationReason.TOKEN_BUDGET

        return None

    async def _call_llm_with_retry(self):
        """Agent-level retry control (feedback point 6)"""
        for attempt in range(self.config.max_retries):
            try:
                return await self._call_llm()
            except Exception as e:
                self._record_error("llm_error", str(e), 0, recoverable=True)
                if attempt == self.config.max_retries - 1:
                    raise
                await asyncio.sleep(2**attempt)

    def _record_error(
        self,
        error_type: str,
        message: str,
        iteration: int,
        tool_name: str | None = None,
        recoverable: bool = False,
    ):
        """Record an error"""
        self._errors.append(
            AgentError(
                error_type=error_type,
                message=message,
                loop_iteration=iteration,
                tool_name=tool_name,
                recoverable=recoverable,
            )
        )

    def _build_result(
        self, reason: TerminationReason, iteration: int, error: str | None = None
    ) -> AgentResult:
        """Build final result"""
        # Fix: Only extract text from the LAST assistant message (not all history)
        text = ""
        if self.context:
            for msg in reversed(self.context.messages):
                if msg.role == Role.ASSISTANT:
                    for block in msg.content:
                        if hasattr(block, "text"):
                            text = block.text
                            break
                    if text:
                        break

        return AgentResult(
            text=text,
            termination_reason=reason,
            loops_used=iteration + 1,
            tokens_used=self.tokens_used,
            time_elapsed=time.time() - self.start_time,
            error=error,
            error_detail=self._errors[:],
        )

    @abstractmethod
    async def _call_llm(self):
        """Implement in subclass"""
        pass

    @abstractmethod
    async def _execute_tools(self, tool_calls: list) -> None:
        """Implement in subclass"""
        pass
