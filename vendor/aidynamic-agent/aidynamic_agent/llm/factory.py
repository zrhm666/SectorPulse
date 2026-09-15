from __future__ import annotations

from collections.abc import Callable
from typing import cast

from aidynamic_agent.config import ProviderConfig
from aidynamic_agent.llm.base import LLMProvider
from aidynamic_agent.llm.providers.anthropic import AnthropicProvider
from aidynamic_agent.llm.providers.dashscope import DashScopeProvider
from aidynamic_agent.llm.providers.openai import OpenAIProvider


class ProviderFactory:
    """Factory for creating LLMProvider instances"""

    _registry: dict[str, type[LLMProvider]] = {}

    @classmethod
    def register(cls, name: str, provider_cls: type[LLMProvider]):
        """Register a provider implementation"""
        cls._registry[name.lower()] = provider_cls

    @classmethod
    def create(cls, config: ProviderConfig) -> LLMProvider:
        """Create provider from config"""
        provider_name = config.LLM_PROVIDER.lower()

        if provider_name not in cls._registry:
            available = ", ".join(cls._registry.keys())
            raise ValueError(f"Unknown provider '{config.LLM_PROVIDER}'. Available: {available}")

        provider_cls = cls._registry[provider_name]
        # Concrete providers define their own __init__; LLMProvider itself is a
        # pure ABC. Cast to a generic constructor since all registered providers
        # accept the standard (api_key, base_url, model) kwargs.
        constructor = cast(Callable[..., LLMProvider], provider_cls)
        return constructor(
            api_key=config.API_KEY,
            base_url=config.BASE_URL,
            model=config.MODEL_ID,
        )

    @classmethod
    def list_providers(cls) -> list[str]:
        return list(cls._registry.keys())


# Auto-register built-in providers
ProviderFactory.register("openai", OpenAIProvider)
ProviderFactory.register("anthropic", AnthropicProvider)
ProviderFactory.register("dashscope", DashScopeProvider)
