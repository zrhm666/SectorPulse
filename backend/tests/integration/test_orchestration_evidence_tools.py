import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_t08_inspection_is_scope_bound_order_independent_and_programmatic():
    from sector_pulse.application.orchestration.evidence_tools import (
        InspectSectorEvidenceService,
    )
    from sector_pulse.application.orchestration.research_context import (
        BoundSectorResearchContext,
    )
    from sector_pulse.application.orchestration.tasks import TaskOwnershipError
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
    from sector_pulse.domain.news.news import NewsDocument, NewsEvent, SourceGrade
    from sector_pulse.domain.news.research import (
        NewsDetailSnapshot,
        ResearchSearchBatch,
        ResearchSearchStatus,
    )
    from sector_pulse.domain.orchestration.models import (
        ArtifactRef,
        RunSnapshot,
        TaskRecord,
        TaskStatus,
    )
    from sector_pulse.domain.runs.time import AnalysisRun
    from sector_pulse.infrastructure.agents.evidence_tools import InspectEvidenceTool

    now = datetime(2026, 9, 14, 4, 0, tzinfo=UTC)
    run_id, root_id, task_id, candidate_batch_id = uuid4(), uuid4(), uuid4(), uuid4()
    candidate_artifact = ArtifactRef(
        artifact_id=uuid4(),
        task_id=root_id,
        kind="candidate_batch",
        reference=f"candidate-batch:{candidate_batch_id}",
    )
    search_artifact = ArtifactRef(
        artifact_id=uuid4(),
        task_id=task_id,
        attempt=1,
        kind="research_search",
        reference=f"research-search:{uuid4()}",
    )
    detail_artifact = ArtifactRef(
        artifact_id=uuid4(),
        task_id=task_id,
        attempt=1,
        kind="news_detail",
        reference=f"news-detail:{uuid4()}",
    )
    unrelated_input = ArtifactRef(
        artifact_id=uuid4(),
        task_id=root_id,
        kind="candidate_proposal",
        reference=f"candidate-proposal:{uuid4()}",
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
        input_artifact_ids=(candidate_artifact.artifact_id,),
        selection_version=1,
    )
    state = RunSnapshot(
        run_id=run_id,
        deadline=now + timedelta(minutes=10),
        tasks=(root, task),
        artifacts=(candidate_artifact, search_artifact, detail_artifact, unrelated_input),
    )

    class Orchestration:
        def load(self, requested_run_id):
            return state if requested_run_id == run_id else None

    candidate = SectorCandidate(
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
        input_fingerprint="a" * 64,
        ranking_stage=CandidateRankingStage.NEWS_ENRICHED,
        candidate_limit=12,
        created_at=now,
        candidates=(candidate,),
    )
    sector = SectorSnapshot(
        provider_sector_id="sector-1",
        name="文化传媒",
        kind=SectorKind.INDUSTRY,
        pct_change=Decimal("2.5"),
        turnover_rate=Decimal("3.2"),
        advancers=8,
        decliners=2,
    )
    universe = SectorUniverseSnapshot(
        provider_id="fixture",
        classification_version="v1",
        source_version="v1",
        kind=SectorKind.INDUSTRY,
        observed_at=now,
        collected_at=now,
        sectors=(sector,),
    )
    run = AnalysisRun.create_live(now, run_id).lock_live_cutoff(now, now)
    document = NewsDocument(
        document_id="doc-1",
        source_id="fixture",
        canonical_locator="urn:fixture:doc-1",
        citation_url="https://example.com/1",
        title="文化传媒政策",
        publisher="权威来源",
        summary="摘要",
        published_at=now - timedelta(hours=1),
        source_observed_at=now - timedelta(hours=1),
        collected_at=now,
        content_hash="doc-hash",
        source_grade=SourceGrade.PRIMARY,
    )
    event = NewsEvent(
        event_id="event-1",
        canonical_title=document.title,
        first_published_at=document.published_at,
        document_ids=(document.document_id,),
        deduplication_reason="fixture",
        sector_ids=("sector-1",),
    )
    search = ResearchSearchBatch(
        batch_id=uuid4(),
        run_id=run_id,
        task_id=task_id,
        attempt=1,
        sector_id="sector-1",
        sector_kind=SectorKind.INDUSTRY,
        query="文化传媒 政策",
        start_at=now - timedelta(days=7),
        cutoff_at=now,
        input_fingerprint="b" * 64,
        status=ResearchSearchStatus.SUCCESS,
        document_ids=(document.document_id,),
        event_ids=(event.event_id,),
        created_at=now,
    )
    search_artifact = search_artifact.model_copy(
        update={"reference": f"research-search:{search.batch_id}"}
    )
    detail = NewsDetailSnapshot(
        detail_id=uuid4(),
        run_id=run_id,
        task_id=task_id,
        attempt=1,
        sector_id="sector-1",
        sector_kind=SectorKind.INDUSTRY,
        document_id=document.document_id,
        document_content_hash=document.content_hash,
        input_fingerprint="c" * 64,
        availability="full_text",
        content="正文",
        content_hash="detail-hash",
        fetched_at=now,
        created_at=now,
    )
    detail_artifact = detail_artifact.model_copy(
        update={"reference": f"news-detail:{detail.detail_id}"}
    )
    state = state.model_copy(
        update={
            "artifacts": (
                candidate_artifact,
                search_artifact,
                detail_artifact,
                unrelated_input,
            )
        }
    )

    class CandidateBatches:
        def get(self, identity):
            return candidate_batch if identity == candidate_batch_id else None

    class Markets:
        def get(self, requested_run_id, kind):
            return universe if requested_run_id == run_id and kind is SectorKind.INDUSTRY else None

        def get_run(self, requested_run_id):
            return run if requested_run_id == run_id else None

    class Searches:
        def get(self, identity):
            return search if identity == search.batch_id else None

    class Details:
        def get(self, identity):
            return detail if identity == detail.detail_id else None

    class News:
        def get_documents(self, identities):
            return {document.document_id: document} if document.document_id in identities else {}

        def get_events(self, identities):
            return (event,) if event.event_id in identities else ()

    class Committer:
        artifacts = []

        def commit(self, artifact, **kwargs):
            self.artifacts.append(artifact)
            return artifact

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
        input_artifacts=(candidate_artifact, unrelated_input),
    )
    committer = Committer()
    service = InspectSectorEvidenceService(
        orchestration=Orchestration(),
        committer=committer,
        candidate_batches=CandidateBatches(),
        market_snapshots=Markets(),
        news=News(),
        research_searches=Searches(),
        news_details=Details(),
    )
    artifact_ids = (
        detail_artifact.artifact_id,
        candidate_artifact.artifact_id,
        search_artifact.artifact_id,
    )
    report = service.inspect(context=context, artifact_ids=artifact_ids, now=now)
    assert report.gate.allowed_max_level is EvidenceLevel.EXPLICIT_DRIVER
    assert report.context.eligible_event_ids == (event.event_id,)
    assert report.document_views[0].content == "正文"
    assert report.input_artifact_ids == tuple(sorted(artifact_ids, key=str))
    reversed_report = service.inspect(
        context=context,
        artifact_ids=tuple(reversed(artifact_ids)),
        now=now,
    )
    assert reversed_report.report_id == report.report_id

    with pytest.raises(ValueError, match="authorized"):
        service.inspect(context=context, artifact_ids=(uuid4(),), now=now)
    with pytest.raises(ValueError, match="pinned candidate"):
        service.inspect(
            context=context,
            artifact_ids=(search_artifact.artifact_id,),
            now=now,
        )
    matching_search = search
    search = search.model_copy(update={"sector_id": "other-sector"})
    with pytest.raises(ValueError, match="current scope"):
        service.inspect(
            context=context,
            artifact_ids=(candidate_artifact.artifact_id, search_artifact.artifact_id),
            now=now,
        )
    search = matching_search
    with pytest.raises(TaskOwnershipError, match="stale"):
        service.inspect(
            context=context.model_copy(update={"attempt": 2}),
            artifact_ids=artifact_ids,
            now=now,
        )
    assert len(committer.artifacts) == 2

    sibling_task_id = uuid4()
    sibling = task.model_copy(
        update={
            "task_id": sibling_task_id,
            "worker_id": "sibling-research-worker",
        }
    )
    state = state.model_copy(update={"tasks": (root, task, sibling)})
    first_base_report = service.inspect(
        context=context,
        artifact_ids=(candidate_artifact.artifact_id,),
        now=now,
    )
    sibling_report = service.inspect(
        context=context.model_copy(
            update={
                "task_id": sibling_task_id,
                "worker_id": "sibling-research-worker",
            }
        ),
        artifact_ids=(candidate_artifact.artifact_id,),
        now=now,
    )
    assert sibling_report.report_id != first_base_report.report_id

    class Reports:
        def get(self, identity):
            return report if identity == report.report_id else None

    tool = InspectEvidenceTool(
        service,
        reports=Reports(),
        context=context,
        clock=lambda: now,
    )
    assert set(tool.parameters["properties"]) == {"artifact_ids"}
    tool_result = await tool.run(artifact_ids=[str(item) for item in artifact_ids])
    assert tool_result.success
    assert "explicit_driver" in tool_result.content
    assert json.loads(tool_result.content)["artifact_refs"] == [
        str(committer.artifacts[-1].artifact_id)
    ]
    replay = tool.replay(f"evidence-inspection:{report.report_id}")
    assert replay.content == tool_result.content
    normalized_result = await tool.run(
        artifact_ids=[str(unrelated_input.artifact_id), str(search_artifact.artifact_id)]
    )
    assert normalized_result.success
    assert "explicit_driver" in normalized_result.content
    injected = await tool.run(
        artifact_ids=[str(item) for item in artifact_ids],
        sector_id="other",
    )
    assert not injected.success
    assert "server controlled" in (injected.error or "")


