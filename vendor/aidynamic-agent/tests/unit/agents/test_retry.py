"""Tests for retry logic in the agent framework."""

import pytest

from aidynamic_agent.core.agent import AgentConfig, BaseAgent, TerminationReason
from aidynamic_agent.core.context import AgentContext
from aidynamic_agent.core.message import FinishReason
from aidynamic_agent.llm.base import LLMResponse
from aidynamic_agent.llm.exceptions import (
    AuthenticationError,
    LLMError,
    RateLimitError,
)


class _TestAgent(BaseAgent):
    """Concrete agent implementation for testing retry logic."""

    def __init__(self, config: AgentConfig):
        super().__init__(config)
        self.context = AgentContext()
        self._responses: list = []
        self._response_index: int = 0

    def set_responses(self, responses: list):
        self._responses = responses
        self._response_index = 0

    async def _call_llm(self):
        if self._response_index < len(self._responses):
            resp = self._responses[self._response_index]
            self._response_index += 1
            if isinstance(resp, Exception):
                raise resp
            return resp
        # After exhausting configured responses, keep returning end_turn
        return LLMResponse(
            content=[], stop_reason=FinishReason.END_TURN, model="mock", usage={"total_tokens": 10}
        )

    async def _execute_tools(self, tool_calls: list) -> None:
        pass


class TestAgentRetry:
    """Test agent-level retry control.

    Note: BaseAgent._call_llm_with_retry retries ALL exceptions with
    exponential backoff, not just recoverable ones.
    """

    @pytest.mark.asyncio
    async def test_retry_succeeds_after_transient_failure(self):
        """Succeeds after one rate limit error."""
        config = AgentConfig(max_retries=3, max_loops=5)
        agent = _TestAgent(config)

        success_resp = LLMResponse(
            content=[], stop_reason=FinishReason.END_TURN, model="mock", usage={"total_tokens": 10}
        )
        agent.set_responses(
            [
                RateLimitError("rate limited", retry_after=0.01),
                success_resp,
            ]
        )
        result = await agent.run("test prompt")
        # After rate limit error, retry succeeds with end_turn -> END_TURN
        assert result.termination_reason == TerminationReason.END_TURN

    @pytest.mark.asyncio
    async def test_retry_exhausted_on_persistent_failure(self):
        """Raises after max_retries attempts."""
        config = AgentConfig(max_retries=2, max_loops=5)
        agent = _TestAgent(config)

        agent.set_responses(
            [
                RateLimitError("rate limited", retry_after=0.01),
                RateLimitError("rate limited", retry_after=0.01),
            ]
        )
        result = await agent.run("test prompt")
        assert result.termination_reason == TerminationReason.ERROR

    @pytest.mark.asyncio
    async def test_auth_error_still_retried(self):
        """BaseAgent retries all exceptions, including auth errors."""
        config = AgentConfig(max_retries=2, max_loops=5)
        agent = _TestAgent(config)

        agent.set_responses(
            [
                AuthenticationError("bad auth"),
                AuthenticationError("bad auth"),
            ]
        )
        result = await agent.run("test prompt")
        assert result.termination_reason == TerminationReason.ERROR
        # All retries were attempted
        assert agent._response_index == 2

    def test_llm_error_not_recoverable(self):
        """Base LLMError without status_code is not recoverable by default."""
        err = LLMError("generic")
        assert err.recoverable is False

    def test_rate_limit_error_is_recoverable(self):
        """RateLimitError is marked as recoverable."""
        err = RateLimitError("rate limited", retry_after=10)
        assert err.recoverable is True

    def test_auth_error_not_recoverable(self):
        """AuthenticationError is not recoverable."""
        err = AuthenticationError("bad key")
        assert err.recoverable is False
