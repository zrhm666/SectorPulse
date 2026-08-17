from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.real_data_run import (
    RealDataCandidate,
    RealDataRun,
    RealDataRunRequest,
    RealDataRunStatus,
)
from sector_pulse.storage.real_data_run_repository import SQLiteRealDataRunRepository
from sector_pulse.storage.sqlite import SQLiteDatabase

RUN_ID = uuid4()


def run(status: RealDataRunStatus = RealDataRunStatus.PREFLIGHT) -> RealDataRun:
    return RealDataRun(
        run_id=RUN_ID,
        request=RealDataRunRequest(
            mode="intraday", requested_at=datetime(2026, 8, 17, tzinfo=UTC)
        ),
        status=status,
    )


def candidate(sector_id: str) -> RealDataCandidate:
    return RealDataCandidate(
        sector_id=sector_id,
        sector_kind=SectorKind.INDUSTRY,
        rank=1,
        score=Decimal("1.25"),
        reasons=("涨幅",),
    )


def repository(tmp_path: Path) -> SQLiteRealDataRunRepository:
    return SQLiteRealDataRunRepository(SQLiteDatabase(tmp_path / "db.sqlite"))


def test_round_trip_run_and_candidates(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    repo.insert(run())
    repo.save_candidates(RUN_ID, (candidate("industry-1"),))

    stored = repo.get_run(RUN_ID)
    assert stored is not None
    assert stored.status is RealDataRunStatus.PREFLIGHT
    assert repo.get_candidates(RUN_ID)[0].sector_id == "industry-1"


def test_non_terminal_rows_become_interrupted(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    repo.insert(run(RealDataRunStatus.FETCHING_NEWS))

    assert repo.mark_interrupted() == 1
    assert repo.get_run(RUN_ID).status is RealDataRunStatus.INTERRUPTED