def test_t08_sqlite_report_and_artifact_are_atomic(tmp_path):
    from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter
    from sector_pulse.application.orchestration.evidence_tools import (
        EvidenceInspectionPersistence,
        SectorAnalysisPersistence,
    )
    from sector_pulse.domain.market.market import SectorKind
    from sector_pulse.domain.news.evidence import EvidenceLevel
    from sector_pulse.domain.orchestration.models import (
        ArtifactRef,
        RunSnapshot,
        TaskRecord,
        TaskStatus,
    )
    from sector_pulse.domain.writing.attribution import (
        AttributionContext,
        AttributionGateResult,
        SectorAnalysisCard,
    )
    from sector_pulse.domain.writing.research import (
        EvidenceInspectionReport,
        SectorAnalysisArtifact,
    )
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import (
        SQLiteOrchestrationRepository,
    )
    from sector_pulse.storage.sqlite.writing.evidence_inspection_repository import (
        SQLiteEvidenceInspectionRepository,
    )
    from sector_pulse.storage.sqlite.writing.sector_analysis_repository import (
        SQLiteSectorAnalysisRepository,
    )

    now = datetime(2026, 9, 14, 5, 0, tzinfo=UTC)
    run_id, root_id, task_id, report_id = uuid4(), uuid4(), uuid4(), uuid4()
    root = TaskRecord(task_id=root_id, role="A0", scope="run")
    task = TaskRecord(
        task_id=task_id,
        parent_id=root_id,
        role="A2",
        scope="sector:INDUSTRY:sector-1",
        status=TaskStatus.RUNNING,
        worker_id="research-worker",
        lease_expires_at=now + timedelta(minutes=5),
        selection_version=1,
    )
    database = SQLiteDatabase(tmp_path / "inspection.db")
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
            deadline=now + timedelta(minutes=10),
            tasks=(root, task),
        ),
        -1,
        "inspection.created",
    )
    context = AttributionContext(
        run_id=run_id,
        sector_id="sector-1",
        sector_kind=SectorKind.INDUSTRY,
        sector_name="文化传媒",
        cutoff_at=now,
        market_facts={"pct_change": Decimal("1")},
        event_ids=(),
        eligible_event_ids=(),
        background_event_ids=(),
        excluded_event_ids=(),
        source_grades={},
        counter_evidence=(),
    )
    gate = AttributionGateResult(
        run_id=run_id,
        sector_id="sector-1",
        allowed_max_level=EvidenceLevel.NO_RELIABLE_EXPLANATION,
        reasons=("NO_ELIGIBLE_EVENT",),
        eligible_evidence_ids=(),
        excluded_evidence_ids=(),
        counter_evidence=(),
    )
    report = EvidenceInspectionReport(
        report_id=report_id,
        run_id=run_id,
        task_id=task_id,
        attempt=1,
        sector_id="sector-1",
        selection_version=1,
        input_artifact_ids=(uuid4(),),
        input_fingerprint="d" * 64,
        context=context,
        gate=gate,
        document_views=(),
        created_at=now,
    )
    artifact = ArtifactRef(
        artifact_id=uuid4(),
        task_id=task_id,
        attempt=1,
        kind="evidence_inspection",
        reference=f"evidence-inspection:{report_id}",
    )
    AtomicArtifactCommitter(orchestration, run_id).commit(
        artifact,
        worker_id="research-worker",
        persistence=EvidenceInspectionPersistence(report),
        now=now,
    )
    assert SQLiteEvidenceInspectionRepository(database).get(report_id) == report
    assert artifact in orchestration.load(run_id).artifacts

    card = SectorAnalysisCard(
        run_id=run_id,
        sector_id="sector-1",
        sector_kind=SectorKind.INDUSTRY,
        sector_name="文化传媒",
        allowed_max_level=EvidenceLevel.NO_RELIABLE_EXPLANATION,
        attribution_level=EvidenceLevel.NO_RELIABLE_EXPLANATION,
        confidence=Decimal("0.2"),
        conclusion="暂无可靠解释",
        supporting_evidence_ids=(),
        counter_evidence=(),
        uncertainties=("缺少合格事件",),
        background_event_ids=(),
        claims=(),
        forbidden_inferences=(),
    )
    analysis = SectorAnalysisArtifact(
        analysis_id=uuid4(),
        run_id=run_id,
        task_id=task_id,
        attempt=1,
        inspection_id=report_id,
        input_fingerprint="e" * 64,
        card_hash="f" * 64,
        card=card,
        created_at=now,
    )
    analysis_artifact = ArtifactRef(
        artifact_id=uuid4(),
        task_id=task_id,
        attempt=1,
        kind="sector_analysis",
        reference=f"sector-analysis:{analysis.analysis_id}",
    )
    AtomicArtifactCommitter(orchestration, run_id).commit(
        analysis_artifact,
        worker_id="research-worker",
        persistence=SectorAnalysisPersistence(analysis),
        now=now,
    )
    analyses = SQLiteSectorAnalysisRepository(database)
    assert analyses.get(analysis.analysis_id) == analysis

    revised = analysis.model_copy(
        update={
            "analysis_id": uuid4(),
            "input_fingerprint": "1" * 64,
            "card_hash": "2" * 64,
            "card": card.model_copy(update={"conclusion": "仍无可靠解释"}),
        }
    )
    revised_artifact = analysis_artifact.model_copy(
        update={
            "artifact_id": uuid4(),
            "reference": f"sector-analysis:{revised.analysis_id}",
        }
    )
    AtomicArtifactCommitter(orchestration, run_id).commit(
        revised_artifact,
        worker_id="research-worker",
        persistence=SectorAnalysisPersistence(revised),
        now=now,
    )
    assert analyses.get(analysis.analysis_id) == analysis
    assert analyses.get(revised.analysis_id) == revised

    concurrent_analysis = analysis.model_copy(
        update={
            "analysis_id": uuid4(),
            "input_fingerprint": "3" * 64,
            "card_hash": "4" * 64,
        }
    )
    concurrent_artifact = analysis_artifact.model_copy(
        update={
            "artifact_id": uuid4(),
            "reference": f"sector-analysis:{concurrent_analysis.analysis_id}",
        }
    )

    def submit_same_analysis() -> bool:
        try:
            AtomicArtifactCommitter(orchestration, run_id).commit(
                concurrent_artifact,
                worker_id="research-worker",
                persistence=SectorAnalysisPersistence(concurrent_analysis),
                now=now,
            )
            return True
        except (sqlite3.IntegrityError, ValueError, RuntimeError):
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(lambda _: submit_same_analysis(), range(2)))
    assert outcomes.count(True) == 1
    assert analyses.get(concurrent_analysis.analysis_id) == concurrent_analysis
    assert sum(
        item.reference == concurrent_artifact.reference
        for item in orchestration.load(run_id).artifacts
    ) == 1
