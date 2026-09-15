from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter
from sector_pulse.application.orchestration.data_tools import (
    CollectMarketService,
    MarketCollectionContext,
    MarketCollectionRequest,
)
from sector_pulse.application.orchestration.tasks import TaskCoordinator, TaskOwnershipError
from sector_pulse.domain.market.market import SectorKind, SectorSnapshot, SectorUniverseSnapshot
from sector_pulse.domain.orchestration.models import RunSnapshot, TaskRecord
from sector_pulse.domain.provider import DataStatus, ProviderResult
from sector_pulse.domain.runs.time import AnalysisMode, AnalysisRun
from sector_pulse.ports.market_data import MarketDataPort
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.market.market_snapshot_repository import (
    SQLiteMarketSnapshotRepository,
)
from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

NOW = datetime(2026, 9, 13, 8, tzinfo=UTC)


class MarketProvider:
    def __init__(
        self, observed_by_kind: dict[SectorKind, datetime] | None = None
    ) -> None:
        self.calls: list[SectorKind] = []
        self.observed_by_kind = observed_by_kind or {}

    async def fetch_sector_universe(
        self, kind: SectorKind, mode: AnalysisMode
    ) -> ProviderResult[SectorUniverseSnapshot]:
        self.calls.append(kind)
        observed_at = self.observed_by_kind.get(kind, NOW)
        return ProviderResult(
            provider_id="fixture-market",
            capability="market.sector_universe",
            status=DataStatus.SUCCESS,
            data=SectorUniverseSnapshot(
                provider_id="fixture-market",
                classification_version="v1",
                source_version="v1",
                kind=kind,
                observed_at=observed_at,
                collected_at=NOW,
                sectors=(
                    SectorSnapshot(
                        provider_sector_id=f"{kind.value}-1",
                        name="测试板块",
                        kind=kind,
                        pct_change=Decimal("1.2"),
                    ),
                ),
            ),
            observed_at=observed_at,
            collected_at=NOW,
            source_version="v1",
        )


def setup_state(
    tmp_path: Path, *, lease_expires_at: datetime
) -> tuple[
    SQLiteDatabase,
    SQLiteOrchestrationRepository,
    TaskRecord,
    AnalysisRun,
]:
    database = SQLiteDatabase(tmp_path / "market-tool.db")
    database.initialize()
    repository = SQLiteOrchestrationRepository(database)
    task = TaskRecord(task_id=uuid4(), role="A1", scope="data")
    snapshot = RunSnapshot(
        run_id=uuid4(),
        deadline=datetime.now(UTC) + timedelta(minutes=30),
        tasks=(task,),
    )
    repository.save(snapshot, -1, "created")
    TaskCoordinator(repository, snapshot.run_id).start(
        task.task_id,
        attempt=1,
        worker_id="worker-a1",
        lease_expires_at=lease_expires_at,
        now=NOW,
    )
    run = AnalysisRun.create_live(NOW - timedelta(minutes=1), snapshot.run_id).lock_live_cutoff(
        NOW, NOW
    )
    return database, repository, task, run


@pytest.mark.asyncio
async def test_market_collection_persists_business_snapshot_and_artifact_atomically(
    tmp_path: Path,
) -> None:
    database, repository, task, run = setup_state(
        tmp_path, lease_expires_at=NOW + timedelta(minutes=5)
    )
    provider = MarketProvider()
    context = MarketCollectionContext(
        run=run,
        task_id=task.task_id,
        attempt=1,
        worker_id="worker-a1",
        orchestration=repository,
        committer=AtomicArtifactCommitter(repository, run.run_id),
    )
    service = CollectMarketService(cast(MarketDataPort, provider), mode=AnalysisMode.LIVE)

    collected = await service.collect_and_persist(
        MarketCollectionRequest(kinds=(SectorKind.INDUSTRY,)), context=context, now=NOW
    )

    persisted = SQLiteMarketSnapshotRepository(database).get(run.run_id, SectorKind.INDUSTRY)
    state = repository.load(run.run_id)
    assert persisted == collected.results[SectorKind.INDUSTRY].data
    assert state is not None
    assert [(item.kind, item.reference) for item in state.artifacts] == [
        ("market_snapshot", f"market:{run.run_id}:INDUSTRY:v1")
    ]


