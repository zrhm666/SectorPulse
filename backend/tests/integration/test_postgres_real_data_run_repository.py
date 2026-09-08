import os
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sector_pulse.domain.market.market import SectorKind
from sector_pulse.domain.market.quality import QualityStatus
from sector_pulse.domain.runs.real_data_run import (
    RealDataCandidate,
    RealDataQualitySummary,
    RealDataRun,
    RealDataRunRequest,
    RealDataRunStatus,
)
from sector_pulse.storage.postgres.database import PostgresDatabase
from sector_pulse.storage.postgres.runs.real_data_run_repository import (
    PostgresRealDataRunRepository,
)


@pytest.mark.postgres
def test_postgres_real_data_run_round_trip() -> None:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL")
    if not url:
        pytest.skip("requires SECTOR_PULSE_DATABASE_URL")
    database = PostgresDatabase(url)
    database.initialize()
    run = RealDataRun(
        request=RealDataRunRequest(mode="intraday", requested_at=datetime.now(UTC)),
        provider="fixture",
    )
    repository = PostgresRealDataRunRepository(database)
    repository.insert(run)
    loaded = repository.get_run(run.run_id)
    assert loaded is not None
    assert loaded.run_id == run.run_id
    assert loaded.request.mode == "intraday"
    assert loaded.provider == "fixture"

    candidates = (
        RealDataCandidate(
            sector_id="industry-1",
            sector_kind=SectorKind.INDUSTRY,
            rank=1,
            score=Decimal("9.5"),
            reasons=("momentum",),
        ),
    )
    repository.save_candidates(run.run_id, candidates)
    assert repository.get_candidates(run.run_id) == list(candidates)

    finished_at = datetime.now(UTC)
    quality = RealDataQualitySummary(
        market_quality={"market": QualityStatus.NORMAL},
        news_quality={"news": QualityStatus.NORMAL},
        downgrade_reasons=("SOURCE_DELAY",),
    )
    repository.update_status(
        run.run_id,
        RealDataRunStatus.DEGRADED,
        quality=quality,
        error_code="SOURCE_DELAY",
        finished_at=finished_at,
    )
    updated = repository.get_run(run.run_id)
    assert updated is not None
    assert updated.status is RealDataRunStatus.DEGRADED
    assert updated.quality == quality
    assert updated.error_code == "SOURCE_DELAY"
    assert updated.finished_at == finished_at
    assert run.run_id in {item.run_id for item in repository.list_runs()}

    interrupted = RealDataRun(request=RealDataRunRequest(mode="post_close"))
    repository.insert(interrupted)
    assert repository.mark_interrupted() >= 1
    recovered = repository.get_run(interrupted.run_id)
    assert recovered is not None
    assert recovered.status is RealDataRunStatus.INTERRUPTED
    database.close()
