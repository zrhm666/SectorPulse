from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sector_pulse.domain.news.news_retrieval import (
    MappingConfidence,
    NewsQuery,
    QueryType,
    SectorEntityConfig,
)


def test_news_query_rejects_naive_or_reversed_window() -> None:
    with pytest.raises(ValidationError):
        NewsQuery(
            query_id="q-1",
            query_type=QueryType.KEYWORD,
            source_id="eastmoney",
            value="人工智能",
            priority=1,
            start_at=datetime(2026, 8, 14, 0, 0),
            cutoff_at=datetime(2026, 8, 14, 1, 0, tzinfo=UTC),
        )
    with pytest.raises(ValidationError):
        NewsQuery(
            query_id="q-2",
            query_type=QueryType.KEYWORD,
            source_id="eastmoney",
            value="人工智能",
            priority=1,
            start_at=datetime(2026, 8, 14, 2, 0, tzinfo=UTC),
            cutoff_at=datetime(2026, 8, 14, 1, 0, tzinfo=UTC),
        )


def test_entity_config_is_immutable_and_mapping_confidence_is_explicit() -> None:
    config = SectorEntityConfig(
        version="2026-08-14.1",
        aliases={"sector-1": ("板块别名",)},
        industry_terms={"sector-1": ("产业链词",)},
        ambiguous_terms=("AI",),
    )
    assert config.aliases["sector-1"] == ("板块别名",)
    assert MappingConfidence.HIGH.value == "HIGH"
    with pytest.raises(ValidationError):
        config.aliases = {}