@pytest.mark.asyncio
async def test_expired_lease_rejects_market_call_before_provider_side_effect(
    tmp_path: Path,
) -> None:
    _database, repository, task, run = setup_state(
        tmp_path, lease_expires_at=NOW + timedelta(seconds=1)
    )
    provider = MarketProvider()
    context = MarketCollectionContext(
        run=run,
        task_id=task.task_id,
        attempt=1,
        worker_id="worker-a1",
        orchestration=repository,
        committer=AtomicArtifactCommitter(repository, run.run_id),
    )
    service = CollectMarketService(cast(MarketDataPort, provider), mode=AnalysisMode.LIVE)

    with pytest.raises(TaskOwnershipError, match="lease expired"):
        await service.collect_and_persist(
            MarketCollectionRequest(kinds=(SectorKind.CONCEPT,)),
            context=context,
            now=NOW + timedelta(seconds=2),
        )

    assert provider.calls == []
    state = repository.load(run.run_id)
    assert state is not None
    assert state.artifacts == ()


@pytest.mark.asyncio
async def test_initial_core_collection_locks_cutoff_and_is_recoverable(tmp_path: Path) -> None:
    database, repository, task, locked_run = setup_state(
        tmp_path, lease_expires_at=NOW + timedelta(minutes=5)
    )
    run = AnalysisRun.create_live(NOW - timedelta(minutes=1), locked_run.run_id)
    provider = MarketProvider(
        {
            SectorKind.INDUSTRY: NOW - timedelta(seconds=5),
            SectorKind.CONCEPT: NOW,
        }
    )
    context = MarketCollectionContext(
        run=run,
        task_id=task.task_id,
        attempt=1,
        worker_id="worker-a1",
        orchestration=repository,
        committer=AtomicArtifactCommitter(repository, run.run_id),
    )
    service = CollectMarketService(cast(MarketDataPort, provider), mode=AnalysisMode.LIVE)

    result = await service.collect_core_and_persist(
        context=context,
        locked_at=NOW,
        max_skew_seconds=10,
    )

    assert result.run.run_cutoff_at == NOW
    recovered = SQLiteMarketSnapshotRepository(database).get_run(run.run_id)
    assert recovered == result.run
    state = repository.load(run.run_id)
    assert state is not None
    assert {artifact.reference.split(":")[2] for artifact in state.artifacts} == {
        "INDUSTRY",
        "CONCEPT",
    }


@pytest.mark.asyncio
async def test_initial_core_collection_rejects_observation_skew_before_persistence(
    tmp_path: Path,
) -> None:
    database, repository, task, locked_run = setup_state(
        tmp_path, lease_expires_at=NOW + timedelta(minutes=5)
    )
    run = AnalysisRun.create_live(NOW - timedelta(minutes=1), locked_run.run_id)
    provider = MarketProvider(
        {
            SectorKind.INDUSTRY: NOW - timedelta(seconds=11),
            SectorKind.CONCEPT: NOW,
        }
    )
    service = CollectMarketService(cast(MarketDataPort, provider), mode=AnalysisMode.LIVE)

    with pytest.raises(ValueError, match="skew"):
        await service.collect_core_and_persist(
            context=MarketCollectionContext(
                run=run,
                task_id=task.task_id,
                attempt=1,
                worker_id="worker-a1",
                orchestration=repository,
                committer=AtomicArtifactCommitter(repository, run.run_id),
            ),
            locked_at=NOW,
            max_skew_seconds=10,
        )

    assert SQLiteMarketSnapshotRepository(database).get(
        run.run_id, SectorKind.INDUSTRY
    ) is None
    state = repository.load(run.run_id)
    assert state is not None
    assert state.artifacts == ()


