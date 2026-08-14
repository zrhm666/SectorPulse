from pathlib import Path
from typing import Any

import yaml

from sector_pulse.domain.news_retrieval import NewsSourceDefinition, SectorEntityConfig


def load_news_config(
    path: Path, registered_provider_types: frozenset[str]
) -> tuple[NewsSourceDefinition, ...]:
    """只加载安全 YAML，并拒绝未注册的 Provider 类型。"""
    payload: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("sources"), list):
        raise ValueError("news source config must contain a sources list")
    raw_sources = payload["sources"]
    if any(
        not isinstance(item, dict) or not isinstance(item.get("provider_type"), str)
        for item in raw_sources
    ):
        raise ValueError("each news source must declare provider_type")
    unknown = {item["provider_type"] for item in raw_sources} - registered_provider_types
    if unknown:
        raise ValueError(f"unregistered provider_type: {sorted(unknown)}")
    sources = tuple(NewsSourceDefinition.model_validate(item) for item in raw_sources)
    return sources


def load_entity_config(path: Path) -> SectorEntityConfig:
    payload: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("sector entity config must be a mapping")
    return SectorEntityConfig.model_validate(payload)
