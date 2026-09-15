import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest


@pytest.mark.asyncio
async def test_t06_failed_search_returns_safe_replayable_failure():
    from sector_pulse.application.orchestration.research_context import (
        BoundSectorResearchContext,
    )
    from sector_pulse.domain.market.market import SectorKind
    from sector_pulse.domain.news.research import ResearchSearchBatch, ResearchSearchStatus
    from sector_pulse.infrastructure.agents.research_tools import SearchNewsTool

    now = datetime(2026, 9, 14, 2, 0, tzinfo=UTC)
    batch = ResearchSearchBatch(
        batch_id=uuid4(),
        run_id=uuid4(),
        task_id=uuid4(),
        attempt=1,
        sector_id="sector-1",
        sector_kind=SectorKind.INDUSTRY,
        query="文化传媒 政策",
        start_at=now - timedelta(days=7),
        cutoff_at=now,
        input_fingerprint="a" * 64,
        status=ResearchSearchStatus.FAILED,
        error_code="NEWS_SEARCH_FAILED",
        document_ids=(),
        event_ids=(),
        created_at=now,
    )

    class Service:
        async def search(self, **kwargs):
            return batch

    class Searches:
        def get(self, batch_id):
            return batch if batch_id == batch.batch_id else None

    context = BoundSectorResearchContext(
        run_id=batch.run_id,
        task_id=batch.task_id,
        attempt=1,
        worker_id="worker",
        sector_id="sector-1",
        sector_kind=SectorKind.INDUSTRY,
        sector_name="文化传媒",
        selection_version=1,
        cutoff_at=now,
        input_artifacts=(),
    )
    tool = SearchNewsTool(Service(), searches=Searches(), context=context)
    result = await tool.run(query="政策 secret=https://private.example/token")
    assert not result.success
    assert result.error == "NEWS_SEARCH_FAILED"
    assert "private.example" not in result.content
    replay = tool.replay(f"research-search:{batch.batch_id}")
    assert not replay.success
    assert replay.error == "NEWS_SEARCH_FAILED"