@pytest.mark.asyncio
async def test_budgeted_market_tool_replay_does_not_call_provider_twice(tmp_path: Path) -> None:
    from sector_pulse.application.orchestration.tool_budget import SharedToolBudget
    from sector_pulse.infrastructure.agents.data_tools import CollectMarketTool
    from sector_pulse.infrastructure.agents.tool_adapter import BudgetedTool

    database, repository, task, run = setup_state(
        tmp_path, lease_expires_at=NOW + timedelta(minutes=5)
    )
    provider = MarketProvider()
    market_repository = SQLiteMarketSnapshotRepository(database)
    inner = CollectMarketTool(
        CollectMarketService(cast(MarketDataPort, provider), mode=AnalysisMode.LIVE),
        context=MarketCollectionContext(
            run=run,
            task_id=task.task_id,
            attempt=1,
            worker_id="worker-a1",
            orchestration=repository,
            committer=AtomicArtifactCommitter(repository, run.run_id),
        ),
        snapshots=market_repository,
        clock=lambda: NOW,
    )
    tool = BudgetedTool(
        inner,
        SharedToolBudget(repository, run.run_id),
        task_id=task.task_id,
        attempt=1,
        reserved_cny=Decimal("0"),
        replay_resolver=inner.replay,
    )

    first = await tool.run(kinds=["INDUSTRY"])
    replay = await tool.run(kinds=["INDUSTRY"])

    assert first.success and replay.success
    assert first.content == replay.content
    assert provider.calls == [SectorKind.INDUSTRY]
    state = repository.load(run.run_id)
    assert state is not None
    assert state.ledger.tool_calls == 1


@pytest.mark.asyncio
async def test_market_tool_initial_core_call_locks_cutoff_and_replays_batch(
    tmp_path: Path,
) -> None:
    from sector_pulse.application.orchestration.tool_budget import SharedToolBudget
    from sector_pulse.infrastructure.agents.data_tools import CollectMarketTool
    from sector_pulse.infrastructure.agents.tool_adapter import BudgetedTool

    database, repository, task, locked_run = setup_state(
        tmp_path, lease_expires_at=NOW + timedelta(minutes=5)
    )
    run = AnalysisRun.create_live(NOW - timedelta(minutes=1), locked_run.run_id)
    provider = MarketProvider()
    snapshots = SQLiteMarketSnapshotRepository(database)
    inner = CollectMarketTool(
        CollectMarketService(cast(MarketDataPort, provider), mode=AnalysisMode.LIVE),
        context=MarketCollectionContext(
            run=run,
            task_id=task.task_id,
            attempt=1,
            worker_id="worker-a1",
            orchestration=repository,
            committer=AtomicArtifactCommitter(repository, run.run_id),
        ),
        snapshots=snapshots,
        clock=lambda: NOW,
        max_core_skew_seconds=10,
    )
    tool = BudgetedTool(
        inner,
        SharedToolBudget(repository, run.run_id),
        task_id=task.task_id,
        attempt=1,
        reserved_cny=Decimal("0"),
    )

    first = await tool.run(kinds=["INDUSTRY", "CONCEPT"])
    replay = await tool.run(kinds=["INDUSTRY", "CONCEPT"])

    assert first.success and replay.success
    assert first.content == replay.content
    assert provider.calls == [SectorKind.INDUSTRY, SectorKind.CONCEPT]
    assert snapshots.get_run(run.run_id).run_cutoff_at == NOW


