from decimal import Decimal

from sector_pulse.config.llm_config import LLMRoute, LLMRuntimeConfig


def test_runtime_config_can_resolve_stage_model() -> None:
    config = LLMRuntimeConfig(
        version="test",
        budget_cny_per_run=Decimal("2"),
        max_attribution_concurrency=4,
        max_revision_rounds=2,
        routes={"writing": LLMRoute(provider="live", model="gpt-4o-mini")},
    )
    assert config.route_for("writing").model == "gpt-4o-mini"


def test_runtime_config_can_override_model_for_live_provider() -> None:
    config = LLMRuntimeConfig(
        version="test",
        budget_cny_per_run=Decimal("2"),
        max_attribution_concurrency=4,
        max_revision_rounds=2,
        routes={"writing": LLMRoute(provider="fixture", model="fixture-high")},
    )
    assert config.route_for("writing", provider_override="live").provider == "live"
