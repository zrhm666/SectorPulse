from __future__ import annotations

import pytest

from aidynamic_agent.core.message import Message, ToolDefinition
from aidynamic_agent.llm.base import LLMProvider, LLMResponse

# ---------------------------------------------------------------------------
# Concrete dummy provider for testing
# ---------------------------------------------------------------------------


class DummyProvider(LLMProvider):
    """Concrete subclass of LLMProvider for unit tests."""

    def __init__(self, api_key: str = "test-key"):
        self.api_key = api_key

    async def create(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs,
    ) -> LLMResponse:
        raise NotImplementedError  # pragma: no cover

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs,
    ):
        raise NotImplementedError  # pragma: no cover


# ---------------------------------------------------------------------------
# DummyProvider can be subclassed and instantiated
# ---------------------------------------------------------------------------


class TestDummyProviderInstantiation:
    def test_can_be_subclassed(self):
        """DummyProvider is a concrete subclass of LLMProvider."""
        assert DummyProvider is not None

    def test_subclass_instantiation_with_defaults(self):
        provider = DummyProvider()
        assert provider.api_key == "test-key"

    def test_subclass_instantiation_with_api_key(self):
        provider = DummyProvider(api_key="sk-123")
        assert provider.api_key == "sk-123"

    def test_inherits_from_llm_provider(self):
        assert issubclass(DummyProvider, LLMProvider)


# ---------------------------------------------------------------------------
# close() is safe to call even without implementation
# ---------------------------------------------------------------------------


class TestClose:
    @pytest.mark.asyncio
    async def test_close_is_safe(self):
        """LLMProvider.close() is a no-op by default."""
        provider = DummyProvider(api_key="sk-123")
        await provider.close()  # should not raise
