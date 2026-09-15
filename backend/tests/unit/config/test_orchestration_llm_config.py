from decimal import Decimal
from pathlib import Path

import pytest


def config_payload():
    return {
        "version": "test",
        "budget_cny_per_run": "2.00",
        "max_attribution_concurrency": 2,
        "max_revision_rounds": 2,
        "max_agent_calls": 80,
        "max_agent_tokens": 120000,
        "max_orchestration_tool_calls": 120,
        "orchestration_timeout_seconds": 1200,
        "routes": {
            "attribution": {"provider": "fixture", "model": "fixture-low"},
            "editorial": {"provider": "fixture", "model": "fixture-high"},
            "writing": {"provider": "fixture", "model": "fixture-high"},
            "review": {"provider": "fixture", "model": "fixture-review"},
            "revision": {"provider": "fixture", "model": "fixture-high"},
        },
        "pricing": {
            "fixture-low": {
                "input_cny_per_million": "0",
                "output_cny_per_million": "0",
            },
            "fixture-high": {
                "input_cny_per_million": "0",
                "output_cny_per_million": "0",
            },
            "fixture-review": {
                "input_cny_per_million": "0",
                "output_cny_per_million": "0",
            },
        },
    }


def test_legacy_stage_routes_map_explicitly_to_agent_roles_and_budget_limits():
    from sector_pulse.config.llm_config import LLMRuntimeConfig

    config = LLMRuntimeConfig.model_validate(config_payload())
    assert config.role_route_for("A0").model == "fixture-high"
    assert config.role_route_for("A1").model == "fixture-low"
    assert config.role_route_for("A2").model == "fixture-low"
    assert config.role_route_for("A3").model == "fixture-high"
    assert config.role_route_for("A4").model == "fixture-review"
    assert config.model_pricing("fixture-low").input_cny_per_million == Decimal("0")
    limits = config.orchestration_budget_limits()
    assert limits.max_tokens == 120000
    assert limits.max_calls == 80
    assert limits.max_tool_calls == 120
    assert limits.max_cny == Decimal("2.00")


def test_merged_writer_route_conflict_is_explicit_and_missing_price_is_not_free():
    from sector_pulse.config.llm_config import LLMRuntimeConfig

    payload = config_payload()
    payload["routes"]["revision"] = {"provider": "fixture", "model": "other-model"}
    config = LLMRuntimeConfig.model_validate(payload)
    with pytest.raises(ValueError, match="A3.*conflict"):
        config.role_route_for("A3")
    assert config.model_pricing("unpriced-model") is None


def test_explicit_role_routes_are_complete_and_do_not_fall_back_to_fixture():
    from sector_pulse.config.llm_config import LLMRuntimeConfig

    payload = config_payload()
    payload["role_routes"] = {
        "A0": {"provider": "fixture", "model": "fixture-high"},
        "A1": {"provider": "fixture", "model": "fixture-low"},
    }
    config = LLMRuntimeConfig.model_validate(payload)
    with pytest.raises(KeyError, match="A2"):
        config.role_route_for("A2")


def test_packaged_config_builds_priced_runtimes_for_every_role():
    from sector_pulse.config.llm_config import load_llm_config
    from sector_pulse.infrastructure.agents.roles import AgentRole, role_runtimes_from_config
    from sector_pulse.infrastructure.llm.prompt_registry import PromptRegistry

    config = load_llm_config(Path("config/llm.yaml"))
    runtimes = role_runtimes_from_config(config, PromptRegistry(Path("config/prompts")))
    assert set(runtimes) == set(AgentRole)
    assert all(runtime.pricing is not None for runtime in runtimes.values())
    assert all(
        runtime.pricing.estimate(1000, 1000) == Decimal("0")
        for runtime in runtimes.values()
    )
    limits = config.orchestration_budget_limits()
    assert limits.max_tool_calls == 120
    assert config.orchestration_timeout_seconds == 1200


def test_packaged_config_has_conservative_peak_price_for_configured_deepseek_flash():
    from sector_pulse.config.llm_config import load_llm_config

    config = load_llm_config(Path("config/llm.yaml"))
    price = config.model_pricing("deepseek-flash")
    assert price is not None
    assert price.input_cny_per_million == Decimal("3.0")
    assert price.output_cny_per_million == Decimal("9.0")
