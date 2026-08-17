from datetime import UTC, datetime, timedelta

from sector_pulse.application.news_ingestion import deduplicate_documents
from sector_pulse.domain.news import NewsDocument, SourceGrade


def document(document_id: str, title: str, content_hash: str, minutes: int) -> NewsDocument:
    published = datetime(2026, 8, 14, 8, 0, tzinfo=UTC) + timedelta(minutes=minutes)
    return NewsDocument(
        document_id=document_id,
        source_id="source",
        canonical_locator=f"https://example.com/{document_id}",
        citation_url=f"https://example.com/{document_id}",
        title=title,
        published_at=published,
        collected_at=published,
        content_hash=content_hash,
        source_grade=SourceGrade.REPUTABLE_MEDIA,
    )


def test_same_content_hash_is_one_event() -> None:
    events = deduplicate_documents(
        (
            document("a", "同一事件：政策发布", "x" * 64, 0),
            document("b", "同一事件：政策发布（转载）", "x" * 64, 2),
        )
    )
    assert len(events) == 1
    assert events[0].document_ids == ("a", "b")


def test_similar_titles_are_merged_but_distinct_titles_are_kept() -> None:
    events = deduplicate_documents(
        (
            document("a", "某公司获批建设示范项目", "a" * 64, 0),
            document("b", "某公司获批建设示范项目 最新进展", "b" * 64, 1),
            document("c", "另一行业发布独立监管政策", "c" * 64, 2),
        )
    )
    assert len(events) == 2
    assert {event.document_ids for event in events} == {("a", "b"), ("c",)}
