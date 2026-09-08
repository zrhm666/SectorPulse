from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sector_pulse.application.data_runs import real_data_writing_bridge as bridge
from sector_pulse.application.data_runs.real_data_writing_bridge import (
    RealDataRunNotReady,
    build_phase1b_request,
)
from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.real_data_run import (
    RealDataCandidate,
    RealDataRun,
    RealDataRunRequest,
    RealDataRunStatus,
)
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.real_data_run_repository import SQLiteRealDataRunRepository


def test_non_ready_run_is_rejected_before_bridge_reads_artifacts(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "bridge.db")
    database.initialize()
    run = RealDataRun(
        run_id=uuid4(),
        request=RealDataRunRequest(mode="intraday", requested_at=datetime.now(UTC)),
        status=RealDataRunStatus.DEGRADED,
    )
    SQLiteRealDataRunRepository(database).insert(run)
    with pytest.raises(RealDataRunNotReady, match="REAL_DATA_RUN_NOT_READY"):
        build_phase1b_request(database, run.run_id)


def test_requested_candidates_are_filtered_in_persisted_rank_order() -> None:
    candidates = [
        RealDataCandidate(
            sector_id=f"sector-{rank}", sector_kind=SectorKind.INDUSTRY,
            rank=rank, score=10 - rank,
        )
        for rank in range(1, 5)
    ]

    selected = bridge.select_requested_candidates(
        candidates, ("sector-4", "sector-1", "sector-3")
    )

    assert [item.sector_id for item in selected] == ["sector-1", "sector-3", "sector-4"]


@pytest.mark.parametrize(
    "sector_ids",
    [
        ("sector-1", "sector-2"),
        ("sector-1", "sector-1", "sector-2"),
        ("sector-1", "sector-2", "missing"),
    ],
)
def test_invalid_requested_candidates_are_rejected(sector_ids: tuple[str, ...]) -> None:
    candidates = [
        RealDataCandidate(
            sector_id=f"sector-{rank}", sector_kind=SectorKind.INDUSTRY,
            rank=rank, score=10 - rank,
        )
        for rank in range(1, 5)
    ]

    with pytest.raises(bridge.RealDataBridgeIncomplete, match="CANDIDATE_SELECTION_INVALID"):
        bridge.select_requested_candidates(candidates, sector_ids)
