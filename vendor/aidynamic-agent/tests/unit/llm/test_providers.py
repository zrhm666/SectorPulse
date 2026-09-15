from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from aidynamic_agent.core.message import Message, Role, TextBlock
from aidynamic_agent.llm.base import LLMResponse
from aidynamic_agent.llm.factory import ProviderFactory
from aidynamic_agent.llm.providers.anthropic import AnthropicProvider
from aidynamic_agent.llm.providers.openai import OpenAIProvider


def _make_httpx_response(status_code: int, json_body: dict | None = None) -> httpx.Response:
    """Create a minimal httpx.Response for SDK exception constructors."""
    return httpx.Response(
        status_code=status_code,
        json=json_body or {},
        request=httpx.Request("POST", "https://example.com"),
    )


# ---------------------------------------------------------------------------
# AnthropicProvider tests
# ---------------------------------------------------------------------------


class TestAnthropicProviderInstantiation:
    """Tests for AnthropicProvider instantiation."""

    def test_can_be_instantiated_with_defaults(self):
        provider = AnthropicProvider(api_key="sk-ant-test")
        assert provider.api_key == "sk-ant-test"
        assert provider.base_url is None
        assert provider.model == "claude-sonnet-4-20250514"
        assert provider.adapter is not None

    def test_can_be_instantiated_with_all_args(self):
        provider = AnthropicProvider(
            api_key="sk-ant-123",
            base_url="https://api.anthropic.com",
            model="claude-opus-4-20250514",
        )
        assert provider.api_key == "sk-ant-123"
        assert provider.base_url == "https://api.anthropic.com"
        assert provider.model == "claude-opus-4-20250514"

    def test_has_adapter(self):
        from aidynamic_agent.llm.adapters.anthropic_adapter import AnthropicAdapter

        provider = AnthropicProvider(api_key="sk-ant")
        assert isinstance(provider.adapter, AnthropicAdapter)


class TestAnthropicProviderCreate:
    """Tests for AnthropicProvider.create()."""

    @pytest.mark.asyncio
    async def test_create_returns_llm_response(self):
        provider = AnthropicProvider(api_key="sk-ant")

        from anthropic.types import Message as AnthropicMessage

        mock_message = AnthropicMessage.model_validate(
            {
                "id": "msg_test",
                "type": "message",
                "model": "claude-sonnet-4-20250514",
                "role": "assistant",
                "content": [{"type": "text", "text": "Hello, world!"}],
                "stop_reason": "end_turn",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            }
        )

        async def fake_create(**kwargs):
            return mock_message

        mock_client = MagicMock()
        mock_client.messages.create = fake_create
        mock_client.is_closed = False

        with patch.object(provider, "_get_client", return_value=mock_client):
            messages = [Message(role=Role.USER, content=[TextBlock(text="Hi")])]
            result = await provider.create(messages)

        assert isinstance(result, LLMResponse)
        assert result.model == "claude-sonnet-4-20250514"
        assert len(result.content) == 1

    @pytest.mark.asyncio
    async def test_create_raises_on_auth_error(self):
        provider = AnthropicProvider(api_key="sk-ant")

        import anthropic

        resp = _make_httpx_response(401, {"error": {"type": "authentication_error"}})
        err = anthropic.AuthenticationError(message="Invalid key", response=resp, body={})

        async def fake_create(**kwargs):
            raise err

        mock_client = MagicMock()
        mock_client.messages.create = fake_create
        mock_client.is_closed = False

        with patch.object(provider, "_get_client", return_value=mock_client):
            messages = [Message(role=Role.USER, content=[TextBlock(text="Hi")])]
            from aidynamic_agent.llm.exceptions import AuthenticationError

            with pytest.raises(AuthenticationError):
                await provider.create(messages)


