from pathlib import Path

import pytest
from sector_pulse.config.news_config import load_entity_config, load_news_config


def test_load_news_config_rejects_unregistered_provider(tmp_path: Path) -> None:
    path = tmp_path / "news.yaml"
    path.write_text(
        "sources:\n  - source_id: bad\n    provider_type: arbitrary.import.Path\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unregistered provider_type"):
        load_news_config(path, frozenset({"akshare_cls"}))


def test_load_news_and_entity_config_from_yaml(tmp_path: Path) -> None:
    news_path = tmp_path / "news.yaml"
    news_path.write_text(
        """
sources:
  - source_id: cls
    provider_type: akshare_cls
    authorization_status: RESEARCH_ONLY
    default_source_grade: DISCOVERY_ONLY
    timeout_seconds: 10
    max_retries: 2
    rate_limit_per_second: 2
    max_results_per_query: 20
""",
        encoding="utf-8",
    )
    entity_path = tmp_path / "entities.yaml"
    entity_path.write_text(
        "version: '2026-08-14.1'\naliases: {}\nindustry_terms: {}\nambiguous_terms: []\n",
        encoding="utf-8",
    )
    sources = load_news_config(news_path, frozenset({"akshare_cls"}))
    entity_config = load_entity_config(entity_path)
    assert sources[0].source_id == "cls"
    assert entity_config.version == "2026-08-14.1"