@pytest.mark.asyncio
async def test_t06_search_is_scope_bound_bounded_atomic_and_replayable(tmp_path):
    from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter
    from sector_pulse.application.orchestration.research_context import (
        BoundSectorResearchContext,
    )
    from sector_pulse.application.orchestration.research_news_tools import (
        SearchSectorNewsService,
    )
    from sector_pulse.application.orchestration.tool_budget import SharedToolBudget
    from sector_pulse.domain.market.market import SectorKind
    from sector_pulse.domain.news.news import NewsDocument, SourceGrade
    from sector_pulse.domain.orchestration.models import (
        ArtifactRef,
        RunSnapshot,
        TaskRecord,
        TaskStatus,
    )
    from sector_pulse.domain.provider import DataStatus, ProviderError, ProviderResult
    from sector_pulse.infrastructure.agents.research_tools import SearchNewsTool
    from sector_pulse.infrastructure.agents.tool_adapter import BudgetedTool
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.news.research_search_repository import (
        SQLiteResearchSearchRepository,
    )
    from sector_pulse.storage.sqlite.orchestration.repository import (
        SQLiteOrchestrationRepository,
    )

    now = datetime(2026, 9, 14, 2, 0, tzinfo=UTC)
    run_id, root_id, task_id = uuid4(), uuid4(), uuid4()
    candidate = ArtifactRef(
        artifact_id=uuid4(),
        task_id=root_id,
        kind="candidate_batch",
        reference=f"candidate-batch:{uuid4()}",
    )
    root = TaskRecord(task_id=root_id, role="A0", scope="run")
    task = TaskRecord(
        task_id=task_id,
        parent_id=root_id,
        role="A2",
        scope="sector:INDUSTRY:sector-1",
        status=TaskStatus.RUNNING,
        worker_id="research-worker",
        lease_expires_at=now + timedelta(minutes=5),
        input_artifact_ids=(candidate.artifact_id,),
        selection_version=1,
    )
    database = SQLiteDatabase(tmp_path / "research-tools.db")
    database.initialize()
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO analysis_runs (run_id, mode, requested_at, run_cutoff_at, "
            "cutoff_locked_at) VALUES (?, 'LIVE', ?, ?, ?)",
            (str(run_id), now.isoformat(), now.isoformat(), now.isoformat()),
        )
    orchestration = SQLiteOrchestrationRepository(database)
    orchestration.save(
        RunSnapshot(
            run_id=run_id,
            deadline=datetime.now(UTC) + timedelta(minutes=10),
            tasks=(root, task),
            artifacts=(candidate,),
        ),
        -1,
        "research.created",
    )
    documents = tuple(
        NewsDocument(
            document_id=f"doc-{index}",
            source_id="fixture",
            canonical_locator=f"urn:fixture:{index}",
            citation_url=f"https://example.com/{index}",
            title=f"文化传媒事件 {index}",
            publisher="测试来源",
            summary="摘要",
            published_at=now - timedelta(hours=index),
            source_observed_at=now - timedelta(hours=index),
            collected_at=now,
            content_hash=f"hash-{index}",
            source_grade=SourceGrade.REPUTABLE_MEDIA,
        )
        for index in range(12)
    ) + (
        NewsDocument(
            document_id="after-cutoff",
            source_id="fixture",
            canonical_locator="urn:fixture:after",
            title="文化传媒未来消息",
            published_at=now + timedelta(minutes=1),
            source_observed_at=now + timedelta(minutes=1),
            collected_at=now,
            content_hash="after",
            source_grade=SourceGrade.REPUTABLE_MEDIA,
        ),
    )

    class Search:
        calls = 0
        query = ""
        start_at = now
        cutoff = now
        status = DataStatus.SUCCESS
        error: Exception | None = None
        delay = False

        async def search(self, query, start_at, cutoff):
            self.calls += 1
            self.query, self.start_at, self.cutoff = query, start_at, cutoff
            if self.delay:
                await asyncio.sleep(0.05)
            if self.error is not None:
                raise self.error
            return ProviderResult(
                provider_id="fixture",
                capability="news.keyword",
                status=self.status,
                data=documents,
                error=(
                    ProviderError(
                        code="UPSTREAM_PARTIAL",
                        message="some sources were unavailable",
                    )
                    if self.status is DataStatus.PARTIAL
                    else None
                ),
                observed_at=now,
                collected_at=now,
            )

    provider = Search()
    context = BoundSectorResearchContext(
        run_id=run_id,
        task_id=task_id,
        attempt=1,
        worker_id="research-worker",
        sector_id="sector-1",
        sector_kind=SectorKind.INDUSTRY,
        sector_name="文化传媒",
        selection_version=1,
        cutoff_at=now,
        input_artifacts=(candidate,),
    )
    repository = SQLiteResearchSearchRepository(database)
    service = SearchSectorNewsService(
        search=provider,
        orchestration=orchestration,
        committer=AtomicArtifactCommitter(orchestration, run_id),
    )
    tool = SearchNewsTool(service, searches=repository, context=context, clock=lambda: now)
    budgeted = BudgetedTool(
        tool,
        SharedToolBudget(orchestration, run_id),
        task_id=task_id,
        attempt=1,
        reserved_cny=Decimal("0"),
    )
    result = await budgeted.run(query="  政策   发布  ")
    assert result.success
    assert provider.calls == 1
    assert provider.query == "文化传媒 政策 发布"
    assert provider.start_at == now - timedelta(days=7)
    assert provider.cutoff == now
    state = orchestration.load(run_id)
    artifact = next(item for item in state.artifacts if item.kind == "research_search")
    assert json.loads(result.content)["artifact_refs"] == [str(artifact.artifact_id)]
    batch = repository.get(UUID(artifact.reference.removeprefix("research-search:")))
    assert batch is not None
    assert len(batch.document_ids) == 10
    assert "after-cutoff" not in batch.document_ids

    replayed = await budgeted.run(query="  政策   发布  ")
    assert replayed.content == result.content
    assert provider.calls == 1
    assert orchestration.load(run_id).ledger.tool_calls == 1
    denied = await tool.run(query="政策", sector_id="other")
    assert not denied.success
    assert "server controlled" in (denied.error or "")

    provider.status = DataStatus.PARTIAL
    partial = await budgeted.run(query="行业治理")
    assert not partial.success
    assert partial.error == "NEWS_SEARCH_PARTIAL"
    partial_batch = repository.get(
        UUID(partial.metadata["result_reference"].removeprefix("research-search:"))
    )
    assert partial_batch is not None
    assert partial_batch.document_ids

    provider.error = RuntimeError("secret=https://private.example/token")
    failed = await budgeted.run(query="公司动态")
    assert not failed.success
    assert failed.error == "NEWS_SEARCH_FAILED"
    assert "private.example" not in failed.content
    failed_batch = repository.get(
        UUID(failed.metadata["result_reference"].removeprefix("research-search:"))
    )
    assert failed_batch is not None
    assert not failed_batch.document_ids

    provider.status = DataStatus.SUCCESS
    provider.error = None
    provider.delay = True
    concurrent = await asyncio.gather(
        budgeted.run(query="并发检索"),
        budgeted.run(query="并发检索"),
    )
    assert provider.calls == 4
    assert sum(item.success for item in concurrent) == 1
    concurrent_replay = await budgeted.run(query="并发检索")
    assert concurrent_replay.success
    assert provider.calls == 4

    current = orchestration.load(run_id)
    replacement = task.model_copy(
        update={
            "attempt": 2,
            "worker_id": "replacement-worker",
            "lease_expires_at": now + timedelta(minutes=6),
        }
    )
    orchestration.save(
        current.model_copy(
            update={
                "revision": current.revision + 1,
                "tasks": tuple(
                    replacement if item.task_id == task_id else item
                    for item in current.tasks
                ),
            }
        ),
        current.revision,
        "task.recovered:test",
    )
    stale = await budgeted.run(query="另一条查询")
    assert not stale.success
    assert "stale task attempt" in (stale.error or "")
    assert provider.calls == 4


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_postgres_t06_t07_research_artifacts_are_atomic_and_readable():
    import os

    from sector_pulse.application.news.news_ingestion import deduplicate_documents
    from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter
    from sector_pulse.application.orchestration.evidence_tools import (
        InspectSectorEvidenceService,
        SubmitSectorAnalysisService,
    )
    from sector_pulse.application.orchestration.research_context import (
        BoundSectorResearchContext,
    )
    from sector_pulse.application.orchestration.research_news_tools import (
        ReadBoundNewsDetailService,
        ResearchSearchPersistence,
        SearchSectorNewsService,
    )
    from sector_pulse.domain.market.candidate import SectorCandidate
    from sector_pulse.domain.market.candidate_batch import (
        CandidateBatch,
        CandidateRankingStage,
    )
    from sector_pulse.domain.market.market import (
        SectorKind,
        SectorSnapshot,
        SectorUniverseSnapshot,
    )
    from sector_pulse.domain.news.evidence import EvidenceLevel
    from sector_pulse.domain.news.news import NewsDocument, SourceGrade
    from sector_pulse.domain.news.news_detail import NewsDetail
    from sector_pulse.domain.orchestration.models import (
        ArtifactRef,
        RunSnapshot,
        TaskRecord,
        TaskStatus,
    )
    from sector_pulse.domain.provider import DataStatus, ProviderResult
    from sector_pulse.domain.runs.time import AnalysisRun
    from sector_pulse.domain.writing.research import SectorAnalysisSubmission
    from sector_pulse.storage.postgres.database import PostgresDatabase
    from sector_pulse.storage.postgres.market.candidate_batch_repository import (
        PostgresCandidateBatchRepository,
    )
    from sector_pulse.storage.postgres.market.market_snapshot_repository import (
        PostgresMarketSnapshotRepository,
    )
    from sector_pulse.storage.postgres.news.news_detail_snapshot_repository import (
        PostgresNewsDetailSnapshotRepository,
    )
    from sector_pulse.storage.postgres.news.news_repository import PostgresNewsRepository
    from sector_pulse.storage.postgres.news.research_search_repository import (
        PostgresResearchSearchRepository,
    )
    from sector_pulse.storage.postgres.orchestration.repository import (
        PostgresOrchestrationRepository,
    )
    from sector_pulse.storage.postgres.writing.evidence_inspection_repository import (
        PostgresEvidenceInspectionRepository,
    )
    from sector_pulse.storage.postgres.writing.sector_analysis_repository import (
        PostgresSectorAnalysisRepository,
    )
    from sqlalchemy import text
    from sqlalchemy.engine import make_url

    url = os.getenv("SECTOR_PULSE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires dedicated SECTOR_PULSE_TEST_DATABASE_URL")
    assert (make_url(url).database or "").endswith("_test"), "business database refused"
    database = PostgresDatabase(url)
    database.initialize()
    now = datetime(2026, 9, 14, 2, 0, tzinfo=UTC)
    run_id, root_id, task_id = uuid4(), uuid4(), uuid4()
    document = NewsDocument(
        document_id=f"pg-doc-{uuid4()}",
        source_id="fixture",
        canonical_locator=f"urn:fixture:{uuid4()}",
        citation_url="https://example.com/research",
        title="文化传媒政策发布",
        publisher="测试来源",
        summary="摘要",
        published_at=now - timedelta(hours=1),
        source_observed_at=now - timedelta(hours=1),
        collected_at=now,
        content_hash=f"hash-{uuid4()}",
        source_grade=SourceGrade.PRIMARY,
    )
    candidate = ArtifactRef(
        artifact_id=uuid4(),
        task_id=root_id,
        kind="candidate_batch",
        reference=f"candidate-batch:{uuid4()}",
    )
    root = TaskRecord(task_id=root_id, role="A0", scope="run")
    task = TaskRecord(
        task_id=task_id,
        parent_id=root_id,
        role="A2",
        scope="sector:INDUSTRY:sector-1",
        status=TaskStatus.RUNNING,
        worker_id="research-worker",
        lease_expires_at=now + timedelta(minutes=5),
        input_artifact_ids=(candidate.artifact_id,),
        selection_version=1,
    )

    class Search:
        async def search(self, query, start_at, cutoff):
            return ProviderResult(
                provider_id="fixture",
                capability="news.keyword",
                status=DataStatus.SUCCESS,
                data=(document,),
                observed_at=now,
                collected_at=now,
            )

    orchestration = PostgresOrchestrationRepository(database)
    try:
        with database.start().begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO analysis_runs (run_id, mode, requested_at, run_cutoff_at, "
                    "cutoff_locked_at) VALUES (:run_id, 'LIVE', :now, :now, :now)"
                ),
                {"run_id": str(run_id), "now": now.isoformat()},
            )
        orchestration.save(
            RunSnapshot(
                run_id=run_id,
                deadline=now + timedelta(minutes=10),
                tasks=(root, task),
                artifacts=(candidate,),
            ),
            -1,
            "research.created",
        )
        context = BoundSectorResearchContext(
            run_id=run_id,
            task_id=task_id,
            attempt=1,
            worker_id="research-worker",
            sector_id="sector-1",
            sector_kind=SectorKind.INDUSTRY,
            sector_name="文化传媒",
            selection_version=1,
            cutoff_at=now,
            input_artifacts=(candidate,),
        )
        batch = await SearchSectorNewsService(
            search=Search(),
            orchestration=orchestration,
            committer=AtomicArtifactCommitter(orchestration, run_id),
        ).search(context=context, query="政策", now=now)
        assert PostgresResearchSearchRepository(database).get(batch.batch_id) == batch
        state = orchestration.load(run_id)
        assert any(
            item.kind == "research_search"
            and item.reference == f"research-search:{batch.batch_id}"
            for item in state.artifacts
        )

        class Detail:
            async def read(self, requested):
                assert requested == document
                return NewsDetail(
                    document_id=document.document_id,
                    availability="full_text",
                    content="经验证的正文",
                    fetched_at=now,
                    content_hash="ignored-provider-hash",
                    historical_snapshot_verified=False,
                )

        detail_snapshot = await ReadBoundNewsDetailService(
            detail=Detail(),
            orchestration=orchestration,
            committer=AtomicArtifactCommitter(orchestration, run_id),
            news=PostgresNewsRepository(database),
            research_searches=PostgresResearchSearchRepository(database),
        ).read(context=context, document_id=document.document_id, now=now)
        assert (
            PostgresNewsDetailSnapshotRepository(database).get(detail_snapshot.detail_id)
            == detail_snapshot
        )
        assert any(
            item.kind == "news_detail"
            and item.reference == f"news-detail:{detail_snapshot.detail_id}"
            for item in orchestration.load(run_id).artifacts
        )

        candidate_batch_id = UUID(candidate.reference.removeprefix("candidate-batch:"))
        candidate_item = SectorCandidate(
            rank=1,
            provider_sector_id="sector-1",
            name="文化传媒",
            kind=SectorKind.INDUSTRY,
            score=Decimal("0.9"),
            reasons=("market",),
        )
        candidate_batch = CandidateBatch(
            batch_id=candidate_batch_id,
            run_id=run_id,
            input_fingerprint="c" * 64,
            ranking_stage=CandidateRankingStage.NEWS_ENRICHED,
            candidate_limit=12,
            created_at=now,
            candidates=(candidate_item,),
        )
        with database.start().begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO candidate_batches (batch_id, run_id, input_fingerprint, "
                    "ranking_stage, candidate_limit, created_at) VALUES (:batch_id, :run_id, "
                    ":fingerprint, :stage, 12, :created_at)"
                ),
                {
                    "batch_id": str(candidate_batch_id),
                    "run_id": str(run_id),
                    "fingerprint": candidate_batch.input_fingerprint,
                    "stage": candidate_batch.ranking_stage.value,
                    "created_at": now.isoformat(),
                },
            )
            connection.execute(
                text(
                    "INSERT INTO sector_candidate_versions (batch_id, provider_sector_id, "
                    "sector_kind, sector_name, rank, score, reasons_json) VALUES "
                    "(:batch_id, 'sector-1', 'INDUSTRY', :name, 1, '0.9', '[]')"
                ),
                {"batch_id": str(candidate_batch_id), "name": "文化传媒"},
            )
        analysis_run = AnalysisRun.create_live(now, run_id).lock_live_cutoff(now, now)
        universe = SectorUniverseSnapshot(
            provider_id="fixture",
            classification_version="v1",
            source_version="v1",
            kind=SectorKind.INDUSTRY,
            observed_at=now,
            collected_at=now,
            sectors=(
                SectorSnapshot(
                    provider_sector_id="sector-1",
                    name="文化传媒",
                    kind=SectorKind.INDUSTRY,
                    pct_change=Decimal("2.5"),
                    advancers=8,
                    decliners=2,
                ),
            ),
        )
        PostgresMarketSnapshotRepository(database).save(
            analysis_run,
            ProviderResult(
                provider_id="fixture",
                capability="market.industry",
                status=DataStatus.SUCCESS,
                data=universe,
                observed_at=now,
                collected_at=now,
            ),
        )
        current_artifacts = orchestration.load(run_id).artifacts
        search_ref = next(item for item in current_artifacts if item.kind == "research_search")
        detail_ref = next(item for item in current_artifacts if item.kind == "news_detail")
        report = InspectSectorEvidenceService(
            orchestration=orchestration,
            committer=AtomicArtifactCommitter(orchestration, run_id),
            candidate_batches=PostgresCandidateBatchRepository(database),
            market_snapshots=PostgresMarketSnapshotRepository(database),
            news=PostgresNewsRepository(database),
            research_searches=PostgresResearchSearchRepository(database),
            news_details=PostgresNewsDetailSnapshotRepository(database),
        ).inspect(
            context=context,
            artifact_ids=(candidate.artifact_id, search_ref.artifact_id, detail_ref.artifact_id),
            now=now,
        )
        assert PostgresEvidenceInspectionRepository(database).get(report.report_id) == report
        inspection_ref = next(
            item
            for item in orchestration.load(run_id).artifacts
            if item.kind == "evidence_inspection"
        )
        analysis = SubmitSectorAnalysisService(
            orchestration=orchestration,
            committer=AtomicArtifactCommitter(orchestration, run_id),
            inspections=PostgresEvidenceInspectionRepository(database),
        ).submit(
            context=context,
            inspection_artifact_id=inspection_ref.artifact_id,
            submission=SectorAnalysisSubmission(
                attribution_level=EvidenceLevel.MARKET_ASSOCIATION,
                confidence=Decimal("0.6"),
                conclusion="存在市场联想",
                supporting_evidence_ids=report.gate.eligible_evidence_ids,
            ),
            now=now,
        )
        assert PostgresSectorAnalysisRepository(database).get(analysis.analysis_id) == analysis

        rolled_back = batch.model_copy(
            update={
                "batch_id": uuid4(),
                "query": "文化传媒 回滚检查",
                "input_fingerprint": "b" * 64,
            }
        )
        rolled_back_artifact = ArtifactRef(
            artifact_id=uuid4(),
            task_id=task_id,
            attempt=1,
            kind="research_search",
            reference=f"research-search:{rolled_back.batch_id}",
        )

        class FailingPersistence(ResearchSearchPersistence):
            def write(self, session, artifact):
                super().write(session, artifact)
                raise RuntimeError("injected transaction failure")

        with pytest.raises(RuntimeError, match="injected transaction failure"):
            AtomicArtifactCommitter(orchestration, run_id).commit(
                rolled_back_artifact,
                worker_id="research-worker",
                persistence=FailingPersistence(
                    rolled_back,
                    (document,),
                    deduplicate_documents((document,)),
                ),
                now=now,
            )
        assert PostgresResearchSearchRepository(database).get(rolled_back.batch_id) is None
        assert rolled_back_artifact not in orchestration.load(run_id).artifacts
    finally:
        with database.start().begin() as connection:
            connection.execute(
                text("DELETE FROM orchestration_events WHERE run_id=:run_id"),
                {"run_id": str(run_id)},
            )
            connection.execute(
                text("DELETE FROM orchestration_snapshots WHERE run_id=:run_id"),
                {"run_id": str(run_id)},
            )
            connection.execute(
                text("DELETE FROM analysis_runs WHERE run_id=:run_id"),
                {"run_id": str(run_id)},
            )
            connection.execute(
                text("DELETE FROM news_event_documents WHERE document_id=:document_id"),
                {"document_id": document.document_id},
            )
            connection.execute(
                text("DELETE FROM news_events WHERE metadata_json LIKE :document_id"),
                {"document_id": f"%{document.document_id}%"},
            )
            connection.execute(
                text("DELETE FROM news_documents WHERE document_id=:document_id"),
                {"document_id": document.document_id},
            )
        database.close()