@pytest.mark.asyncio
async def test_quality_tool_reads_persisted_artifact_with_server_thresholds(tmp_path: Path) -> None:
    from sector_pulse.application.orchestration.data_tools import InspectDataQualityService
    from sector_pulse.domain.market.quality import QualityThresholds
    from sector_pulse.infrastructure.agents.data_tools import InspectDataQualityTool

    database, repository, task, run = setup_state(
        tmp_path, lease_expires_at=NOW + timedelta(minutes=5)
    )
    provider = MarketProvider()
    context = MarketCollectionContext(
        run=run,
        task_id=task.task_id,
        attempt=1,
        worker_id="worker-a1",
        orchestration=repository,
        committer=AtomicArtifactCommitter(repository, run.run_id),
    )
    await CollectMarketService(
        cast(MarketDataPort, provider), mode=AnalysisMode.LIVE
    ).collect_and_persist(
        MarketCollectionRequest(kinds=(SectorKind.INDUSTRY,)), context=context, now=NOW
    )
    state = repository.load(run.run_id)
    assert state is not None
    artifact = state.artifacts[0]
    tool = InspectDataQualityTool(
        InspectDataQualityService(
            QualityThresholds(min_industry_count=2, min_concept_count=2)
        ),
        context=context,
        snapshots=SQLiteMarketSnapshotRepository(database),
        clock=lambda: NOW,
    )

    result = await tool.run(artifact_ref=str(artifact.artifact_id))

    assert result.success
    assert '"status": "BLOCKED"' in result.content
    assert '"issues": ["INSUFFICIENT_COVERAGE"]' in result.content
    rejected = await tool.run(
        artifact_ref=str(artifact.artifact_id), min_industry_count=0
    )
    assert not rejected.success


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_postgres_market_snapshot_and_artifact_share_transaction() -> None:
    import os

    from sector_pulse.storage.postgres.database import PostgresDatabase
    from sector_pulse.storage.postgres.market.market_snapshot_repository import (
        PostgresMarketSnapshotRepository,
    )
    from sector_pulse.storage.postgres.orchestration.repository import (
        PostgresOrchestrationRepository,
    )
    from sqlalchemy import text
    from sqlalchemy.engine import make_url

    url = os.getenv("SECTOR_PULSE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires dedicated SECTOR_PULSE_TEST_DATABASE_URL")
    assert (make_url(url).database or "").endswith("_test"), "business database refused"
    database = PostgresDatabase(url)
    database.initialize()
    repository = PostgresOrchestrationRepository(database)
    provider = MarketProvider()
    now = datetime.now(UTC)
    task = TaskRecord(task_id=uuid4(), role="A1", scope="data")
    snapshot = RunSnapshot(
        run_id=uuid4(),
        deadline=now + timedelta(minutes=10),
        tasks=(task,),
    )
    run = AnalysisRun.create_live(now, snapshot.run_id).lock_live_cutoff(now, now)
    repository.save(snapshot, -1, "created")
    TaskCoordinator(repository, snapshot.run_id).start(
        task.task_id,
        attempt=1,
        worker_id="worker-a1",
        lease_expires_at=now + timedelta(minutes=5),
        now=now,
    )
    try:
        await CollectMarketService(
            cast(MarketDataPort, provider), mode=AnalysisMode.LIVE
        ).collect_and_persist(
            MarketCollectionRequest(kinds=(SectorKind.CONCEPT,)),
            context=MarketCollectionContext(
                run=run,
                task_id=task.task_id,
                attempt=1,
                worker_id="worker-a1",
                orchestration=repository,
                committer=AtomicArtifactCommitter(repository, run.run_id),
            ),
            now=now,
        )
        persisted = PostgresMarketSnapshotRepository(database).get(
            run.run_id, SectorKind.CONCEPT
        )
        state = repository.load(run.run_id)
        assert persisted is not None
        assert state is not None
        assert state.artifacts[0].reference.endswith(":CONCEPT:v1")
    finally:
        with database.start().begin() as connection:
            connection.execute(
                text("DELETE FROM sector_snapshots WHERE run_id=:run_id"),
                {"run_id": str(run.run_id)},
            )
            connection.execute(
                text("DELETE FROM analysis_runs WHERE run_id=:run_id"),
                {"run_id": str(run.run_id)},
            )
            connection.execute(
                text("DELETE FROM orchestration_events WHERE run_id=:run_id"),
                {"run_id": str(run.run_id)},
            )
            connection.execute(
                text("DELETE FROM orchestration_snapshots WHERE run_id=:run_id"),
                {"run_id": str(run.run_id)},
            )
        database.close()
