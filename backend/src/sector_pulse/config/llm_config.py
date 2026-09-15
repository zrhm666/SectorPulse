from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from sector_pulse.domain.orchestration.models import BudgetLimits, ModelPricing
from sector_pulse.domain.writing.agent_execution import AgentLimits


class LLMRoute(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider: str
    model: str


class LLMRuntimeConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    version: str
    budget_cny_per_run: Decimal = Field(gt=0)
    max_attribution_concurrency: int = Field(ge=1, le=32)
    max_revision_rounds: int = Field(ge=0, le=2)
    routes: dict[str, LLMRoute]
    role_routes: dict[str, LLMRoute] | None = None
    pricing: dict[str, dict[str, str]] = Field(default_factory=dict)
    agent_limits: AgentLimits = Field(default_factory=AgentLimits)
    max_agent_calls: int = Field(default=80, ge=1, le=200)
    max_agent_tokens: int = Field(default=500000, ge=1000, le=2000000)
    max_orchestration_tool_calls: int = Field(default=120, ge=1, le=10000)
    orchestration_timeout_seconds: int = Field(default=1200, ge=1, le=86400)

    def route_for(self, stage: str, provider_override: str | None = None) -> LLMRoute:
        # 统一从配置解析阶段路由；旧配置缺失 routes 时保留 Fixture 兼容默认值。
        route = self.routes.get(stage)
        if route is None:
            defaults = {
                "attribution": "fixture",
                "editorial": "fixture-high",
                "writing": "fixture-high",
                "review": "fixture-review",
                "revision": "fixture-high",
            }
            route = LLMRoute(provider="fixture", model=defaults.get(stage, "fixture"))
        if provider_override is None:
            return route
        return route.model_copy(update={"provider": provider_override})

    def role_route_for(self, role: str) -> LLMRoute:
        if role not in {"A0", "A1", "A2", "A3", "A4"}:
            raise KeyError(f"unknown agent role: {role}")
        if self.role_routes is not None:
            try:
                return self.role_routes[role]
            except KeyError as exc:
                raise KeyError(f"role route is not configured: {role}") from exc
        legacy_stages = {
            "A0": ("editorial",),
            "A1": ("attribution",),
            "A2": ("attribution",),
            "A3": ("editorial", "writing", "revision"),
            "A4": ("review",),
        }[role]
        missing = [stage for stage in legacy_stages if stage not in self.routes]
        if missing:
            raise KeyError(f"legacy routes missing for {role}: {', '.join(missing)}")
        routes = tuple(self.routes[stage] for stage in legacy_stages)
        if any(route != routes[0] for route in routes[1:]):
            raise ValueError(f"{role} legacy route conflict: {', '.join(legacy_stages)}")
        return routes[0]

    def model_pricing(self, model: str) -> ModelPricing | None:
        raw = self.pricing.get(model)
        if raw is None:
            return None
        return ModelPricing.model_validate(raw)

    def orchestration_budget_limits(self) -> BudgetLimits:
        return BudgetLimits(
            max_tokens=self.max_agent_tokens,
            max_calls=self.max_agent_calls,
            max_tool_calls=self.max_orchestration_tool_calls,
            max_cny=self.budget_cny_per_run,
        )


def load_llm_config(path: Path) -> LLMRuntimeConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("LLM config must be a mapping")
    return LLMRuntimeConfig.model_validate(raw)
