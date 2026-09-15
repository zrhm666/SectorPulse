from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("aidynamic_agent")


@pytest.mark.asyncio
async def test_fixture_provider_is_framework_native_and_uses_role_script():
    from aidynamic_agent.core.message import FinishReason, Message, Role, TextBlock
    from aidynamic_agent.llm.base import LLMProvider
    from sector_pulse.infrastructure.agents.provider_factory import (
        AgentProviderFactory,
        FixtureAgentTurn,
    )
    from sector_pulse.infrastructure.agents.roles import AgentRole, RoleRuntime

    runtime = RoleRuntime(
        provider="fixture",
        model="fixture-low",
        prompt="fixed",
        pricing=None,
    )
    factory = AgentProviderFactory(
        fixture_turns={
            AgentRole.A1: (
                FixtureAgentTurn(text="candidate batch ready", total_tokens=7),
            )
        }
    )

    provider = factory.build(AgentRole.A1, runtime, "fixture")
    assert isinstance(provider, LLMProvider)
    response = await provider.create([Message.from_text(Role.USER, "collect data")])
    assert response.content == [TextBlock(text="candidate batch ready")]
    assert response.stop_reason is FinishReason.END_TURN
    assert response.model == "fixture-low"
    assert response.usage == {
        "prompt_tokens": 0,
        "completion_tokens": 7,
        "total_tokens": 7,
    }


@pytest.mark.asyncio
async def test_live_factory_builds_vendor_openai_provider_and_closes_it(tmp_path):
    from aidynamic_agent.llm.providers.openai import OpenAIProvider
    from sector_pulse.config.llm_config import LLMRuntimeConfig
    from sector_pulse.infrastructure.agents.provider_factory import AgentProviderFactory
    from sector_pulse.infrastructure.agents.roles import AgentRole, RoleRuntime

    consent = tmp_path / ".live-llm-consent"
    consent.write_text("accepted", encoding="utf-8")
    config = LLMRuntimeConfig.model_validate(
        {
            "version": "test",
            "budget_cny_per_run": "1",
            "max_attribution_concurrency": 1,
            "max_revision_rounds": 1,
            "routes": {},
            "role_routes": {
                role: {"provider": "live", "model": "deepseek-flash"}
                for role in ("A0", "A1", "A2", "A3", "A4")
            },
            "pricing": {
                "deepseek-flash": {
                    "input_cny_per_million": "1",
                    "output_cny_per_million": "2",
                }
            },
        }
    )
    runtime = RoleRuntime(
        provider="live",
        model="deepseek-flash",
        prompt="fixed",
        pricing=config.model_pricing("deepseek-flash"),
    )
    factory = AgentProviderFactory(
        base_url="https://example.invalid/v1",
        api_key="secret",
        live_model="deepseek-flash",
        timeout_seconds=9,
        consent_file=consent,
    )

    provider = factory.build(AgentRole.A0, runtime, "live")
    assert isinstance(provider, OpenAIProvider)
    assert provider.model == "deepseek-flash"
    assert provider.base_url == "https://example.invalid/v1"
    assert provider.timeout == 9
    await factory.close()


@pytest.mark.parametrize(
    ("factory_kwargs", "price", "message"),
    [
        ({"api_key": "key", "base_url": "https://host/v1", "live_model": "m"}, None,
         "consent"),
        ({"consent": True, "base_url": "https://host/v1", "live_model": "m"}, None,
         "API key"),
        ({"consent": True, "api_key": "key", "live_model": "m"}, None, "base URL"),
        ({"consent": True, "api_key": "key", "base_url": "https://host/v1"}, None,
         "model"),
        ({"consent": True, "api_key": "key", "base_url": "https://host/v1",
          "live_model": "m"}, None, "price"),
    ],
)
def test_live_preflight_rejects_missing_consent_config_or_price(
    tmp_path, factory_kwargs, price, message
):
    from sector_pulse.infrastructure.agents.provider_factory import AgentProviderFactory

    consent_file = tmp_path / "consent"
    if factory_kwargs.pop("consent", False):
        consent_file.write_text("accepted", encoding="utf-8")
    factory = AgentProviderFactory(consent_file=consent_file, **factory_kwargs)

    with pytest.raises(ValueError, match=message):
        factory.preflight("live", pricing=price)


def test_live_runtime_routes_are_rewritten_before_agent_creation():
    from sector_pulse.config.llm_config import load_llm_config
    from sector_pulse.infrastructure.agents.provider_factory import AgentProviderFactory

    config = load_llm_config(Path("config/llm.yaml"))
    factory = AgentProviderFactory(
        base_url="https://host/v1",
        api_key="key",
        live_model="deepseek-flash",
        consent_file=Path("unused"),
    )
    config = config.model_copy(
        update={
            "pricing": {
                **config.pricing,
                "deepseek-flash": {
                    "input_cny_per_million": "1.5",
                    "output_cny_per_million": "3.0",
                },
            }
        }
    )

    resolved = factory.resolve_runtime_config(config, "live", require_consent=False)
    assert {
        resolved.role_route_for(role).provider for role in ("A0", "A1", "A2", "A3", "A4")
    } == {"live"}
    assert {
        resolved.role_route_for(role).model for role in ("A0", "A1", "A2", "A3", "A4")
    } == {"deepseek-flash"}
    assert resolved.model_pricing("deepseek-flash").input_cny_per_million == Decimal("1.5")
