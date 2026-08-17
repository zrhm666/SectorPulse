from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sector_pulse.application.real_data_writing_bridge import (
    RealDataRunNotReady,
    build_phase1b_request,
)
from sector_pulse.domain.real_data_run import RealDataRun, RealDataRunRequest, RealDataRunStatus
from sector_pulse.storage.real_data_run_repository import SQLiteRealDataRunRepository
from sector_pulse.storage.sqlite import SQLiteDatabase


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
