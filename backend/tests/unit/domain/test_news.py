from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sector_pulse.domain.news import NewsDocument, NewsUse, SourceGrade


def make_document(
    published_at: datetime | None,
    collected_at: datetime,
    source_observed_at: datetime | None = None,
) -> NewsDocument:
    return NewsDocument(
        document_id="doc-1",
        source_id="official-example",
        canonical_locator="https://example.com/news/1",
        citation_url="https://example.com/news/1",
        title="示例产业政策发布",
        published_at=published_at,
        source_observed_at=source_observed_at,
        collected_at=collected_at,
        content_hash="a" * 64,
        source_grade=SourceGrade.PRIMARY,
    )


def test_naive_published_at_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_document(
            datetime(2026, 8, 14, 9, 0),
            datetime(2026, 8, 14, 9, 1, tzinfo=UTC),
        )


def test_missing_published_at_is_background_only() -> None:
    cutoff = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)
    document = make_document(None, cutoff)
    assert document.use_at(cutoff) is NewsUse.BACKGROUND


def test_document_after_cutoff_is_excluded() -> None:
    cutoff = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)
    document = make_document(cutoff + timedelta(seconds=1), cutoff)
    assert document.use_at(cutoff) is NewsUse.EXCLUDED


def test_document_before_cutoff_is_evidence_eligible() -> None:
    cutoff = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)
    document = make_document(cutoff - timedelta(minutes=10), cutoff)
    assert document.use_at(cutoff) is NewsUse.EVIDENCE


def test_collected_after_cutoff_does_not_exclude_published_news() -> None:
    cutoff = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)
    document = make_document(cutoff - timedelta(minutes=10), cutoff + timedelta(minutes=5))
    assert document.use_at(cutoff) is NewsUse.EVIDENCE


def test_source_observed_after_cutoff_is_excluded() -> None:
    cutoff = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)
    document = make_document(
        cutoff - timedelta(minutes=10), cutoff, source_observed_at=cutoff + timedelta(seconds=1)
    )
    assert document.use_at(cutoff) is NewsUse.EXCLUDED
