from datetime import UTC, datetime, timedelta

from sector_pulse.application.news.news_quality import evaluate_news_quality
from sector_pulse.domain.news import NewsDocument, SourceGrade
from sector_pulse.domain.provider import DataStatus

NOW = datetime(2026, 8, 14, 2, tzinfo=UTC)


def document(published_at: datetime | None) -> NewsDocument:
    return NewsDocument(
        document_id="doc-1",
        source_id="eastmoney",
        canonical_locator="urn:fixture:doc-1",
        citation_url="https://example.test/doc-1",
        title="测试新闻",
        publisher="证券时报",
        summary="摘要",
        published_at=published_at,
        source_observed_at=published_at,
        collected_at=NOW,
        content_hash="hash-1",
        source_grade=SourceGrade.REPUTABLE_MEDIA,
    )


def test_cutoff_violation_blocks_quality() -> None:
    report = evaluate_news_quality(
        documents=(document(NOW + timedelta(minutes=1)),),
        events=(),
        source_statuses={"cls": DataStatus.SUCCESS},
        cutoff=NOW,
    )
    assert report.status.value == "BLOCKED"
    assert report.excluded_after_cutoff_count == 1
    assert report.blocking_reasons


def test_non_core_source_failure_degrades_but_does_not_block() -> None:
    report = evaluate_news_quality(
        documents=(document(NOW),),
        events=(),
        source_statuses={"cls": DataStatus.SUCCESS, "eastmoney": DataStatus.FAILED},
        cutoff=NOW,
    )
    assert report.status.value == "DEGRADED"
    assert report.citation_eligible_count == 1
