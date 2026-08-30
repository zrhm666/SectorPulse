import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping

from sector_pulse.domain.candidate_selection import (
    CandidateSelection,
    CandidateSelectionMethod,
)
from sector_pulse.storage.candidate_selection_repository import (
    SQLiteCandidateSelectionRepository,
)
from sector_pulse.storage.postgres import PostgresDatabase


class PostgresCandidateSelectionRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def append(self, selection: CandidateSelection, *, expected_version: int) -> None:
        engine = self._database.start()
        with engine.begin() as connection:
            result = connection.execute(
                text(
                    "SELECT MAX(version) FROM data_run_candidate_selections WHERE run_id = :run_id"
                ),
                {"run_id": str(selection.run_id)},
            )
            value = result.scalar_one_or_none()
            actual_version = int(value) if value is not None else 0
            SQLiteCandidateSelectionRepository._check_version(
                selection, expected_version, actual_version
            )
            connection.execute(
                text(
                    """INSERT INTO data_run_candidate_selections
                    (run_id, version, selected_sector_ids_json, method, confirmed_at,
                     data_version, edit_count)
                    VALUES (:run_id, :version, :sector_ids, :method, :confirmed_at,
                     :data_version, :edit_count)"""
                ),
                self._values(selection),
            )

    def latest(self, run_id: UUID) -> CandidateSelection | None:
        engine = self._database.start()
        with engine.connect() as connection:
            result = connection.execute(
                text(
                    """SELECT run_id, version, selected_sector_ids_json, method,
                    confirmed_at, data_version, edit_count
                    FROM data_run_candidate_selections WHERE run_id = :run_id
                    ORDER BY version DESC LIMIT 1"""
                ),
                {"run_id": str(run_id)},
            )
            row = result.mappings().first()
        return self._row(row) if row else None

    def list_versions(self, run_id: UUID) -> list[CandidateSelection]:
        engine = self._database.start()
        with engine.connect() as connection:
            result = connection.execute(
                text(
                    """SELECT run_id, version, selected_sector_ids_json, method,
                    confirmed_at, data_version, edit_count
                    FROM data_run_candidate_selections WHERE run_id = :run_id
                    ORDER BY version"""
                ),
                {"run_id": str(run_id)},
            )
            rows = result.mappings().all()
        return [self._row(row) for row in rows]

    @staticmethod
    def _values(selection: CandidateSelection) -> dict[str, object]:
        return {
            "run_id": str(selection.run_id),
            "version": selection.version,
            "sector_ids": json.dumps(selection.selected_sector_ids, ensure_ascii=False),
            "method": selection.method.value,
            "confirmed_at": selection.confirmed_at.isoformat(),
            "data_version": selection.data_version,
            "edit_count": selection.edit_count,
        }

    @staticmethod
    def _row(row: RowMapping) -> CandidateSelection:
        return CandidateSelection(
            run_id=UUID(str(row["run_id"])),
            version=int(str(row["version"])),
            selected_sector_ids=tuple(json.loads(str(row["selected_sector_ids_json"]))),
            method=CandidateSelectionMethod(str(row["method"])),
            confirmed_at=datetime.fromisoformat(str(row["confirmed_at"])),
            data_version=str(row["data_version"]),
            edit_count=int(str(row["edit_count"])),
        )
