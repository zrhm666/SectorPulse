from uuid import UUID

from sector_pulse.domain.news.news_batch import NewsBatch
from sector_pulse.storage.sqlite.database import SQLiteDatabase


class SQLiteNewsBatchRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def get(self, batch_id: UUID) -> NewsBatch | None:
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM news_batches WHERE batch_id = ?",
                (str(batch_id),),
            ).fetchone()
        return NewsBatch.model_validate_json(row[0]) if row else None

