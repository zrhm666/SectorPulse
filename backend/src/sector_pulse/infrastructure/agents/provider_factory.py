"""Server-owned framework providers for deterministic and live agent execution."""

from __future__ import annotations

from collections import deque
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from aidynamic_agent.core.message import (
    ContentBlockUnion,
    FinishReason,
    Message,
    StreamChunk,
    TextBlock,
    ToolDefinition,
    ToolUseBlock,
)
from aidynamic_agent.llm.base import LLMProvider, LLMResponse
from aidynamic_agent.llm.providers.openai import OpenAIProvider

from sector_pulse.config.llm_config import LLMRoute, LLMRuntimeConfig
from sector_pulse.domain.orchestration.models import ModelPricing
from sector_pulse.infrastructure.agents.roles import AgentRole, RoleRuntime


@dataclass(frozen=True)
class FixtureToolCall:
    tool_call_id: str
    tool_name: str
    tool_input: dict[str, Any]


@dataclass(frozen=True)
class FixtureAgentTurn:
    """One deterministic framework response used by offline integration runs."""

    text: str | None = None
    tool_calls: tuple[FixtureToolCall, ...] = ()
    total_tokens: int = 0

    def __post_init__(self) -> None:
        if self.total_tokens < 0:
            raise ValueError("fixture token count cannot be negative")
        if (self.text is None) == (not self.tool_calls):
            raise ValueError("fixture turn requires exactly one of text or tool calls")


class FixtureAgentProvider(LLMProvider):
    def __init__(self, model: str, turns: tuple[FixtureAgentTurn, ...]) -> None:
        self.model = model
        self._turns = deque(turns)

    async def create(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        del messages, tools, kwargs
        if not self._turns:
            raise RuntimeError(f"fixture agent responses exhausted for model: {self.model}")
        turn = self._turns.popleft()
        content: list[ContentBlockUnion] = (
            [TextBlock(text=turn.text)]
            if turn.text is not None
            else [
                ToolUseBlock(
                    tool_call_id=call.tool_call_id,
                    tool_name=call.tool_name,
                    tool_input=call.tool_input,
                )
                for call in turn.tool_calls
            ]
        )
        return LLMResponse(
            content=content,
            stop_reason=FinishReason.END_TURN if turn.text is not None else FinishReason.TOOL_USE,
            model=self.model,
            usage={
                "prompt_tokens": 0,
                "completion_tokens": turn.total_tokens,
                "total_tokens": turn.total_tokens,
            },
        )

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        del messages, tools, kwargs
        raise NotImplementedError("fixture agent streaming is not supported")
        yield  # pragma: no cover


class AgentProviderFactory:
    """Build only providers supported by the embedded aidynamic-agent framework."""

    def __init__(
        self,
        *,
        fixture_turns: Mapping[AgentRole, tuple[FixtureAgentTurn, ...]] | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        live_model: str | None = None,
        timeout_seconds: float = 60.0,
        consent_file: Path = Path(".live-llm-consent"),
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("provider timeout must be positive")
        self.fixture_turns = dict(fixture_turns or {})
        self.base_url = base_url
        self.api_key = api_key
        self.live_model = live_model
        self.timeout_seconds = timeout_seconds
        self.consent_file = consent_file
        self._providers: list[LLMProvider] = []
        self._fixture_providers: dict[AgentRole, FixtureAgentProvider] = {}

    def preflight(
        self,
        provider: str,
        *,
        pricing: ModelPricing | None,
        require_consent: bool = True,
    ) -> None:
        if provider == "fixture":
            return
        if provider != "live":
            raise ValueError(f"unknown agent provider: {provider}")
        if require_consent and not self.consent_file.is_file():
            raise ValueError("live LLM consent is required")
        if not self.api_key:
            raise ValueError("live LLM API key is required")
        if not self.base_url:
            raise ValueError("live LLM base URL is required")
        if not self.live_model:
            raise ValueError("live LLM model is required")
        if pricing is None:
            raise ValueError(f"live model price is not configured: {self.live_model}")

    def resolve_runtime_config(
        self,
        config: LLMRuntimeConfig,
        provider: str,
        *,
        require_consent: bool = True,
    ) -> LLMRuntimeConfig:
        if provider == "fixture":
            for role in AgentRole:
                route = config.role_route_for(role.value)
                if route.provider != "fixture":
                    raise ValueError(f"fixture route is not configured for {role.value}")
                self.preflight(provider, pricing=config.model_pricing(route.model))
            return config
        pricing = config.model_pricing(self.live_model or "")
        self.preflight(provider, pricing=pricing, require_consent=require_consent)
        assert self.live_model is not None
        role_routes = {
            role.value: LLMRoute(provider="live", model=self.live_model) for role in AgentRole
        }
        return config.model_copy(update={"role_routes": role_routes})

    def build(
        self,
        role: AgentRole,
        runtime: RoleRuntime,
        provider: str,
    ) -> LLMProvider:
        if runtime.provider != provider:
            raise ValueError(f"runtime provider mismatch for {role.value}")
        if provider == "fixture":
            existing = self._fixture_providers.get(role)
            if existing is not None:
                return existing
            try:
                turns = self.fixture_turns[role]
            except KeyError as exc:
                raise ValueError(f"fixture turns are not configured for {role.value}") from exc
            fixture_provider = FixtureAgentProvider(runtime.model, turns)
            self._fixture_providers[role] = fixture_provider
            self._providers.append(fixture_provider)
            return fixture_provider
        self.preflight(provider, pricing=runtime.pricing)
        if runtime.model != self.live_model:
            raise ValueError(f"live runtime model mismatch for {role.value}")
        assert self.api_key is not None
        live_provider = OpenAIProvider(
            api_key=self.api_key,
            base_url=self.base_url,
            model=runtime.model,
            timeout=self.timeout_seconds,
        )
        self._providers.append(live_provider)
        return live_provider

    async def close(self) -> None:
        providers, self._providers = self._providers, []
        self._fixture_providers.clear()
        for provider in providers:
            await cast(Any, provider).close()
