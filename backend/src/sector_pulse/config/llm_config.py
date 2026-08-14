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


def load_llm_config(path: Path) -> LLMRuntimeConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("LLM config must be a mapping")
    return LLMRuntimeConfig.model_validate(raw)
