import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sector_pulse.domain.news import SourceGrade
from sector_pulse.domain.provider import DataStatus
from sector_pulse.infrastructure.news.akshare_adapters import (
    AkShareClsAdapter,
    AkShareCninfoAdapter,
    AkShareEastmoneyNewsAdapter,
)

FIXTURES = Path("backend/tests/fixtures/news")
CUTOFF = datetime(2026, 8, 14, 3, 0, tzinfo=UTC)
COLLECTED = datetime(2026, 8, 14, 4, 0, tzinfo=UTC)


def load_rows(name: str) -> list[dict[str, Any]]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_cls_document_is_discovery_only_and_has_no_article_url() -> None:
    result = AkShareClsAdapter().map_rows(load_rows("cls_rows.json"), CUTOFF, COLLECTED)
    assert result.status is DataStatus.SUCCESS
    assert result.data is not None
    document = result.data[0]
    assert document.canonical_locator.startswith("urn:sector-pulse:akshare-cls:")
    assert document.citation_url is None
    assert document.source_grade is SourceGrade.DISCOVERY_ONLY
    assert len(result.data) == 1


def test_eastmoney_maps_publisher_summary_time_and_url() -> None:
    result = AkShareEastmoneyNewsAdapter().map_rows(
        load_rows("eastmoney_rows.json"), CUTOFF, COLLECTED
    )
    assert result.status is DataStatus.SUCCESS
    assert result.data is not None
    document = result.data[0]
    assert document.publisher == "证券时报"
    assert document.citation_url == "https://finance.eastmoney.com/a/example.html"
    assert document.published_at == datetime(2026, 8, 14, 2, 10, tzinfo=UTC)


def test_cninfo_is_primary_and_filters_after_cutoff() -> None:
    result = AkShareCninfoAdapter().map_rows(load_rows("cninfo_rows.json"), CUTOFF, COLLECTED)
    assert result.status is DataStatus.SUCCESS
    assert result.data is not None
    assert len(result.data) == 1
    assert result.data[0].source_grade is SourceGrade.PRIMARY
    assert result.data[0].citation_url is not None
