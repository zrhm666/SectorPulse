import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from sector_pulse.application.data_runs.candidate_selection import (
    select_candidates,
    select_market_precandidates,
)
from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter
from sector_pulse.application.orchestration.candidate_tools import RankSectorCandidatesService
from sector_pulse.application.orchestration.data_tools import (
    CollectMarketService,
    MarketCollectionContext,
)
from sector_pulse.application.orchestration.tasks import TaskCoordinator
from sector_pulse.domain.market.candidate_batch import CandidateRankingStage
from sector_pulse.domain.market.market import SectorKind, SectorSnapshot, SectorUniverseSnapshot
from sector_pulse.domain.news.news import NewsDocument
from sector_pulse.domain.orchestration.models import RunSnapshot, TaskRecord
from sector_pulse.domain.provider import DataStatus, ProviderError, ProviderResult
from sector_pulse.domain.runs.time import AnalysisMode, AnalysisRun
from sector_pulse.ports.market_data import MarketDataPort
from sector_pulse.ports.news_sources import (
    DisclosureSearchPort,
    GlobalNewsDiscoveryPort,
    KeywordNewsSearchPort,
    SectorConstituentPort,
)
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.market.candidate_batch_repository import (
    SQLiteCandidateBatchRepository,
)
from sector_pulse.storage.sqlite.market.market_snapshot_repository import (
    SQLiteMarketSnapshotRepository,
)
from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

NOW = datetime(2026, 9, 13, 9, tzinfo=UTC)


class MarketProvider:
    async def fetch_sector_universe(
        self, kind: SectorKind, mode: AnalysisMode
    ) -> ProviderResult[SectorUniverseSnapshot]:
        assert mode is AnalysisMode.LIVE
        return ProviderResult(
            provider_id="fixture-market",
            capability="market.sector_universe",
            status=DataStatus.SUCCESS,
            data=SectorUniverseSnapshot(
                provider_id="fixture-market",
                classification_version="v1",
                source_version="v1",
                kind=kind,
                observed_at=NOW,
                collected_at=NOW,
                sectors=tuple(
                    SectorSnapshot(
                        provider_sector_id=f"{kind.value}-{index}",
                        name=f"{kind.value} {index}",
                        kind=kind,
                        pct_change=Decimal(index),
                        turnover_rate=None if index == 1 else Decimal(index),
                        advancers=index,
                        decliners=4 - index,
                    )
                    for index in range(1, 4)
                ),
                available_fields=frozenset({"pct_change", "advancers", "decliners"}),
            ),
            observed_at=NOW,
            collected_at=NOW,
            source_version="v1",
        )


class ConstituentsProvider:
    async def fetch_constituents(
        self, sector_name: str, kind: SectorKind
    ) -> ProviderResult[tuple[tuple[str, str], ...]]:
        del sector_name, kind
        return ProviderResult(
            provider_id="fixture-constituents",
            capability="sector_constituents",
            status=DataStatus.SUCCESS,
            data=(("600001", "测试股"),),
            collected_at=NOW,
        )


class NewsProviders:
    def __init__(self, suffix: str = "") -> None:
        self.global_calls = 0
        self.keyword_calls = 0
        self.disclosure_calls = 0
        self.suffix = suffix

    def documents(self) -> tuple[NewsDocument, ...]:
        from sector_pulse.domain.news.news import SourceGrade

        return tuple(
            NewsDocument(
                document_id=f"doc-{index}{self.suffix}",
                source_id="cls",
                canonical_locator=f"urn:test:doc-{index}{self.suffix}",
                citation_url=f"https://example.test/doc-{index}{self.suffix}",
                title="INDUSTRY 3 出现政策催化",
                publisher="测试媒体",
                summary="INDUSTRY 3 测试摘要",
                published_at=NOW - timedelta(minutes=5),
                source_observed_at=NOW - timedelta(minutes=1),
                collected_at=NOW,
                content_hash=f"same-content{self.suffix}",
                source_grade=SourceGrade.REPUTABLE_MEDIA,
            )
            for index in (1, 2)
        )

    async def fetch_global(
        self, cutoff: datetime
    ) -> ProviderResult[tuple[NewsDocument, ...]]:
        del cutoff
        self.global_calls += 1
        return ProviderResult(
            provider_id="cls",
            capability="news.global.discovery",
            status=DataStatus.SUCCESS,
            data=self.documents(),
            collected_at=NOW,
        )

    async def search(
        self, query: str, start_at: datetime, cutoff: datetime
    ) -> ProviderResult[tuple[NewsDocument, ...]]:
        del query, start_at, cutoff
        self.keyword_calls += 1
        return ProviderResult(
            provider_id="eastmoney",
            capability="news.keyword.search",
            status=DataStatus.EMPTY,
            collected_at=NOW,
        )

    async def search_disclosures(
        self, stock_codes: tuple[str, ...], start_at: datetime, cutoff: datetime
    ) -> ProviderResult[tuple[NewsDocument, ...]]:
        del stock_codes, start_at, cutoff
        self.disclosure_calls += 1
        return ProviderResult(
            provider_id="cninfo",
            capability="news.disclosure.search",
            status=DataStatus.EMPTY,
            collected_at=NOW,
        )


class RetryingNewsProviders(NewsProviders):
    async def search(
        self, query: str, start_at: datetime, cutoff: datetime
    ) -> ProviderResult[tuple[NewsDocument, ...]]:
        del query, start_at, cutoff
        self.keyword_calls += 1
        return ProviderResult(
            provider_id="eastmoney",
            capability="news.keyword.search",
            status=DataStatus.FAILED,
            collected_at=NOW,
            error=ProviderError(
                code="NEWS_SOURCE_DOWN",
                message="safe fixture failure",
                retriable=True,
            ),
        )


class AfterCutoffNewsProviders(NewsProviders):
    def documents(self) -> tuple[NewsDocument, ...]:
        return tuple(
            document.model_copy(
                update={
                    "published_at": NOW + timedelta(minutes=1),
                    "source_observed_at": NOW + timedelta(minutes=1),
                }
            )
            for document in super().documents()
        )


