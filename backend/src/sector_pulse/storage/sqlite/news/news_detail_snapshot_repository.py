from uuid import UUID

from sector_pulse.domain.news.research import NewsDetailSnapshot
from sector_pulse.storage.sqlite.database import SQLiteDatabase


class SQLiteNewsDetailSnapshotRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def get(self, detail_id: UUID) -> NewsDetailSnapshot | None:
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM news_detail_snapshots WHERE detail_id = ?",
                (str(detail_id),),
            ).fetchone()
        return NewsDetailSnapshot.model_validate_json(row[0]) if row else None
