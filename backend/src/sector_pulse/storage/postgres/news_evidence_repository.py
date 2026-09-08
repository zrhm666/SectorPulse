from sqlalchemy import text

from sector_pulse.storage.postgres.database import PostgresDatabase
from sector_pulse.storage.sqlite.news_evidence_repository import NewsEvidenceItem


class PostgresNewsEvidenceRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def get_events(self, event_ids: tuple[str, ...]) -> tuple[NewsEvidenceItem, ...]:
        if not event_ids:
            return ()
        with self._database.start().connect() as connection:
            result = connection.execute(
                text(
                    "SELECT event_id, canonical_title, first_published_at FROM news_events "
                    "WHERE event_id = ANY(:event_ids)"
                ),
                {"event_ids": list(event_ids)},
            )
            events = result.fetchall()
            items: dict[str, NewsEvidenceItem] = {}
            for event_id, title, published_at in events:
                docs = connection.execute(
                    text(
                        "SELECT nd.title, nd.citation_url, nd.publisher, nd.published_at, "
                        "nd.source_grade FROM news_documents nd "
                        "JOIN news_event_documents ned ON ned.document_id = nd.document_id "
                        "WHERE ned.event_id = :event_id "
                        "ORDER BY CASE WHEN nd.citation_url IS NULL THEN 1 ELSE 0 END, "
                        "nd.published_at DESC, nd.document_id ASC"
                    ),
                    {"event_id": event_id},
                )
                items[event_id] = NewsEvidenceItem(
                    event_id=event_id, canonical_title=title,
                    first_published_at=published_at,
                    documents=tuple(
                        {"title": row[0], "citation_url": row[1], "publisher": row[2],
                         "published_at": row[3], "source_grade": row[4]}
                        for row in docs.fetchall()
                    ),
                )
        return tuple(items[event_id] for event_id in event_ids if event_id in items)
