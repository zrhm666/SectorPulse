from uuid import UUID

from sqlalchemy import text

from sector_pulse.domain.writing.research import EvidenceInspectionReport
from sector_pulse.storage.postgres.database import PostgresDatabase


class PostgresEvidenceInspectionRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def get(self, report_id: UUID) -> EvidenceInspectionReport | None:
        with self._database.start().connect() as connection:
            row = connection.execute(
                text(
                    "SELECT payload_json FROM evidence_inspection_reports "
                    "WHERE report_id=:report_id"
                ),
                {"report_id": str(report_id)},
            ).fetchone()
        return EvidenceInspectionReport.model_validate_json(row[0]) if row else None