async def setup_rank_state(
    tmp_path: Path,
) -> tuple[
    SQLiteDatabase,
    SQLiteOrchestrationRepository,
    MarketCollectionContext,
    SQLiteMarketSnapshotRepository,
    tuple[UUID, ...],
]:
    database = SQLiteDatabase(tmp_path / "candidate-tool.db")
    database.initialize()
    orchestration = SQLiteOrchestrationRepository(database)
    task = TaskRecord(task_id=uuid4(), role="A1", scope="data")
    snapshot = RunSnapshot(
        run_id=uuid4(),
        deadline=datetime.now(UTC) + timedelta(minutes=30),
        tasks=(task,),
    )
    orchestration.save(snapshot, -1, "created")
    TaskCoordinator(orchestration, snapshot.run_id).start(
        task.task_id,
        attempt=1,
        worker_id="worker-a1",
        lease_expires_at=NOW + timedelta(minutes=5),
        now=NOW,
    )
    run = AnalysisRun.create_live(NOW - timedelta(minutes=1), snapshot.run_id)
    context = MarketCollectionContext(
        run=run,
        task_id=task.task_id,
        attempt=1,
        worker_id="worker-a1",
        orchestration=orchestration,
        committer=AtomicArtifactCommitter(orchestration, run.run_id),
    )
    snapshots = SQLiteMarketSnapshotRepository(database)
    await CollectMarketService(
        cast(MarketDataPort, MarketProvider()), mode=AnalysisMode.LIVE
    ).collect_core_and_persist(context=context, locked_at=NOW, max_skew_seconds=10)
    state = orchestration.load(run.run_id)
    assert state is not None
    artifact_ids = tuple(item.artifact_id for item in state.artifacts)
    return database, orchestration, context, snapshots, artifact_ids


@pytest.mark.asyncio
async def test_rank_candidates_matches_existing_algorithm_and_persists_batch(
    tmp_path: Path,
) -> None:
    database, orchestration, context, snapshots, artifact_ids = await setup_rank_state(
        tmp_path
    )
    service = RankSectorCandidatesService(
        snapshots=snapshots,
        orchestration=orchestration,
        committer=context.committer,
    )

    batch = service.rank_market(
        task_id=context.task_id,
        attempt=context.attempt,
        worker_id=context.worker_id,
        market_artifact_ids=artifact_ids,
        limit=4,
        now=NOW,
    )

    industry = snapshots.get(context.run.run_id, SectorKind.INDUSTRY)
    concept = snapshots.get(context.run.run_id, SectorKind.CONCEPT)
    assert industry is not None and concept is not None
    expected = select_market_precandidates(industry, concept, 4)
    assert batch.candidates == expected
    assert SQLiteCandidateBatchRepository(database).get(batch.batch_id) == batch
    state = orchestration.load(context.run.run_id)
    assert state is not None
    assert state.artifacts[-1].reference == f"candidate-batch:{batch.batch_id}"


@pytest.mark.asyncio
async def test_new_ranking_input_keeps_previous_candidate_batch_immutable(
    tmp_path: Path,
) -> None:
    database, orchestration, context, snapshots, artifact_ids = await setup_rank_state(
        tmp_path
    )
    service = RankSectorCandidatesService(
        snapshots=snapshots,
        orchestration=orchestration,
        committer=context.committer,
    )

    first = service.rank_market(
        task_id=context.task_id,
        attempt=1,
        worker_id=context.worker_id,
        market_artifact_ids=artifact_ids,
        limit=4,
        now=NOW,
    )
    second = service.rank_market(
        task_id=context.task_id,
        attempt=1,
        worker_id=context.worker_id,
        market_artifact_ids=artifact_ids,
        limit=2,
        now=NOW,
    )

    reader = SQLiteCandidateBatchRepository(database)
    assert first.batch_id != second.batch_id
    stored_first = reader.get(first.batch_id)
    stored_second = reader.get(second.batch_id)
    assert stored_first is not None and stored_second is not None
    assert len(stored_first.candidates) == 4
    assert len(stored_second.candidates) == 2


