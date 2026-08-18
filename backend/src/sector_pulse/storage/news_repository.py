from collections.abc import Sequence

from sector_pulse.domain.news import NewsDocument, NewsEvent
from sector_pulse.storage.sqlite import SQLiteDatabase


class SQLiteNewsRepository:
    """保存新闻元数据和事件关系；不保存完整正文。"""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def save(self, documents: Sequence[NewsDocument], events: Sequence[NewsEvent]) -> None:
        with self._database.transaction() as connection:
            canonical_ids: dict[str, str] = {}
            canonical_to_id: dict[str, str] = {}
            for document in documents:
                if document.canonical_locator in canonical_to_id:
                    canonical_ids[document.document_id] = canonical_to_id[
                        document.canonical_locator
                    ]
                    continue
                existing = connection.execute(
                    "SELECT document_id FROM news_documents WHERE canonical_url = ?",
                    (document.canonical_locator,),
                ).fetchone()
                canonical_to_id[document.canonical_locator] = (
                    existing[0] if existing else document.document_id
                )
                canonical_ids[document.document_id] = canonical_to_id[document.canonical_locator]
            for document in documents:
                connection.execute(
                    """
                    INSERT INTO news_documents (
                        document_id, source_id, canonical_url, title, published_at,
                        observed_at, content_hash, source_grade, metadata_json,
                        citation_url, publisher, summary, source_observed_at,
                        use_grade, quality_flags_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(document_id) DO UPDATE SET
                        title = excluded.title, observed_at = excluded.observed_at,
                        citation_url = excluded.citation_url, publisher = excluded.publisher,
                        summary = excluded.summary,
                        source_observed_at = excluded.source_observed_at,
                        quality_flags_json = excluded.quality_flags_json,
                        metadata_json = excluded.metadata_json
                    ON CONFLICT(canonical_url) DO NOTHING
                    """,
                    (
                        document.document_id, document.source_id, document.canonical_locator,
                        document.title,
                        document.published_at.isoformat() if document.published_at else None,
                        document.collected_at.isoformat(), document.content_hash,
                        document.source_grade.value, document.model_dump_json(),
                        document.citation_url, document.publisher, document.summary,
                        document.source_observed_at.isoformat()
                        if document.source_observed_at else None,
                        "EVIDENCE" if document.published_at is not None else "BACKGROUND", "[]",
                    ),
                )
            for event in events:
                normalized_event = event.model_copy(
                    update={
                        "document_ids": tuple(
                            canonical_ids.get(document_id, document_id)
                            for document_id in event.document_ids
                        )
                    }
                )
                connection.execute(
                    """
                    INSERT INTO news_events (
                        event_id, canonical_title, first_published_at,
                        deduplication_reason, metadata_json
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(event_id) DO UPDATE SET
                        canonical_title = excluded.canonical_title,
                        metadata_json = excluded.metadata_json
                    """,
                    (
                        normalized_event.event_id, normalized_event.canonical_title,
                        normalized_event.first_published_at.isoformat()
                        if normalized_event.first_published_at else None,
                        normalized_event.deduplication_reason, normalized_event.model_dump_json(),
                    ),
                )
                connection.execute(
                    "DELETE FROM news_event_documents WHERE event_id = ?",
                    (normalized_event.event_id,),
                )
                connection.executemany(
                    "INSERT INTO news_event_documents (event_id, document_id) VALUES (?, ?)",
                    [
                        (normalized_event.event_id, document_id)
                        for document_id in normalized_event.document_ids
                    ],
                )

    def get_event(self, event_id: str) -> NewsEvent | None:
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT metadata_json FROM news_events WHERE event_id = ?", (event_id,)
            ).fetchone()
        return NewsEvent.model_validate_json(row[0]) if row else None

    def get_events(self, event_ids: Sequence[str]) -> tuple[NewsEvent, ...]:
        if not event_ids:
            return ()
        placeholders = ",".join("?" for _ in event_ids)
        with self._database.connection() as connection:
            rows = connection.execute(
                f"SELECT metadata_json FROM news_events WHERE event_id IN ({placeholders})",
                tuple(event_ids),
            ).fetchall()
        return tuple(NewsEvent.model_validate_json(row[0]) for row in rows)

    def get_documents(self, document_ids: Sequence[str]) -> dict[str, NewsDocument]:
        if not document_ids:
            return {}
        placeholders = ",".join("?" for _ in document_ids)
        with self._database.connection() as connection:
            rows = connection.execute(
                f"SELECT metadata_json FROM news_documents WHERE document_id IN ({placeholders})",
                tuple(document_ids),
            ).fetchall()
        documents = (NewsDocument.model_validate_json(row[0]) for row in rows)
        return {document.document_id: document for document in documents}
