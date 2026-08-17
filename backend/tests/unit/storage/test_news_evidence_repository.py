from sector_pulse.storage.news_evidence_repository import SQLiteNewsEvidenceRepository
from sector_pulse.storage.sqlite import SQLiteDatabase


def test_get_events_empty(tmp_path) -> None:
    repo = SQLiteNewsEvidenceRepository(SQLiteDatabase(tmp_path / "t.db"))
    assert repo.get_events(()) == ()


def test_get_events_returns_events_with_documents(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "t.db")
    database.initialize()
    with database.transaction() as connection:
        connection.execute(
            """INSERT INTO news_events (
                event_id, canonical_title, first_published_at, deduplication_reason, metadata_json
            ) VALUES (?, ?, ?, ?, ?)""",
            ("event-1", "人工智能政策", "2026-08-14T02:00:00Z", "content_hash", "{}"),
        )
        connection.execute(
            """INSERT INTO news_documents (
                document_id, source_id, canonical_url, title, published_at,
                observed_at, content_hash, source_grade, metadata_json,
                citation_url, publisher
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "doc-1", "eastmoney", "https://example.com/a", "标题A", "2026-08-14T01:00:00Z",
                "2026-08-14T01:05:00Z", "hash-1", "A1", "{}",
                "https://example.com/a", "东方财富",
            ),
        )
        connection.execute(
            "INSERT INTO news_event_documents (event_id, document_id) VALUES (?, ?)",
            ("event-1", "doc-1"),
        )
    repo = SQLiteNewsEvidenceRepository(database)
    events = repo.get_events(("event-1",))
    assert len(events) == 1
    event = events[0]
    assert event.event_id == "event-1"
    assert event.canonical_title == "人工智能政策"
    assert event.first_published_at == "2026-08-14T02:00:00Z"
    assert len(event.documents) == 1
    document = event.documents[0]
    assert document["title"] == "标题A"
    assert document["citation_url"] == "https://example.com/a"
    assert document["publisher"] == "东方财富"
    assert document["published_at"] == "2026-08-14T01:00:00Z"
    assert document["source_grade"] == "A1"
