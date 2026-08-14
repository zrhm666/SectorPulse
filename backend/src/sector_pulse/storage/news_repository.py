from collections.abc import Sequence

from sector_pulse.domain.news import NewsDocument, NewsEvent
from sector_pulse.storage.sqlite import SQLiteDatabase


class SQLiteNewsRepository:
    """保存新闻元数据和事件关系；不保存完整正文。"""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def save(self, documents: Sequence[NewsDocument], events: Sequence[NewsEvent]) -> None:
        with self._database.transaction() as connection:
            for document in documents:
                connection.execute(
                    """
                    INSERT INTO news_documents (
                        document_id, source_id, canonical_url, title, published_at,
                        observed_at, content_hash, source_grade, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(document_id) DO UPDATE SET
                        title = excluded.title,
                        observed_at = excluded.observed_at,
                        metadata_json = excluded.metadata_json
                    """,
                    (
                        document.document_id,
                        document.source_id,
                        document.url,
                        document.title,
                        document.published_at.isoformat() if document.published_at else None,
                        document.observed_at.isoformat(),
                        document.content_hash,
                        document.source_grade.value,
                        document.model_dump_json(),
                    ),
                )
            for event in events:
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
                        event.event_id,
                        event.canonical_title,
                        event.first_published_at.isoformat() if event.first_published_at else None,
                        event.deduplication_reason,
                        event.model_dump_json(),
                    ),
                )
                connection.execute(
                    "DELETE FROM news_event_documents WHERE event_id = ?",
                    (event.event_id,),
                )
                connection.executemany(
                    """
                    INSERT INTO news_event_documents (event_id, document_id)
                    VALUES (?, ?)
                    """,
                    [(event.event_id, document_id) for document_id in event.document_ids],
                )

    def get_event(self, event_id: str) -> NewsEvent | None:
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT metadata_json FROM news_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        if row is None:
            return None
        return NewsEvent.model_validate_json(row[0])