class TestAnthropicProviderStream:
    """Tests for AnthropicProvider.stream()."""

    @pytest.mark.asyncio
    async def test_stream_yields_chunks(self):
        provider = AnthropicProvider(api_key="sk-ant")

        from anthropic.lib.streaming import TextEvent

        events = [
            TextEvent(type="text", text="Hel", snapshot="Hel"),
            TextEvent(type="text", text="lo", snapshot="Hello"),
        ]

        class MockStream:
            def __init__(self, evts):
                self._evts = iter(evts)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def __aiter__(self):
                return self

            async def __anext__(self):
                try:
                    return next(self._evts)
                except StopIteration:
                    raise StopAsyncIteration from None

        mock_client = MagicMock()
        mock_client.messages.stream.return_value = MockStream(events)
        mock_client.is_closed = False

        with patch.object(provider, "_get_client", return_value=mock_client):
            messages = [Message(role=Role.USER, content=[TextBlock(text="Hi")])]
            chunks = []
            async for chunk in provider.stream(messages):
                chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0].delta == "Hel"
        assert chunks[1].delta == "lo"


# ---------------------------------------------------------------------------
# OpenAIProvider tests
# ---------------------------------------------------------------------------


class TestOpenAIProviderInstantiation:
    """Tests for OpenAIProvider instantiation."""

    def test_can_be_instantiated_with_defaults(self):
        provider = OpenAIProvider(api_key="sk-openai-test")
        assert provider.api_key == "sk-openai-test"
        assert provider.base_url is None
        assert provider.model == "gpt-4o"
        assert provider.adapter is not None

    def test_can_be_instantiated_with_all_args(self):
        provider = OpenAIProvider(
            api_key="sk-123",
            base_url="https://api.openai.com/v1",
            model="gpt-4o-mini",
        )
        assert provider.api_key == "sk-123"
        assert provider.base_url == "https://api.openai.com/v1"
        assert provider.model == "gpt-4o-mini"

    def test_has_adapter(self):
        from aidynamic_agent.llm.adapters.openai_adapter import OpenAIAdapter

        provider = OpenAIProvider(api_key="sk-123")
        assert isinstance(provider.adapter, OpenAIAdapter)


class TestOpenAIProviderCreate:
    """Tests for OpenAIProvider.create()."""

    @pytest.mark.asyncio
    async def test_create_returns_llm_response(self):
        provider = OpenAIProvider(api_key="sk-123")

        from openai.types.chat import ChatCompletion, ChatCompletionMessage
        from openai.types.chat.chat_completion import Choice
        from openai.types.completion_usage import CompletionUsage

        mock_completion = ChatCompletion(
            id="chatcmpl-test",
            created=1,
            model="gpt-4o",
            object="chat.completion",
            choices=[
                Choice(
                    finish_reason="stop",
                    index=0,
                    message=ChatCompletionMessage(
                        role="assistant",
                        content="Hello, world!",
                    ),
                )
            ],
            usage=CompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

        async def fake_create(**kwargs):
            return mock_completion

        mock_client = MagicMock()
        mock_client.chat.completions.create = fake_create
        mock_client.is_closed = False

        with patch.object(provider, "_get_client", return_value=mock_client):
            messages = [Message(role=Role.USER, content=[TextBlock(text="Hi")])]
            result = await provider.create(messages)

        assert isinstance(result, LLMResponse)
        assert result.model == "gpt-4o"

    @pytest.mark.asyncio
    async def test_create_raises_on_auth_error(self):
        provider = OpenAIProvider(api_key="sk-123")

        import openai

        resp = _make_httpx_response(401, {"error": {"message": "Invalid API key"}})
        err = openai.AuthenticationError(message="Invalid key", response=resp, body=None)

        async def fake_create(**kwargs):
            raise err

        mock_client = MagicMock()
        mock_client.chat.completions.create = fake_create
        mock_client.is_closed = False

        with patch.object(provider, "_get_client", return_value=mock_client):
            messages = [Message(role=Role.USER, content=[TextBlock(text="Hi")])]
            from aidynamic_agent.llm.exceptions import AuthenticationError

            with pytest.raises(AuthenticationError):
                await provider.create(messages)


class TestOpenAIProviderStream:
    """Tests for OpenAIProvider.stream()."""

    @pytest.mark.asyncio
    async def test_stream_yields_chunks(self):
        provider = OpenAIProvider(api_key="sk-123")

        from openai.types.chat import ChatCompletionChunk
        from openai.types.chat.chat_completion_chunk import Choice, ChoiceDelta

        def make_chunk(content=None, finish_reason=None):
            delta = ChoiceDelta(content=content)
            choice = Choice(delta=delta, index=0, finish_reason=finish_reason)
            chunk = ChatCompletionChunk(
                id="chunk-test",
                created=1,
                model="gpt-4o",
                object="chat.completion.chunk",
                choices=[choice],
            )
            return chunk

        async def fake_create(**kwargs):
            chunks = [
                make_chunk(content="Hel"),
                make_chunk(content="lo"),
            ]

            class AsyncIter:
                def __init__(self, items):
                    self._items = iter(items)

                def __aiter__(self):
                    return self

                async def __anext__(self):
                    try:
                        return next(self._items)
                    except StopIteration:
                        raise StopAsyncIteration from None

            stream = AsyncIter(chunks)
            # Mimic AsyncStream.response for close() in cleanup
            stream.response = MagicMock()
            return stream

        mock_client = MagicMock()
        mock_client.chat.completions.create = fake_create
        mock_client.is_closed = False

        with patch.object(provider, "_get_client", return_value=mock_client):
            messages = [Message(role=Role.USER, content=[TextBlock(text="Hi")])]
            chunks = []
            async for chunk in provider.stream(messages):
                chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0].delta == "Hel"
        assert chunks[1].delta == "lo"


