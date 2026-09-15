from uuid import UUID

from sector_pulse.domain.writing.research import EvidenceInspectionReport
from sector_pulse.storage.sqlite.database import SQLiteDatabase


class SQLiteEvidenceInspectionRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def get(self, report_id: UUID) -> EvidenceInspectionReport | None:
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM evidence_inspection_reports WHERE report_id = ?",
                (str(report_id),),
            ).fetchone()
        return EvidenceInspectionReport.model_validate_json(row[0]) if row else None
