from datetime import UTC, datetime

import pytest
from sector_pulse.domain.candidate_selection import (
    CandidateSelection,
    CandidateSelectionMethod,
    CandidateSelectionVersionConflict,
)
from sector_pulse.domain.real_data_run import RealDataRun, RealDataRunRequest
from sector_pulse.storage.sqlite.candidate_selection_repository import (
    SQLiteCandidateSelectionRepository,
)
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.real_data_run_repository import SQLiteRealDataRunRepository


def selection(run_id, version: int, *, edit_count: int = 0) -> CandidateSelection:
    return CandidateSelection(
        run_id=run_id,
        version=version,
        selected_sector_ids=("881101", "881102", "309001"),
        method=CandidateSelectionMethod.DEFAULT
        if version == 1
        else CandidateSelectionMethod.MANUAL,
        confirmed_at=datetime.now(UTC),
        data_version="a" * 64,
        edit_count=edit_count,
    )


def test_sqlite_candidate_selections_are_versioned_and_cascade_with_the_run(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "selection.db")
    runs = SQLiteRealDataRunRepository(database)
    run = RealDataRun(request=RealDataRunRequest(mode="post_close"), provider="fixture")
    runs.insert(run)
    repository = SQLiteCandidateSelectionRepository(database)

    assert repository.latest(run.run_id) is None
    first = selection(run.run_id, 1)
    repository.append(first, expected_version=0)
    second = selection(run.run_id, 2, edit_count=1)
    repository.append(second, expected_version=1)

    assert repository.latest(run.run_id) == second
    assert repository.list_versions(run.run_id) == [first, second]
    with pytest.raises(CandidateSelectionVersionConflict):
        repository.append(selection(run.run_id, 3, edit_count=2), expected_version=1)

    with database.transaction() as connection:
        connection.execute("DELETE FROM real_data_runs WHERE run_id = ?", (str(run.run_id),))
    assert repository.latest(run.run_id) is None
