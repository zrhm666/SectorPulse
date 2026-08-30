# ruff: noqa: E501
from collections.abc import Sequence

from sqlalchemy import text

from sector_pulse.domain.news import NewsDocument, NewsEvent
from sector_pulse.storage.postgres import PostgresDatabase


class PostgresNewsRepository:
    """Synchronous PostgreSQL news metadata and relationship persistence."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def save(self, documents: Sequence[NewsDocument], events: Sequence[NewsEvent]) -> None:
        canonical_ids: dict[str, str] = {}
        with self._database.start().begin() as connection:
            for document in documents:
                existing = connection.execute(
                    text("SELECT document_id FROM news_documents WHERE canonical_url = :url"),
                    {"url": document.canonical_locator},
                )
                row = existing.first()
                canonical_ids[document.document_id] = row[0] if row else document.document_id
                if row:
                    continue
                connection.execute(
                    text(
                        """INSERT INTO news_documents
                        (document_id, source_id, canonical_url, title, published_at, observed_at,
                         content_hash, source_grade, metadata_json, citation_url, publisher, summary,
                         source_observed_at, use_grade, quality_flags_json)
                        VALUES (:document_id, :source_id, :canonical_url, :title, :published_at,
                         :observed_at, :content_hash, :source_grade, :metadata_json, :citation_url,
                         :publisher, :summary, :source_observed_at, :use_grade, :quality_flags_json)
                        ON CONFLICT (document_id) DO UPDATE SET title = EXCLUDED.title,
                         observed_at = EXCLUDED.observed_at, citation_url = EXCLUDED.citation_url,
                         publisher = EXCLUDED.publisher, summary = EXCLUDED.summary,
                         source_observed_at = EXCLUDED.source_observed_at,
                         quality_flags_json = EXCLUDED.quality_flags_json, metadata_json = EXCLUDED.metadata_json"""
                    ),
                    {
                        "document_id": document.document_id, "source_id": document.source_id,
                        "canonical_url": document.canonical_locator, "title": document.title,
                        "published_at": document.published_at.isoformat() if document.published_at else None,
                        "observed_at": document.collected_at.isoformat(), "content_hash": document.content_hash,
                        "source_grade": document.source_grade.value, "metadata_json": document.model_dump_json(),
                        "citation_url": document.citation_url, "publisher": document.publisher,
                        "summary": document.summary,
                        "source_observed_at": document.source_observed_at.isoformat()
                        if document.source_observed_at else None,
                        "use_grade": "EVIDENCE" if document.published_at is not None else "BACKGROUND",
                        "quality_flags_json": "[]",
                    },
                )
            for event in events:
                document_ids = tuple(dict.fromkeys(
                    canonical_ids.get(item, item) for item in event.document_ids
                ))
                normalized = event.model_copy(update={
                    "document_ids": document_ids,
                })
                connection.execute(
                    text("INSERT INTO news_events (event_id, canonical_title, first_published_at, "
                         "deduplication_reason, metadata_json) VALUES (:event_id, :title, :published_at, "
                         ":reason, :metadata) ON CONFLICT (event_id) DO UPDATE SET canonical_title = EXCLUDED.canonical_title, "
                         "metadata_json = EXCLUDED.metadata_json"),
                    {"event_id": normalized.event_id, "title": normalized.canonical_title,
                     "published_at": normalized.first_published_at.isoformat()
                     if normalized.first_published_at else None,
                     "reason": normalized.deduplication_reason, "metadata": normalized.model_dump_json()},
                )
                connection.execute(
                    text("DELETE FROM news_event_documents WHERE event_id = :event_id"),
                    {"event_id": normalized.event_id},
                )
                for document_id in normalized.document_ids:
                    connection.execute(
                        text(
                            "INSERT INTO news_event_documents (event_id, document_id) "
                            "VALUES (:event_id, :document_id) "
                            "ON CONFLICT (event_id, document_id) DO NOTHING"
                        ),
                        {"event_id": normalized.event_id, "document_id": document_id},
                    )

    def get_event(self, event_id: str) -> NewsEvent | None:
        values = self._metadata("news_events", event_id)
        return NewsEvent.model_validate_json(values) if values else None

    def get_events(self, event_ids: Sequence[str]) -> tuple[NewsEvent, ...]:
        if not event_ids:
            return ()
        with self._database.start().connect() as connection:
            result = connection.execute(
                text("SELECT metadata_json FROM news_events WHERE event_id = ANY(:ids)"),
                {"ids": list(event_ids)},
            )
            rows = result.fetchall()
        return tuple(NewsEvent.model_validate_json(row[0]) for row in rows)

    def get_documents(self, document_ids: Sequence[str]) -> dict[str, NewsDocument]:
        if not document_ids:
            return {}
        with self._database.start().connect() as connection:
            result = connection.execute(
                text("SELECT metadata_json FROM news_documents WHERE document_id = ANY(:ids)"),
                {"ids": list(document_ids)},
            )
            rows = result.fetchall()
        values = (NewsDocument.model_validate_json(row[0]) for row in rows)
        return {item.document_id: item for item in values}

    def _metadata(self, table: str, item_id: str) -> str | None:
        column = "event_id" if table == "news_events" else "document_id"
        with self._database.start().connect() as connection:
            result = connection.execute(
                text(f"SELECT metadata_json FROM {table} WHERE {column} = :item_id"),
                {"item_id": item_id},
            )
            row = result.first()
        return row[0] if row else None
