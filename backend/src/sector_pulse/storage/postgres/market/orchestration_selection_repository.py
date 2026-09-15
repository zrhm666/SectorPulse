import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from sector_pulse.domain.market.candidate_selection import (
    CandidateSelection,
    CandidateSelectionMethod,
)
from sector_pulse.storage.postgres.database import PostgresDatabase


class PostgresOrchestrationSelectionRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def latest(self, run_id: UUID) -> CandidateSelection | None:
        values = self.list_versions(run_id)
        return values[-1] if values else None

    def list_versions(self, run_id: UUID) -> list[CandidateSelection]:
        with self._database.start().connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT run_id,version,selected_sector_ids_json,method,confirmed_at,"
                    "data_version,edit_count FROM orchestration_candidate_selections "
                    "WHERE run_id=:run ORDER BY version"
                ),
                {"run": str(run_id)},
            ).fetchall()
        return [
            CandidateSelection(
                run_id=UUID(str(row[0])),
                version=int(row[1]),
                selected_sector_ids=tuple(json.loads(str(row[2]))),
                method=CandidateSelectionMethod(str(row[3])),
                confirmed_at=(
                    row[4] if isinstance(row[4], datetime) else datetime.fromisoformat(str(row[4]))
                ),
                data_version=str(row[5]),
                edit_count=int(row[6]),
            )
            for row in rows
        ]
