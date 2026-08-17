from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


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
    pricing: dict[str, dict[str, str]] = Field(default_factory=dict)

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


def load_llm_config(path: Path) -> LLMRuntimeConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("LLM config must be a mapping")
    return LLMRuntimeConfig.model_validate(raw)