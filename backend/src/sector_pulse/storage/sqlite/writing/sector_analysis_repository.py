from uuid import UUID

from sector_pulse.domain.writing.research import SectorAnalysisArtifact
from sector_pulse.storage.sqlite.database import SQLiteDatabase


class SQLiteSectorAnalysisRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def get(self, analysis_id: UUID) -> SectorAnalysisArtifact | None:
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM sector_analysis_artifacts WHERE analysis_id = ?",
                (str(analysis_id),),
            ).fetchone()
        return SectorAnalysisArtifact.model_validate_json(row[0]) if row else None