@pytest.mark.asyncio
async def test_budgeted_rank_tool_replays_batch_without_recomputing_or_accepting_scores(
    tmp_path: Path,
) -> None:
    from sector_pulse.application.orchestration.tool_budget import SharedToolBudget
    from sector_pulse.infrastructure.agents.candidate_tools import RankSectorCandidatesTool
    from sector_pulse.infrastructure.agents.tool_adapter import BudgetedTool

    database, orchestration, context, snapshots, artifact_ids = await setup_rank_state(
        tmp_path
    )
    batches = SQLiteCandidateBatchRepository(database)
    inner = RankSectorCandidatesTool(
        RankSectorCandidatesService(
            snapshots=snapshots,
            orchestration=orchestration,
            committer=context.committer,
        ),
        batches=batches,
        task_id=context.task_id,
        attempt=context.attempt,
        worker_id=context.worker_id,
        candidate_limit=4,
        clock=lambda: NOW,
    )
    tool = BudgetedTool(
        inner,
        SharedToolBudget(orchestration, context.run.run_id),
        task_id=context.task_id,
        attempt=context.attempt,
        reserved_cny=Decimal("0"),
    )
    payload = {"market_artifact_refs": [str(value) for value in artifact_ids]}

    first = await tool.run(**payload)
    replay = await tool.run(**payload)
    rejected = await tool.run(**payload, scores={"INDUSTRY-1": "999"})

    assert first.success and replay.success
    assert first.content == replay.content
    assert not rejected.success
    state = orchestration.load(context.run.run_id)
    assert state is not None
    assert len([item for item in state.artifacts if item.kind == "candidate_batch"]) == 1
    assert state.ledger.tool_calls == 2


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_postgres_candidate_batch_is_versioned_and_atomic() -> None:
    import os

    from sector_pulse.application.orchestration.data_tools import InspectDataQualityService
    from sector_pulse.application.orchestration.news_tools import (
        CollectInitialNewsService,
        NewsCollectionLimits,
        NewsCollectionReason,
    )
    from sector_pulse.application.orchestration.proposal_tools import (
        ProposalExplanation,
        ProposeCandidatesService,
    )
    from sector_pulse.domain.market.quality import QualityThresholds
    from sector_pulse.domain.news.news_retrieval import SectorEntityConfig
    from sector_pulse.infrastructure.agents.data_tools import InspectDataQualityTool
    from sector_pulse.storage.postgres.database import PostgresDatabase
    from sector_pulse.storage.postgres.market.candidate_batch_repository import (
        PostgresCandidateBatchRepository,
    )
    from sector_pulse.storage.postgres.market.candidate_proposal_repository import (
        PostgresCandidateProposalRepository,
    )
    from sector_pulse.storage.postgres.market.market_snapshot_repository import (
        PostgresMarketSnapshotRepository,
    )
    from sector_pulse.storage.postgres.news.news_batch_repository import (
        PostgresNewsBatchRepository,
    )
    from sector_pulse.storage.postgres.news.news_repository import PostgresNewsRepository
    from sector_pulse.storage.postgres.news.news_retrieval_repository import (
        PostgresNewsRetrievalRepository,
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
    orchestration = PostgresOrchestrationRepository(database)
    snapshots = PostgresMarketSnapshotRepository(database)
    now = datetime.now(UTC)
    task = TaskRecord(task_id=uuid4(), role="A1", scope="data")
    state = RunSnapshot(
        run_id=uuid4(),
        deadline=now + timedelta(minutes=10),
        tasks=(task,),
    )
    orchestration.save(state, -1, "created")
    TaskCoordinator(orchestration, state.run_id).start(
        task.task_id,
        attempt=1,
        worker_id="worker-a1",
        lease_expires_at=now + timedelta(minutes=5),
        now=now,
    )
    run = AnalysisRun.create_live(NOW - timedelta(minutes=1), state.run_id)
    context = MarketCollectionContext(
        run=run,
        task_id=task.task_id,
        attempt=1,
        worker_id="worker-a1",
        orchestration=orchestration,
        committer=AtomicArtifactCommitter(orchestration, run.run_id),
    )
    batch_ids: list[UUID] = []
    news_batch_id = None
    news_document_ids: tuple[str, ...] = ()
    news_event_ids: tuple[str, ...] = ()
    proposal_id: UUID | None = None
    try:
        await CollectMarketService(
            cast(MarketDataPort, MarketProvider()), mode=AnalysisMode.LIVE
        ).collect_core_and_persist(context=context, locked_at=now, max_skew_seconds=60)
        current = orchestration.load(run.run_id)
        assert current is not None
        market_refs = tuple(
            item.artifact_id for item in current.artifacts if item.kind == "market_snapshot"
        )
        quality_tool = InspectDataQualityTool(
            InspectDataQualityService(
                QualityThresholds(min_industry_count=1, min_concept_count=1)
            ),
            context=context,
            snapshots=snapshots,
            clock=lambda: now,
        )
        for artifact_id in market_refs:
            assert (await quality_tool.run(artifact_ref=str(artifact_id))).success
        current = orchestration.load(run.run_id)
        assert current is not None
        assert len([item for item in current.artifacts if item.kind == "data_quality"]) == 2
        batch = RankSectorCandidatesService(
            snapshots=snapshots,
            orchestration=orchestration,
            committer=context.committer,
        ).rank_market(
            task_id=task.task_id,
            attempt=1,
            worker_id="worker-a1",
            market_artifact_ids=market_refs,
            limit=4,
            now=now,
        )
        batch_ids.append(batch.batch_id)
        assert PostgresCandidateBatchRepository(database).get(batch.batch_id) == batch
        current = orchestration.load(run.run_id)
        assert current is not None
        candidate_artifact = next(
            item
            for item in current.artifacts
            if item.reference == f"candidate-batch:{batch.batch_id}"
        )
        providers = NewsProviders(suffix=f"-{run.run_id}")
        news_batch = await CollectInitialNewsService(
            constituents=cast(SectorConstituentPort, ConstituentsProvider()),
            global_news=cast(GlobalNewsDiscoveryPort, providers),
            keyword_news=cast(KeywordNewsSearchPort, providers),
            disclosure_news=cast(DisclosureSearchPort, providers),
            entity_config=SectorEntityConfig(
                version="postgres-test-v1",
                aliases={},
                industry_terms={},
                ambiguous_terms=(),
            ),
            snapshots=snapshots,
            candidate_batches=PostgresCandidateBatchRepository(database),
            orchestration=orchestration,
            committer=context.committer,
            limits=NewsCollectionLimits(
                lookback_hours=6,
                keyword_budget=2,
                disclosure_code_budget=1,
                max_retries=0,
            ),
        ).collect(
            task_id=task.task_id,
            attempt=1,
            worker_id="worker-a1",
            candidate_artifact_id=candidate_artifact.artifact_id,
            reason=NewsCollectionReason.INITIAL_CANDIDATES,
            now=now,
            retry_backoff=lambda _attempt: 0,
        )
        news_batch_id = news_batch.batch_id
        news_document_ids = news_batch.document_ids
        news_event_ids = news_batch.event_ids
        assert PostgresNewsBatchRepository(database).get(news_batch.batch_id) == news_batch
        assert {
            item.source_id: (item.call_count, item.result_count)
            for item in PostgresNewsRetrievalRepository(database).list_source_metrics(
                run.run_id
            )
        } == {"cls": (1, 2), "cninfo": (1, 0), "eastmoney": (2, 0)}
        current = orchestration.load(run.run_id)
        assert current is not None
        news_artifact = next(
            item
            for item in current.artifacts
            if item.reference == f"news-batch:{news_batch.batch_id}"
        )
        news_repository = PostgresNewsRepository(database)
        enriched = RankSectorCandidatesService(
            snapshots=snapshots,
            news_batches=PostgresNewsBatchRepository(database),
            news=news_repository,
            orchestration=orchestration,
            committer=context.committer,
        ).rank_news_enriched(
            task_id=task.task_id,
            attempt=1,
            worker_id="worker-a1",
            market_artifact_ids=market_refs,
            news_artifact_id=news_artifact.artifact_id,
            limit=4,
            now=now,
        )
        batch_ids.append(enriched.batch_id)
        assert PostgresCandidateBatchRepository(database).get(enriched.batch_id) == enriched
        assert enriched.candidates == select_candidates(
            snapshots.get(run.run_id, SectorKind.INDUSTRY),
            snapshots.get(run.run_id, SectorKind.CONCEPT),
            news_repository.get_events(news_batch.event_ids),
            4,
        )
        current = orchestration.load(run.run_id)
        assert current is not None
        enriched_artifact = next(
            item
            for item in current.artifacts
            if item.reference == f"candidate-batch:{enriched.batch_id}"
        )
        proposal = ProposeCandidatesService(
            candidate_batches=PostgresCandidateBatchRepository(database),
            proposals=PostgresCandidateProposalRepository(database),
            orchestration=orchestration,
            committer=context.committer,
        ).propose(
            task_id=task.task_id,
            attempt=1,
            worker_id="worker-a1",
            candidate_artifact_id=enriched_artifact.artifact_id,
            explanations=tuple(
                ProposalExplanation(
                    sector_id=item.provider_sector_id,
                    explanation=f"research {item.name}",
                )
                for item in enriched.candidates[:3]
            ),
            now=now,
        )
        proposal_id = proposal.proposal_id
        assert (
            PostgresCandidateProposalRepository(database).get(proposal.proposal_id)
            == proposal
        )
        with database.start().connect() as connection:
            assert connection.execute(
                text(
                    "SELECT COUNT(*) FROM data_run_candidate_selections "
                    "WHERE run_id=:run_id"
                ),
                {"run_id": str(run.run_id)},
            ).scalar_one() == 0
    finally:
        with database.start().begin() as connection:
            if proposal_id is not None:
                connection.execute(
                    text("DELETE FROM candidate_proposals WHERE proposal_id=:proposal_id"),
                    {"proposal_id": str(proposal_id)},
                )
            if news_batch_id is not None:
                connection.execute(
                    text("DELETE FROM news_batches WHERE batch_id=:batch_id"),
                    {"batch_id": str(news_batch_id)},
                )
            for batch_id in reversed(batch_ids):
                connection.execute(
                    text("DELETE FROM candidate_batches WHERE batch_id=:batch_id"),
                    {"batch_id": str(batch_id)},
                )
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
            for event_id in news_event_ids:
                connection.execute(
                    text("DELETE FROM news_events WHERE event_id=:event_id"),
                    {"event_id": event_id},
                )
            for document_id in news_document_ids:
                connection.execute(
                    text("DELETE FROM news_documents WHERE document_id=:document_id"),
                    {"document_id": document_id},
                )
        database.close()


@pytest.mark.asyncio
async def test_initial_news_collection_is_bounded_deduplicated_and_atomic(
    tmp_path: Path,
) -> None:
    from sector_pulse.application.orchestration.news_tools import (
        CollectInitialNewsService,
        NewsCollectionLimits,
        NewsCollectionReason,
    )
    from sector_pulse.application.orchestration.tool_budget import SharedToolBudget
    from sector_pulse.domain.news.news_retrieval import SectorEntityConfig
    from sector_pulse.infrastructure.agents.candidate_tools import RankSectorCandidatesTool
    from sector_pulse.infrastructure.agents.news_tools import CollectInitialNewsTool
    from sector_pulse.infrastructure.agents.tool_adapter import BudgetedTool
    from sector_pulse.storage.sqlite.news.news_batch_repository import (
        SQLiteNewsBatchRepository,
    )
    from sector_pulse.storage.sqlite.news.news_repository import SQLiteNewsRepository
    from sector_pulse.storage.sqlite.news.news_retrieval_repository import (
        SQLiteNewsRetrievalRepository,
    )

    database, orchestration, context, snapshots, market_refs = await setup_rank_state(
        tmp_path
    )
    candidate_batch = RankSectorCandidatesService(
        snapshots=snapshots,
        orchestration=orchestration,
        committer=context.committer,
    ).rank_market(
        task_id=context.task_id,
        attempt=1,
        worker_id=context.worker_id,
        market_artifact_ids=market_refs,
        limit=2,
        now=NOW,
    )
    state = orchestration.load(context.run.run_id)
    assert state is not None
    candidate_artifact = next(
        item
        for item in state.artifacts
        if item.reference == f"candidate-batch:{candidate_batch.batch_id}"
    )
    providers = NewsProviders()
    service = CollectInitialNewsService(
        constituents=cast(SectorConstituentPort, ConstituentsProvider()),
        global_news=cast(GlobalNewsDiscoveryPort, providers),
        keyword_news=cast(KeywordNewsSearchPort, providers),
        disclosure_news=cast(DisclosureSearchPort, providers),
        entity_config=SectorEntityConfig(
            version="test-v1", aliases={}, industry_terms={}, ambiguous_terms=()
        ),
        snapshots=snapshots,
        candidate_batches=SQLiteCandidateBatchRepository(database),
        orchestration=orchestration,
        committer=context.committer,
        limits=NewsCollectionLimits(
            lookback_hours=6,
            keyword_budget=2,
            disclosure_code_budget=1,
            max_retries=0,
        ),
    )

    inner = CollectInitialNewsTool(
        service,
        batches=SQLiteNewsBatchRepository(database),
        task_id=context.task_id,
        attempt=1,
        worker_id=context.worker_id,
        clock=lambda: NOW,
        retry_backoff=lambda _attempt: 0,
    )
    tool = BudgetedTool(
        inner,
        SharedToolBudget(orchestration, context.run.run_id),
        task_id=context.task_id,
        attempt=1,
        reserved_cny=Decimal("0"),
    )
    payload = {
        "candidate_artifact_ref": str(candidate_artifact.artifact_id),
        "reason": NewsCollectionReason.INITIAL_CANDIDATES.value,
    }

    first = await tool.run(**payload)
    replay = await tool.run(**payload)
    rejected_reason = await tool.run(
        candidate_artifact_ref=str(candidate_artifact.artifact_id),
        reason="ARBITRARY_MODEL_REASON",
    )
    assert first.success and replay.success
    assert not rejected_reason.success
    assert first.content == replay.content
    result_reference = first.metadata["result_reference"]
    assert isinstance(result_reference, str)
    batch = SQLiteNewsBatchRepository(database).get(
        UUID(result_reference.removeprefix("news-batch:"))
    )
    assert batch is not None

    assert providers.global_calls == 1
    assert providers.keyword_calls == 2
    assert providers.disclosure_calls == 1
    assert batch.document_count == 2
    assert batch.event_count == 1
    assert batch.link_count >= 1
    assert {item.source_id: item.call_count for item in batch.source_metrics} == {
        "cls": 1,
        "cninfo": 1,
        "eastmoney": 2,
    }
    assert {item.source_id: item.result_count for item in batch.source_metrics} == {
        "cls": 2,
        "cninfo": 0,
        "eastmoney": 0,
    }
    content = json.loads(first.content)
    assert content["summary"]["sources"]["cls"]["result_count"] == 2
    assert SQLiteNewsBatchRepository(database).get(batch.batch_id) == batch
    news_repository = SQLiteNewsRepository(database)
    assert len(news_repository.get_documents(batch.document_ids)) == 2
    assert len(SQLiteNewsRetrievalRepository(database).list_links(context.run.run_id)) >= 1
    current = orchestration.load(context.run.run_id)
    assert current is not None
    assert current.artifacts[-1].reference == f"news-batch:{batch.batch_id}"
    ranking_tool = BudgetedTool(
        RankSectorCandidatesTool(
            RankSectorCandidatesService(
                snapshots=snapshots,
                news_batches=SQLiteNewsBatchRepository(database),
                news=news_repository,
                orchestration=orchestration,
                committer=context.committer,
            ),
            batches=SQLiteCandidateBatchRepository(database),
            task_id=context.task_id,
            attempt=1,
            worker_id=context.worker_id,
            candidate_limit=2,
            clock=lambda: NOW,
        ),
        SharedToolBudget(orchestration, context.run.run_id),
        task_id=context.task_id,
        attempt=1,
        reserved_cny=Decimal("0"),
    )
    enriched_result = await ranking_tool.run(
        market_artifact_refs=[str(value) for value in market_refs],
        news_artifact_ref=str(current.artifacts[-1].artifact_id),
    )
    enriched_replay = await ranking_tool.run(
        market_artifact_refs=[str(value) for value in market_refs],
        news_artifact_ref=str(current.artifacts[-1].artifact_id),
    )
    assert enriched_result.success and enriched_replay.success
    assert enriched_result.content == enriched_replay.content
    enriched_reference = enriched_result.metadata["result_reference"]
    assert isinstance(enriched_reference, str)
    enriched = SQLiteCandidateBatchRepository(database).get(
        UUID(enriched_reference.removeprefix("candidate-batch:"))
    )
    assert enriched is not None
    industry = snapshots.get(context.run.run_id, SectorKind.INDUSTRY)
    concept = snapshots.get(context.run.run_id, SectorKind.CONCEPT)
    assert industry is not None and concept is not None
    assert enriched.candidates == select_candidates(
        industry,
        concept,
        news_repository.get_events(batch.event_ids),
        2,
    )
    assert enriched.ranking_stage is CandidateRankingStage.NEWS_ENRICHED
    assert enriched.input_fingerprint != candidate_batch.input_fingerprint
    calls_before_recovery = (
        providers.global_calls,
        providers.keyword_calls,
        providers.disclosure_calls,
    )
    TaskCoordinator(orchestration, context.run.run_id).recover(
        context.task_id,
        expected_attempt=1,
        worker_id="worker-a1-recovered",
        lease_expires_at=NOW + timedelta(minutes=10),
        now=NOW + timedelta(minutes=6),
    )
    with pytest.raises(RuntimeError, match="attempt|owner"):
        await service.collect(
            task_id=context.task_id,
            attempt=1,
            worker_id=context.worker_id,
            candidate_artifact_id=candidate_artifact.artifact_id,
            reason=NewsCollectionReason.INITIAL_CANDIDATES,
            now=NOW + timedelta(minutes=7),
        )
    assert (
        providers.global_calls,
        providers.keyword_calls,
        providers.disclosure_calls,
    ) == calls_before_recovery


@pytest.mark.asyncio
async def test_news_batch_reports_actual_retry_calls_and_degraded_source(
    tmp_path: Path,
) -> None:
    from sector_pulse.application.orchestration.news_tools import (
        CollectInitialNewsService,
        NewsCollectionLimits,
        NewsCollectionReason,
    )
    from sector_pulse.domain.market.quality import QualityStatus
    from sector_pulse.domain.news.news_retrieval import SectorEntityConfig

    database, orchestration, context, snapshots, market_refs = await setup_rank_state(
        tmp_path
    )
    candidate_batch = RankSectorCandidatesService(
        snapshots=snapshots,
        orchestration=orchestration,
        committer=context.committer,
    ).rank_market(
        task_id=context.task_id,
        attempt=1,
        worker_id=context.worker_id,
        market_artifact_ids=market_refs,
        limit=1,
        now=NOW,
    )
    state = orchestration.load(context.run.run_id)
    assert state is not None
    candidate_artifact = next(
        item
        for item in state.artifacts
        if item.reference == f"candidate-batch:{candidate_batch.batch_id}"
    )
    providers = RetryingNewsProviders()
    service = CollectInitialNewsService(
        constituents=cast(SectorConstituentPort, ConstituentsProvider()),
        global_news=cast(GlobalNewsDiscoveryPort, providers),
        keyword_news=cast(KeywordNewsSearchPort, providers),
        disclosure_news=cast(DisclosureSearchPort, providers),
        entity_config=SectorEntityConfig(
            version="test-v1", aliases={}, industry_terms={}, ambiguous_terms=()
        ),
        snapshots=snapshots,
        candidate_batches=SQLiteCandidateBatchRepository(database),
        orchestration=orchestration,
        committer=context.committer,
        limits=NewsCollectionLimits(
            lookback_hours=6,
            keyword_budget=1,
            disclosure_code_budget=0,
            max_retries=1,
        ),
    )

    batch = await service.collect(
        task_id=context.task_id,
        attempt=1,
        worker_id=context.worker_id,
        candidate_artifact_id=candidate_artifact.artifact_id,
        reason=NewsCollectionReason.INITIAL_CANDIDATES,
        now=NOW,
        retry_backoff=lambda _attempt: 0,
    )

    metric = next(item for item in batch.source_metrics if item.source_id == "eastmoney")
    assert providers.keyword_calls == 2
    assert metric.call_count == 2
    assert metric.retry_count == 1
    assert metric.result_count == 0
    assert metric.status is DataStatus.FAILED
    assert metric.error_code == "NEWS_SOURCE_DOWN"
    assert batch.quality.status is QualityStatus.DEGRADED


@pytest.mark.asyncio
async def test_news_after_locked_cutoff_is_retained_but_blocked_from_evidence(
    tmp_path: Path,
) -> None:
    from sector_pulse.application.orchestration.news_tools import (
        CollectInitialNewsService,
        NewsCollectionLimits,
        NewsCollectionReason,
    )
    from sector_pulse.domain.market.quality import QualityStatus
    from sector_pulse.domain.news.news_retrieval import SectorEntityConfig

    database, orchestration, context, snapshots, market_refs = await setup_rank_state(
        tmp_path
    )
    candidate_batch = RankSectorCandidatesService(
        snapshots=snapshots,
        orchestration=orchestration,
        committer=context.committer,
    ).rank_market(
        task_id=context.task_id,
        attempt=1,
        worker_id=context.worker_id,
        market_artifact_ids=market_refs,
        limit=1,
        now=NOW,
    )
    state = orchestration.load(context.run.run_id)
    assert state is not None
    candidate_artifact = next(
        item
        for item in state.artifacts
        if item.reference == f"candidate-batch:{candidate_batch.batch_id}"
    )
    providers = AfterCutoffNewsProviders()
    service = CollectInitialNewsService(
        constituents=cast(SectorConstituentPort, ConstituentsProvider()),
        global_news=cast(GlobalNewsDiscoveryPort, providers),
        keyword_news=cast(KeywordNewsSearchPort, providers),
        disclosure_news=cast(DisclosureSearchPort, providers),
        entity_config=SectorEntityConfig(
            version="test-v1", aliases={}, industry_terms={}, ambiguous_terms=()
        ),
        snapshots=snapshots,
        candidate_batches=SQLiteCandidateBatchRepository(database),
        orchestration=orchestration,
        committer=context.committer,
        limits=NewsCollectionLimits(
            lookback_hours=6,
            keyword_budget=0,
            disclosure_code_budget=0,
            max_retries=0,
        ),
    )

    batch = await service.collect(
        task_id=context.task_id,
        attempt=1,
        worker_id=context.worker_id,
        candidate_artifact_id=candidate_artifact.artifact_id,
        reason=NewsCollectionReason.INITIAL_CANDIDATES,
        now=NOW,
    )

    assert batch.document_count == 2
    assert batch.quality.excluded_after_cutoff_count == 2
    assert batch.quality.citation_eligible_count == 0
    assert batch.quality.status is QualityStatus.BLOCKED
    assert batch.quality.blocking_reasons == ("CUTOFF_VIOLATION",)


@pytest.mark.asyncio
async def test_candidate_proposal_copies_scores_without_confirming_selection(
    tmp_path: Path,
) -> None:
    from sector_pulse.application.data_runs.candidate_selection_service import (
        CandidateSelectionRequired,
        CandidateSelectionService,
    )
    from sector_pulse.application.orchestration.proposal_tools import (
        ProposalExplanation,
        ProposeCandidatesService,
    )
    from sector_pulse.application.orchestration.referenced_context import (
        ContextReferenceRequest,
        ReferencedContextReader,
    )
    from sector_pulse.application.orchestration.tool_budget import SharedToolBudget
    from sector_pulse.domain.runs.real_data_run import (
        RealDataCandidate,
        RealDataRun,
        RealDataRunRequest,
    )
    from sector_pulse.infrastructure.agents.proposal_tools import ProposeCandidatesTool
    from sector_pulse.infrastructure.agents.tool_adapter import BudgetedTool
    from sector_pulse.storage.sqlite.market.candidate_proposal_repository import (
        SQLiteCandidateProposalRepository,
    )
    from sector_pulse.storage.sqlite.market.candidate_selection_repository import (
        SQLiteCandidateSelectionRepository,
    )
    from sector_pulse.storage.sqlite.runs.real_data_run_repository import (
        SQLiteRealDataRunRepository,
    )

    database, orchestration, context, snapshots, market_refs = await setup_rank_state(
        tmp_path
    )
    batch = RankSectorCandidatesService(
        snapshots=snapshots,
        orchestration=orchestration,
        committer=context.committer,
    ).rank_market(
        task_id=context.task_id,
        attempt=1,
        worker_id=context.worker_id,
        market_artifact_ids=market_refs,
        limit=4,
        now=NOW,
    )
    state = orchestration.load(context.run.run_id)
    assert state is not None
    batch_artifact = next(
        item for item in state.artifacts if item.reference == f"candidate-batch:{batch.batch_id}"
    )
    proposal_repository = SQLiteCandidateProposalRepository(database)
    service = ProposeCandidatesService(
        candidate_batches=SQLiteCandidateBatchRepository(database),
        proposals=proposal_repository,
        orchestration=orchestration,
        committer=context.committer,
    )
    tool = BudgetedTool(
        ProposeCandidatesTool(
            service,
            proposals=proposal_repository,
            task_id=context.task_id,
            attempt=1,
            worker_id=context.worker_id,
            clock=lambda: NOW,
        ),
        SharedToolBudget(orchestration, context.run.run_id),
        task_id=context.task_id,
        attempt=1,
        reserved_cny=Decimal("0"),
    )
    chosen = (batch.candidates[2], batch.candidates[0], batch.candidates[1])
    payload = {
        "candidate_artifact_ref": str(batch_artifact.artifact_id),
        "proposals": [
            {"sector_id": item.provider_sector_id, "explanation": f"研究 {item.name}"}
            for item in chosen
        ],
    }

    first = await tool.run(**payload)
    replay = await tool.run(**payload)
    rejected_score = await tool.run(
        candidate_artifact_ref=str(batch_artifact.artifact_id),
        proposals=[
            {
                "sector_id": item.provider_sector_id,
                "explanation": f"研究 {item.name}",
                "score": "999",
            }
            for item in chosen
        ],
    )

    assert first.success and replay.success
    assert first.content == replay.content
    assert not rejected_score.success
    reference = first.metadata["result_reference"]
    assert isinstance(reference, str)
    proposal = proposal_repository.get(UUID(reference.removeprefix("candidate-proposal:")))
    assert proposal is not None
    expected = tuple(sorted(chosen, key=lambda item: item.rank))
    assert tuple(item.provider_sector_id for item in proposal.items) == tuple(
        item.provider_sector_id for item in expected
    )
    assert tuple(item.score for item in proposal.items) == tuple(
        item.score for item in expected
    )
    assert all(item.explanation.startswith("研究 ") for item in proposal.items)
    current = orchestration.load(context.run.run_id)
    assert current is not None
    assert len([item for item in current.artifacts if item.kind == "candidate_proposal"]) == 1

    real_runs = SQLiteRealDataRunRepository(database)
    real_runs.insert(
        RealDataRun(
            run_id=context.run.run_id,
            provider="fixture",
            request=RealDataRunRequest(mode="intraday", requested_at=NOW),
        )
    )
    real_runs.save_candidates(
        context.run.run_id,
        tuple(
            RealDataCandidate(
                sector_id=item.provider_sector_id,
                sector_kind=item.kind,
                rank=item.rank,
                score=item.score,
                reasons=item.reasons,
            )
            for item in batch.candidates
        ),
    )
    selections = SQLiteCandidateSelectionRepository(database)
    with pytest.raises(CandidateSelectionRequired):
        CandidateSelectionService(real_runs, selections).require_confirmed(
            context.run.run_id
        )
    assert selections.latest(context.run.run_id) is None
    request = ContextReferenceRequest(
        artifact_ids=(*market_refs, batch_artifact.artifact_id, current.artifacts[-1].artifact_id),
        selection_version=None,
    )
    reader = ReferencedContextReader(orchestration, selections, context.run.run_id)
    referenced = reader.read(request)
    assert tuple(item.artifact_id for item in referenced.artifacts) == request.artifact_ids
    assert referenced.selection is None

    confirmed = CandidateSelectionService(real_runs, selections, clock=lambda: NOW).confirm(
        context.run.run_id,
        tuple(item.provider_sector_id for item in expected),
        expected_version=0,
    )
    confirmed_request = request.model_copy(update={"selection_version": 1})
    assert reader.read(confirmed_request).selection == confirmed
    assert reader.read(confirmed_request) == reader.read(confirmed_request)

    with pytest.raises(ValueError, match="between 3 and 12"):
        service.propose(
            task_id=context.task_id,
            attempt=1,
            worker_id=context.worker_id,
            candidate_artifact_id=batch_artifact.artifact_id,
            explanations=(
                ProposalExplanation(
                    sector_id=batch.candidates[0].provider_sector_id,
                    explanation="too few",
                ),
            ),
            now=NOW,
        )
    with pytest.raises(ValueError, match="unique"):
        service.propose(
            task_id=context.task_id,
            attempt=1,
            worker_id=context.worker_id,
            candidate_artifact_id=batch_artifact.artifact_id,
            explanations=tuple(
                ProposalExplanation(
                    sector_id=batch.candidates[0].provider_sector_id,
                    explanation=f"duplicate {index}",
                )
                for index in range(3)
            ),
            now=NOW,
        )
    with pytest.raises(ValueError, match="unknown"):
        service.propose(
            task_id=context.task_id,
            attempt=1,
            worker_id=context.worker_id,
            candidate_artifact_id=batch_artifact.artifact_id,
            explanations=(
                ProposalExplanation(sector_id="UNKNOWN", explanation="unknown"),
                ProposalExplanation(
                    sector_id=batch.candidates[0].provider_sector_id,
                    explanation="known one",
                ),
                ProposalExplanation(
                    sector_id=batch.candidates[1].provider_sector_id,
                    explanation="known two",
                ),
            ),
            now=NOW,
        )


@pytest.mark.asyncio
async def test_real_framework_a0_delegates_a1_through_t01_to_t05(tmp_path: Path) -> None:
    from aidynamic_agent.core.message import FinishReason, TextBlock, ToolUseBlock
    from aidynamic_agent.llm.base import LLMResponse
    from aidynamic_agent.tools.base import ToolResult
    from aidynamic_agent.tools.builtins.skill import SkillTool
    from sector_pulse.application.orchestration.data_tools import InspectDataQualityService
    from sector_pulse.application.orchestration.news_tools import (
        CollectInitialNewsService,
        NewsCollectionLimits,
    )
    from sector_pulse.application.orchestration.proposal_tools import ProposeCandidatesService
    from sector_pulse.domain.market.quality import QualityThresholds
    from sector_pulse.domain.news.news_retrieval import SectorEntityConfig
    from sector_pulse.infrastructure.agents.candidate_tools import RankSectorCandidatesTool
    from sector_pulse.infrastructure.agents.data_tools import (
        CollectMarketTool,
        InspectDataQualityTool,
    )
    from sector_pulse.infrastructure.agents.delegation import RestrictedDelegateTool
    from sector_pulse.infrastructure.agents.news_tools import CollectInitialNewsTool
    from sector_pulse.infrastructure.agents.proposal_tools import ProposeCandidatesTool
    from sector_pulse.infrastructure.agents.roles import (
        AgentRole,
        AgentToolContext,
        RoleAgentFactory,
        RoleRuntime,
    )
    from sector_pulse.infrastructure.agents.skills import AllowedSkillManager
    from sector_pulse.storage.sqlite.market.candidate_proposal_repository import (
        SQLiteCandidateProposalRepository,
    )
    from sector_pulse.storage.sqlite.news.news_batch_repository import (
        SQLiteNewsBatchRepository,
    )
    from sector_pulse.storage.sqlite.news.news_repository import SQLiteNewsRepository

    database = SQLiteDatabase(tmp_path / "a1-framework.db")
    database.initialize()
    orchestration = SQLiteOrchestrationRepository(database)
    wall_now = datetime.now(UTC)
    root = TaskRecord(task_id=uuid4(), role="A0", scope="run")
    child = TaskRecord(
        task_id=uuid4(), parent_id=root.task_id, role="A1", scope="data"
    )
    snapshot = RunSnapshot(
        run_id=uuid4(),
        deadline=wall_now + timedelta(minutes=10),
        tasks=(root, child),
    )
    orchestration.save(snapshot, -1, "created")
    coordinator = TaskCoordinator(orchestration, snapshot.run_id)
    lease = wall_now + timedelta(minutes=5)
    coordinator.start(root.task_id, attempt=1, worker_id="a0-worker", lease_expires_at=lease)
    coordinator.start(child.task_id, attempt=1, worker_id="a1-worker", lease_expires_at=lease)
    snapshots = SQLiteMarketSnapshotRepository(database)
    candidate_batches = SQLiteCandidateBatchRepository(database)
    news_batches = SQLiteNewsBatchRepository(database)
    news_repository = SQLiteNewsRepository(database)
    proposal_repository = SQLiteCandidateProposalRepository(database)
    committer = AtomicArtifactCommitter(orchestration, snapshot.run_id)
    market_context = MarketCollectionContext(
        run=AnalysisRun.create_live(NOW - timedelta(minutes=1), snapshot.run_id),
        task_id=child.task_id,
        attempt=1,
        worker_id="a1-worker",
        orchestration=orchestration,
        committer=committer,
    )
    news_providers = NewsProviders(suffix=f"-{snapshot.run_id}")

    def build_tool(name: str, context: AgentToolContext):
        if name == "collect_market":
            return CollectMarketTool(
                CollectMarketService(
                    cast(MarketDataPort, MarketProvider()), mode=AnalysisMode.LIVE
                ),
                context=market_context,
                snapshots=snapshots,
                clock=lambda: wall_now,
            )
        if name == "inspect_data_quality":
            return InspectDataQualityTool(
                InspectDataQualityService(
                    QualityThresholds(min_industry_count=1, min_concept_count=1)
                ),
                context=market_context,
                snapshots=snapshots,
                clock=lambda: wall_now,
            )
        candidate_service = RankSectorCandidatesService(
            snapshots=snapshots,
            news_batches=news_batches,
            news=news_repository,
            orchestration=orchestration,
            committer=committer,
        )
        if name == "rank_sector_candidates":
            return RankSectorCandidatesTool(
                candidate_service,
                batches=candidate_batches,
                task_id=context.task_id,
                attempt=context.attempt,
                worker_id=context.worker_id,
                candidate_limit=4,
                clock=lambda: wall_now,
            )
        if name == "collect_initial_news":
            return CollectInitialNewsTool(
                CollectInitialNewsService(
                    constituents=cast(SectorConstituentPort, ConstituentsProvider()),
                    global_news=cast(GlobalNewsDiscoveryPort, news_providers),
                    keyword_news=cast(KeywordNewsSearchPort, news_providers),
                    disclosure_news=cast(DisclosureSearchPort, news_providers),
                    entity_config=SectorEntityConfig(
                        version="trace-v1",
                        aliases={},
                        industry_terms={},
                        ambiguous_terms=(),
                    ),
                    snapshots=snapshots,
                    candidate_batches=candidate_batches,
                    orchestration=orchestration,
                    committer=committer,
                    limits=NewsCollectionLimits(
                        lookback_hours=6,
                        keyword_budget=2,
                        disclosure_code_budget=1,
                        max_retries=0,
                    ),
                ),
                batches=news_batches,
                task_id=context.task_id,
                attempt=context.attempt,
                worker_id=context.worker_id,
                clock=lambda: wall_now,
                retry_backoff=lambda _attempt: 0,
            )
        if name == "propose_candidates":
            return ProposeCandidatesTool(
                ProposeCandidatesService(
                    candidate_batches=candidate_batches,
                    proposals=proposal_repository,
                    orchestration=orchestration,
                    committer=committer,
                ),
                proposals=proposal_repository,
                task_id=context.task_id,
                attempt=context.attempt,
                worker_id=context.worker_id,
                clock=lambda: wall_now,
            )
        if name == "skill":
            return SkillTool()
        raise AssertionError(name)

    class ScriptedEndpoint:
        def __init__(self, role: AgentRole) -> None:
            self.role = role
            self.calls = 0

        async def create(self, *args: object, **kwargs: object) -> LLMResponse:
            del args, kwargs
            self.calls += 1
            if self.role is AgentRole.A0:
                if self.calls == 1:
                    block = ToolUseBlock(
                        tool_call_id="delegate-a1",
                        tool_name="delegate",
                        tool_input={"role": "A1", "goal": "prepare data", "scope": "data"},
                    )
                else:
                    return LLMResponse(
                        content=[TextBlock(text="A1 proposal ready")],
                        model="fixture",
                        stop_reason=FinishReason.END_TURN,
                        usage={"total_tokens": 1},
                    )
            else:
                state = orchestration.load(snapshot.run_id)
                assert state is not None
                market = [item for item in state.artifacts if item.kind == "market_snapshot"]
                candidates = [item for item in state.artifacts if item.kind == "candidate_batch"]
                news = [item for item in state.artifacts if item.kind == "news_batch"]
                if self.calls == 1:
                    block = ToolUseBlock(
                        tool_call_id="skill-a1",
                        tool_name="skill",
                        tool_input={"operation": "load", "name": "data-gap-handling"},
                    )
                elif not market:
                    block = ToolUseBlock(
                        tool_call_id="market-a1",
                        tool_name="collect_market",
                        tool_input={"kinds": ["INDUSTRY", "CONCEPT"]},
                    )
                elif self.calls in (3, 4):
                    block = ToolUseBlock(
                        tool_call_id=f"quality-a1-{self.calls}",
                        tool_name="inspect_data_quality",
                        tool_input={"artifact_ref": str(market[self.calls - 3].artifact_id)},
                    )
                elif not candidates:
                    block = ToolUseBlock(
                        tool_call_id="rank-market-a1",
                        tool_name="rank_sector_candidates",
                        tool_input={
                            "market_artifact_refs": [str(item.artifact_id) for item in market]
                        },
                    )
                elif not news:
                    block = ToolUseBlock(
                        tool_call_id="news-a1",
                        tool_name="collect_initial_news",
                        tool_input={
                            "candidate_artifact_ref": str(candidates[-1].artifact_id),
                            "reason": "INITIAL_CANDIDATES",
                        },
                    )
                elif len(candidates) == 1:
                    block = ToolUseBlock(
                        tool_call_id="rank-news-a1",
                        tool_name="rank_sector_candidates",
                        tool_input={
                            "market_artifact_refs": [str(item.artifact_id) for item in market],
                            "news_artifact_ref": str(news[-1].artifact_id),
                        },
                    )
                elif not any(
                    item.kind == "candidate_proposal" for item in state.artifacts
                ):
                    batch = candidate_batches.get(
                        UUID(candidates[-1].reference.removeprefix("candidate-batch:"))
                    )
                    assert batch is not None
                    block = ToolUseBlock(
                        tool_call_id="proposal-a1",
                        tool_name="propose_candidates",
                        tool_input={
                            "candidate_artifact_ref": str(candidates[-1].artifact_id),
                            "proposals": [
                                {
                                    "sector_id": item.provider_sector_id,
                                    "explanation": f"research {item.name}",
                                }
                                for item in batch.candidates[:3]
                            ],
                        },
                    )
                else:
                    return LLMResponse(
                        content=[TextBlock(text="candidate proposal persisted")],
                        model="fixture",
                        stop_reason=FinishReason.END_TURN,
                        usage={"total_tokens": 1},
                    )
            return LLMResponse(
                content=[block],
                model="fixture",
                stop_reason=FinishReason.TOOL_USE,
                usage={"total_tokens": 1},
            )

    runtimes = {
        role: RoleRuntime(
            provider="fixture", model="fixture", prompt=role.value, pricing=None
        )
        for role in AgentRole
    }
    endpoints: dict[AgentRole, ScriptedEndpoint] = {}
    factory: RoleAgentFactory

    async def dispatch(
        role: str, goal: str, scope: str, artifact_refs: tuple[str, ...]
    ) -> ToolResult:
        del role, scope, artifact_refs
        result = await factory.create(child.task_id, attempt=1).run(goal)
        return ToolResult(
            content=result.text,
            success=result.error is None,
            error=result.error,
            metadata={"result_reference": f"task:{child.task_id}"},
        )

    contextual = {
        name: (lambda context, name=name: build_tool(name, context))
        for name in (
            "collect_market",
            "inspect_data_quality",
            "rank_sector_candidates",
            "collect_initial_news",
            "propose_candidates",
            "skill",
        )
    }
    contextual["delegate"] = lambda context: RestrictedDelegateTool(dispatch)
    factory = RoleAgentFactory(
        repository=orchestration,
        run_id=snapshot.run_id,
        provider_builder=lambda runtime: endpoints.setdefault(
            AgentRole(runtime.prompt), ScriptedEndpoint(AgentRole(runtime.prompt))
        ),
        role_runtimes=runtimes,
        tool_builders={},
        contextual_tool_builders=contextual,
        tool_reserved_cny={name: Decimal("0") for name in contextual},
        skill_managers={
            AgentRole.A1: AllowedSkillManager(
                Path("config/agent-skills"),
                allowed_names=frozenset({"data-gap-handling", "sector-selection"}),
            )
        },
    )

    result = await factory.create(root.task_id, attempt=1).run("prepare candidates")
    assert result.text == "A1 proposal ready"
    state = orchestration.load(snapshot.run_id)
    assert state is not None
    assert [item.kind for item in state.artifacts].count("market_snapshot") == 2
    assert [item.kind for item in state.artifacts].count("data_quality") == 2
    assert [item.kind for item in state.artifacts].count("candidate_batch") == 2
    assert [item.kind for item in state.artifacts].count("news_batch") == 1
    assert [item.kind for item in state.artifacts].count("candidate_proposal") == 1
    assert {item.tool_name for item in state.ledger.tool_invocations} >= {
        "delegate",
        "skill",
        "collect_market",
        "inspect_data_quality",
        "rank_sector_candidates",
        "collect_initial_news",
        "propose_candidates",
    }
    assert all(
        item.task_id == child.task_id and item.attempt == 1 and item.role == "A1"
        for item in state.ledger.tool_invocations
        if item.tool_name != "delegate"
    )
