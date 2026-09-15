from uuid import UUID

from sqlalchemy import text

from sector_pulse.domain.news.research import ResearchSearchBatch
from sector_pulse.storage.postgres.database import PostgresDatabase


class PostgresResearchSearchRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def get(self, batch_id: UUID) -> ResearchSearchBatch | None:
        with self._database.start().connect() as connection:
            row = connection.execute(
                text("SELECT payload_json FROM research_search_batches WHERE batch_id=:batch_id"),
                {"batch_id": str(batch_id)},
            ).fetchone()
        return ResearchSearchBatch.model_validate_json(row[0]) if row else None
