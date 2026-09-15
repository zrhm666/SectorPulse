from uuid import UUID

from sqlalchemy import text

from sector_pulse.domain.news.research import NewsDetailSnapshot
from sector_pulse.storage.postgres.database import PostgresDatabase


class PostgresNewsDetailSnapshotRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def get(self, detail_id: UUID) -> NewsDetailSnapshot | None:
        with self._database.start().connect() as connection:
            row = connection.execute(
                text("SELECT payload_json FROM news_detail_snapshots WHERE detail_id=:detail_id"),
                {"detail_id": str(detail_id)},
            ).fetchone()
        return NewsDetailSnapshot.model_validate_json(row[0]) if row else None
