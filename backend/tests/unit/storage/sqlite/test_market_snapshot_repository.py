from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sector_pulse.domain.market import SectorKind, SectorSnapshot, SectorUniverseSnapshot
from sector_pulse.domain.provider import DataStatus, ProviderResult
from sector_pulse.domain.time import AnalysisRun
from sector_pulse.ports.market_snapshot import SnapshotAfterCutoffError
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.market_snapshot_repository import SQLiteMarketSnapshotRepository


def build_result(observed_at: datetime) -> ProviderResult[SectorUniverseSnapshot]:
    snapshot = SectorUniverseSnapshot(
        provider_id="fixture",
        classification_version="fixture-industry-v1",
        source_version="fixture-v1",
        kind=SectorKind.INDUSTRY,
        observed_at=observed_at,
        collected_at=observed_at + timedelta(seconds=1),
        sectors=(
            SectorSnapshot(
                provider_sector_id="BK0001",
                name="示例行业",
                kind=SectorKind.INDUSTRY,
                pct_change=Decimal("1.5"),
                advancers=10,
                decliners=5,
            ),
        ),
    )
    return ProviderResult(
        provider_id="fixture",
        capability="sector_universe.industry",
        status=DataStatus.SUCCESS,
        data=snapshot,
        observed_at=observed_at,
        collected_at=snapshot.collected_at,
        source_version="fixture-v1",
    )


def create_repository(path: Path) -> SQLiteMarketSnapshotRepository:
    database = SQLiteDatabase(path)
    database.initialize()
    return SQLiteMarketSnapshotRepository(database)


def test_save_and_restore_market_snapshot(tmp_path: Path) -> None:
    cutoff = datetime(2026, 8, 14, 1, 40, tzinfo=UTC)
    run = AnalysisRun.create_live(cutoff).lock_live_cutoff(cutoff, cutoff)
    repository = create_repository(tmp_path / "market.db")
    result = build_result(cutoff)

    repository.save(run, result)

    restored = repository.get(run.run_id, SectorKind.INDUSTRY)
    assert restored == result.data


def test_snapshot_observed_after_cutoff_is_rejected(tmp_path: Path) -> None:
    cutoff = datetime(2026, 8, 14, 1, 40, tzinfo=UTC)
    run = AnalysisRun.create_live(cutoff).lock_live_cutoff(cutoff, cutoff)
    repository = create_repository(tmp_path / "market.db")

    with pytest.raises(SnapshotAfterCutoffError):
        repository.save(run, build_result(cutoff + timedelta(seconds=1)))
