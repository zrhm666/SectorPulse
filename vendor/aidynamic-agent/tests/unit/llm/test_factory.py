from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from aidynamic_agent.config import ProviderConfig
from aidynamic_agent.llm.base import LLMProvider, LLMResponse
from aidynamic_agent.llm.factory import ProviderFactory


class DummyProvider(LLMProvider):
    """Concrete provider for testing factory."""

    def __init__(
        self,
        api_key: str = "",
        base_url: str | None = None,
        model: str = "dummy",
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    async def create(
        self,
        messages,
        tools=None,
        **kwargs,
    ) -> LLMResponse:
        pass

    async def stream(
        self,
        messages,
        tools=None,
        **kwargs,
    ) -> AsyncIterator:
        if False:
            yield
        return


class AnotherDummyProvider(LLMProvider):
    """Second concrete provider for testing multiple registrations."""

    def __init__(
        self,
        api_key: str = "",
        base_url: str | None = None,
        model: str = "another-dummy",
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    async def create(self, messages, tools=None, **kwargs) -> LLMResponse:
        pass

    async def stream(self, messages, tools=None, **kwargs) -> AsyncIterator:
        if False:
            yield
        return


@pytest.fixture(autouse=True)
def _clean_registry():
    """Reset the registry before and after each test to ensure isolation."""
    ProviderFactory._registry.clear()
    yield
    ProviderFactory._registry.clear()


class TestProviderFactoryRegister:
    """Tests for ProviderFactory.register()."""

    def test_register_adds_provider_to_registry(self):
        """register() stores the provider class under its lowercase name."""
        ProviderFactory.register("test_provider", DummyProvider)
        assert "test_provider" in ProviderFactory._registry
        assert ProviderFactory._registry["test_provider"] is DummyProvider

    def test_register_is_case_insensitive(self):
        """Registration normalises the name to lowercase."""
        ProviderFactory.register("MyProvider", DummyProvider)
        assert "myprovider" in ProviderFactory._registry
        assert "MyProvider" not in ProviderFactory._registry

    def test_register_multiple_providers(self):
        """Multiple providers can be registered simultaneously."""
        ProviderFactory.register("alpha", DummyProvider)
        ProviderFactory.register("beta", AnotherDummyProvider)
        assert len(ProviderFactory._registry) == 2
        assert ProviderFactory._registry["alpha"] is DummyProvider
        assert ProviderFactory._registry["beta"] is AnotherDummyProvider


class TestProviderFactoryCreate:
    """Tests for ProviderFactory.create()."""

    def _make_config(
        self,
        provider: str = "dummy",
        api_key: str = "sk-test",
        base_url: str | None = None,
        model: str = "dummy-model",
    ):
        return ProviderConfig(
            LLM_PROVIDER=provider,
            API_KEY=api_key,
            BASE_URL=base_url,
            MODEL_ID=model,
        )

    def test_create_returns_correct_provider_instance(self):
        """create() instantiates and returns the registered provider."""
        ProviderFactory.register("dummy", DummyProvider)
        config = self._make_config(provider="dummy", api_key="key123", model="test-model")
        result = ProviderFactory.create(config)
        assert isinstance(result, DummyProvider)
        assert result.api_key == "key123"
        assert result.model == "test-model"
        assert result.base_url is None

    def test_create_passes_base_url(self):
        """create() passes base_url through to the provider constructor."""
        ProviderFactory.register("dummy", DummyProvider)
        config = self._make_config(provider="dummy", base_url="https://api.example.com")
        result = ProviderFactory.create(config)
        assert isinstance(result, DummyProvider)
        assert result.base_url == "https://api.example.com"

    def test_create_raises_value_error_for_unknown_provider(self):
        """create() raises ValueError when the provider name is not registered."""
        config = self._make_config(provider="nonexistent")
        with pytest.raises(ValueError, match="Unknown provider 'nonexistent'"):
            ProviderFactory.create(config)

    def test_create_error_message_lists_available_providers(self):
        """The ValueError message includes the list of available providers."""
        ProviderFactory.register("alpha", DummyProvider)
        ProviderFactory.register("beta", AnotherDummyProvider)
        config = self._make_config(provider="unknown")
        with pytest.raises(ValueError, match="Available:"):
            ProviderFactory.create(config)


class TestProviderFactoryCreateCaseInsensitive:
    """Tests for case-insensitive provider name lookup in create()."""

    def _make_config(self, provider: str = "dummy"):
        return ProviderConfig(
            LLM_PROVIDER=provider,
            API_KEY="sk-test",
        )

    def test_create_looks_up_provider_case_insensitively(self):
        """Provider lookup is case-insensitive — registered as 'dummy', looked up as 'DUMMY'."""
        ProviderFactory.register("dummy", DummyProvider)
        config = self._make_config(provider="DUMMY")
        result = ProviderFactory.create(config)
        assert isinstance(result, DummyProvider)

    def test_create_mixed_case_lookup(self):
        """Mixed-case provider names are also resolved correctly."""
        ProviderFactory.register("openai", DummyProvider)
        config = self._make_config(provider="OpenAI")
        result = ProviderFactory.create(config)
        assert isinstance(result, DummyProvider)


class TestProviderFactoryListProviders:
    """Tests for ProviderFactory.list_providers()."""

    def test_list_providers_returns_registered_names(self):
        """list_providers() returns all registered provider names."""
        ProviderFactory.register("alpha", DummyProvider)
        ProviderFactory.register("beta", AnotherDummyProvider)
        providers = ProviderFactory.list_providers()
        assert "alpha" in providers
        assert "beta" in providers

    def test_list_providers_returns_lowercase_names(self):
        """list_providers() returns normalised (lowercase) names."""
        ProviderFactory.register("MyProvider", DummyProvider)
        providers = ProviderFactory.list_providers()
        assert "myprovider" in providers
        assert "MyProvider" not in providers

    def test_list_providers_empty_when_nothing_registered(self):
        """list_providers() returns an empty list when no providers are registered."""
        assert ProviderFactory.list_providers() == []