# ---------------------------------------------------------------------------
# ProviderFactory integration tests
# ---------------------------------------------------------------------------


class TestProviderFactoryIntegration:
    """Tests for ProviderFactory with concrete providers."""

    @pytest.fixture(autouse=True)
    def _setup_registry(self):
        """Ensure concrete providers are registered, then clean up."""
        ProviderFactory.register("anthropic", AnthropicProvider)
        ProviderFactory.register("openai", OpenAIProvider)
        yield
        ProviderFactory._registry.pop("anthropic", None)
        ProviderFactory._registry.pop("openai", None)

    def _make_config(
        self,
        provider: str = "anthropic",
        api_key: str = "sk-test",
        base_url: str | None = None,
        model: str = "default-model",
    ):
        from aidynamic_agent.config import ProviderConfig

        return ProviderConfig(
            LLM_PROVIDER=provider,
            API_KEY=api_key,
            BASE_URL=base_url,
            MODEL_ID=model,
        )

    def test_factory_creates_anthropic_provider(self):
        config = self._make_config(provider="anthropic", api_key="sk-ant", model="claude-test")
        provider = ProviderFactory.create(config)
        assert isinstance(provider, AnthropicProvider)
        assert provider.api_key == "sk-ant"
        assert provider.model == "claude-test"

    def test_factory_creates_openai_provider(self):
        config = self._make_config(provider="openai", api_key="sk-oai", model="gpt-4o-mini")
        provider = ProviderFactory.create(config)
        assert isinstance(provider, OpenAIProvider)
        assert provider.api_key == "sk-oai"
        assert provider.model == "gpt-4o-mini"

    def test_factory_lists_registered_providers(self):
        providers = ProviderFactory.list_providers()
        assert "anthropic" in providers
        assert "openai" in providers

    def test_factory_anthropic_has_correct_default_base_url(self):
        from aidynamic_agent.config import ProviderConfig

        config = ProviderConfig(LLM_PROVIDER="anthropic", API_KEY="sk-ant", _env_file=None)
        provider = ProviderFactory.create(config)
        assert isinstance(provider, AnthropicProvider)
        assert provider.base_url is None

    def test_factory_openai_has_correct_default_base_url(self):
        from aidynamic_agent.config import ProviderConfig

        config = ProviderConfig(LLM_PROVIDER="openai", API_KEY="sk-oai", _env_file=None)
        provider = ProviderFactory.create(config)
        assert isinstance(provider, OpenAIProvider)
        assert provider.base_url is None
