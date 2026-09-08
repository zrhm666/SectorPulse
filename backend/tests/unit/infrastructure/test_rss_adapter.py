from datetime import UTC, datetime, timedelta

import pytest
from sector_pulse.domain.news.news import NewsUse
from sector_pulse.domain.provider import DataStatus
from sector_pulse.infrastructure.news.rss_adapter import RssNewsAdapter
from sector_pulse.infrastructure.news.rss_client import (
    UnsafeNewsUrlError,
    validate_public_url,
    validate_response_size,
)


def test_adapter_filters_items_after_cutoff_and_keeps_background_items() -> None:
    cutoff = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)
    rows = [
        {
            "id": "old",
            "title": "旧新闻",
            "link": "https://example.com/old",
            "published": "2026-08-14T08:30:00+00:00",
        },
        {
            "id": "future",
            "title": "盘后新闻",
            "link": "https://example.com/future",
            "published": "2026-08-14T09:01:00+00:00",
        },
        {
            "id": "unknown-time",
            "title": "发布时间缺失",
            "link": "https://example.com/unknown",
            "published": None,
        },
    ]

    result = RssNewsAdapter().map_items(rows, cutoff, observed_at=cutoff)

    assert result.status is DataStatus.SUCCESS
    assert result.data is not None
    assert {item.document_id for item in result.data} == {"old", "unknown-time"}
    assert result.data[0].use_at(cutoff) is NewsUse.EVIDENCE
    assert result.data[1].use_at(cutoff) is NewsUse.BACKGROUND


def test_adapter_returns_empty_when_all_items_are_after_cutoff() -> None:
    cutoff = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)
    rows = [
        {
            "id": "future",
            "title": "盘后新闻",
            "link": "https://example.com/future",
            "published": (cutoff + timedelta(minutes=1)).isoformat(),
        }
    ]

    result = RssNewsAdapter().map_items(rows, cutoff, observed_at=cutoff)

    assert result.status is DataStatus.EMPTY
    assert result.data is None


def test_private_and_non_http_urls_are_rejected() -> None:
    with pytest.raises(UnsafeNewsUrlError):
        validate_public_url("http://127.0.0.1/news")
    with pytest.raises(UnsafeNewsUrlError):
        validate_public_url("file:///C:/secret.txt")


def test_response_size_limit_is_enforced() -> None:
    with pytest.raises(ValueError):
        validate_response_size(b"12345", max_bytes=4)
