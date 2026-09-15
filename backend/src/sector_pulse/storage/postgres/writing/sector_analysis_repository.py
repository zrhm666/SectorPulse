from uuid import UUID

from sqlalchemy import text

from sector_pulse.domain.writing.research import SectorAnalysisArtifact
from sector_pulse.storage.postgres.database import PostgresDatabase


class PostgresSectorAnalysisRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def get(self, analysis_id: UUID) -> SectorAnalysisArtifact | None:
        with self._database.start().connect() as connection:
            row = connection.execute(
                text(
                    "SELECT payload_json FROM sector_analysis_artifacts "
                    "WHERE analysis_id=:analysis_id"
                ),
                {"analysis_id": str(analysis_id)},
            ).fetchone()
        return SectorAnalysisArtifact.model_validate_json(row[0]) if row else None
