from dataclasses import dataclass
from typing import Any

from sector_pulse.storage.sqlite import SQLiteDatabase


@dataclass(frozen=True)
class NewsEvidenceItem:
    event_id: str
    canonical_title: str
    first_published_at: str | None
    documents: tuple[dict[str, Any], ...]


class SQLiteNewsEvidenceRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database
        self._database.initialize()

    def get_events(self, event_ids: tuple[str, ...]) -> tuple[NewsEvidenceItem, ...]:
        if not event_ids:
            return ()
        placeholders = ",".join("?" for _ in event_ids)
        with self._database.connection() as conn:
            event_rows = conn.execute(
                f"""SELECT event_id, canonical_title, first_published_at
                    FROM news_events WHERE event_id IN ({placeholders})""",
                tuple(event_ids),
            ).fetchall()
            items: list[NewsEvidenceItem] = []
            for eid, title, published_at in event_rows:
                doc_rows = conn.execute(
                    """SELECT nd.title, nd.citation_url, nd.publisher,
                              nd.published_at, nd.source_grade
                       FROM news_documents nd
                       JOIN news_event_documents ned ON ned.document_id = nd.document_id
                       WHERE ned.event_id = ?""",
                    (eid,),
                ).fetchall()
                items.append(
                    NewsEvidenceItem(
                        event_id=eid,
                        canonical_title=title,
                        first_published_at=published_at,
                        documents=tuple(
                            {
                                "title": d[0],
                                "citation_url": d[1],
                                "publisher": d[2],
                                "published_at": d[3],
                                "source_grade": d[4],
                            }
                            for d in doc_rows
                        ),
                    )
                )
        return tuple(items)