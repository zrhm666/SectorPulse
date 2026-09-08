import json
from datetime import datetime
from uuid import UUID

from sector_pulse.domain.market.candidate_selection import (
    CandidateSelection,
    CandidateSelectionMethod,
    CandidateSelectionVersionConflict,
)
from sector_pulse.storage.sqlite.database import SQLiteDatabase


class SQLiteCandidateSelectionRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database
        self._database.initialize()

    def append(self, selection: CandidateSelection, *, expected_version: int) -> None:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT MAX(version) FROM data_run_candidate_selections WHERE run_id = ?",
                (str(selection.run_id),),
            ).fetchone()
            actual_version = int(row[0]) if row and row[0] is not None else 0
            self._check_version(selection, expected_version, actual_version)
            connection.execute(
                """INSERT INTO data_run_candidate_selections
                (run_id, version, selected_sector_ids_json, method, confirmed_at,
                 data_version, edit_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(selection.run_id),
                    selection.version,
                    json.dumps(selection.selected_sector_ids, ensure_ascii=False),
                    selection.method.value,
                    selection.confirmed_at.isoformat(),
                    selection.data_version,
                    selection.edit_count,
                ),
            )

    def latest(self, run_id: UUID) -> CandidateSelection | None:
        with self._database.connection() as connection:
            row = connection.execute(
                """SELECT run_id, version, selected_sector_ids_json, method,
                confirmed_at, data_version, edit_count
                FROM data_run_candidate_selections WHERE run_id = ?
                ORDER BY version DESC LIMIT 1""",
                (str(run_id),),
            ).fetchone()
        return self._row(row) if row else None

    def list_versions(self, run_id: UUID) -> list[CandidateSelection]:
        with self._database.connection() as connection:
            rows = connection.execute(
                """SELECT run_id, version, selected_sector_ids_json, method,
                confirmed_at, data_version, edit_count
                FROM data_run_candidate_selections WHERE run_id = ? ORDER BY version""",
                (str(run_id),),
            ).fetchall()
        return [self._row(row) for row in rows]

    @staticmethod
    def _check_version(
        selection: CandidateSelection, expected_version: int, actual_version: int
    ) -> None:
        if expected_version != actual_version or selection.version != actual_version + 1:
            raise CandidateSelectionVersionConflict(
                f"candidate selection version conflict: expected={expected_version} "
                f"actual={actual_version} next={selection.version}"
            )

    @staticmethod
    def _row(row: tuple[object, ...]) -> CandidateSelection:
        return CandidateSelection(
            run_id=UUID(str(row[0])),
            version=int(str(row[1])),
            selected_sector_ids=tuple(json.loads(str(row[2]))),
            method=CandidateSelectionMethod(str(row[3])),
            confirmed_at=datetime.fromisoformat(str(row[4])),
            data_version=str(row[5]),
            edit_count=int(str(row[6])),
        )
