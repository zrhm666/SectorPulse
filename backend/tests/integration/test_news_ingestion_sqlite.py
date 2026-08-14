from datetime import UTC, datetime
from pathlib import Path

from sector_pulse.domain.news import NewsDocument, NewsEvent, SourceGrade
from sector_pulse.storage.news_repository import SQLiteNewsRepository
from sector_pulse.storage.sqlite import SQLiteDatabase


def test_news_repository_persists_event_documents(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "news.db")
    database.initialize()
    repository = SQLiteNewsRepository(database)
    document = NewsDocument(
        document_id="doc-1",
        source_id="source",
        url="https://example.com/1",
        title="新闻标题",
        published_at=datetime(2026, 8, 14, 8, 0, tzinfo=UTC),
        observed_at=datetime(2026, 8, 14, 8, 1, tzinfo=UTC),
        content_hash="a" * 64,
        source_grade=SourceGrade.PRIMARY,
    )
    event = NewsEvent(
        event_id="event-1",
        canonical_title="新闻标题",
        first_published_at=document.published_at,
        document_ids=(document.document_id,),
        deduplication_reason="content_hash",
    )

    repository.save((document,), (event,))

    restored = repository.get_event("event-1")
    assert restored == event
