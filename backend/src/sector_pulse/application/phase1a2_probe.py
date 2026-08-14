import time
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from sector_pulse.application.candidate_selection import (
    build_evidence_pack,
    select_candidates,
    select_market_precandidates,
)
from sector_pulse.application.entity_resolution import resolve_sector_links
from sector_pulse.application.news_ingestion import deduplicate_documents
from sector_pulse.application.news_quality import NewsQualityReport, evaluate_news_quality
from sector_pulse.application.news_retrieval import build_news_query_plan, execute_news_query_plan
from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.news_retrieval import SectorEntityConfig
from sector_pulse.domain.provider import DataStatus
from sector_pulse.domain.quality import (
    QualityReport,
    QualityStatus,
    QualityThresholds,
    evaluate_universe,
)
from sector_pulse.domain.time import AnalysisMode, AnalysisRun
from sector_pulse.ports.market_data import MarketDataPort
from sector_pulse.ports.news_sources import (
    DisclosureSearchPort,
    GlobalNewsDiscoveryPort,
    KeywordNewsSearchPort,
    SectorConstituentPort,
)
from sector_pulse.storage.evidence_repository import SQLiteEvidenceRepository
from sector_pulse.storage.market_snapshot_repository import SQLiteMarketSnapshotRepository
from sector_pulse.storage.news_repository import SQLiteNewsRepository
from sector_pulse.storage.news_retrieval_repository import SQLiteNewsRetrievalRepository
from sector_pulse.storage.sqlite import SQLiteDatabase


class Phase1A2Request(BaseModel):
    model_config = ConfigDict(frozen=True)

    requested_at: datetime
    run_kind: str = Field(pattern="^(intraday|post_close)$")
    lookback_hours: int = Field(default=24, ge=1, le=168)
    precandidate_limit: int = Field(default=30, ge=1, le=50)
    final_candidate_limit: int = Field(default=12, ge=1, le=12)
    min_industry_count: int = Field(default=50, ge=1)
    min_concept_count: int = Field(default=100, ge=1)


class Phase1A2Dependencies(Protocol):
    @property
    def market(self) -> MarketDataPort: ...
    @property
    def constituents(self) -> SectorConstituentPort: ...
    @property
    def global_news(self) -> GlobalNewsDiscoveryPort: ...
    @property
    def keyword_news(self) -> KeywordNewsSearchPort: ...
    @property
    def disclosure_news(self) -> DisclosureSearchPort: ...
    @property
    def database(self) -> SQLiteDatabase: ...
    @property
    def entity_config(self) -> SectorEntityConfig: ...


class SourceMetricSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: DataStatus
    call_count: int
    retry_count: int
    duration_ms: int
    document_count: int
    error_codes: tuple[str, ...] = ()


class Phase1A2Report(BaseModel):
    model_config = ConfigDict(frozen=True)

    run: AnalysisRun
    run_kind: str
    elapsed_ms: int
    market_quality: Mapping[str, QualityReport]
    news_quality: NewsQualityReport
    market_precandidate_count: int
    final_candidate_count: int
    source_metrics: Mapping[str, SourceMetricSummary]
    document_count: int
    event_count: int
    link_count: int
    deduplication_rate: float
    mapping_rate: float
    cutoff_violation_count: int
    downgrade_reasons: tuple[str, ...]
    ready_for_phase1b: bool
    evidence_pack_count: int


def _empty_report(
    request: Phase1A2Request,
    run: AnalysisRun,
    started: float,
    market_quality: Mapping[str, QualityReport],
    reason: str,
) -> Phase1A2Report:
    empty_quality = NewsQualityReport(
        status=QualityStatus.BLOCKED,
        document_count=0,
        event_count=0,
        citation_eligible_count=0,
        background_only_count=0,
        excluded_after_cutoff_count=0,
        source_statuses={},
        blocking_reasons=(reason,),
    )
    return Phase1A2Report(
        run=run,
        run_kind=request.run_kind,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        market_quality=market_quality,
        news_quality=empty_quality,
        market_precandidate_count=0,
        final_candidate_count=0,
        source_metrics={},
        document_count=0,
        event_count=0,
        link_count=0,
        deduplication_rate=0.0,
        mapping_rate=0.0,
        cutoff_violation_count=0,
        downgrade_reasons=(reason,),
        ready_for_phase1b=False,
        evidence_pack_count=0,
    )


async def run_phase1a2_probe(
    dependencies: Phase1A2Dependencies, request: Phase1A2Request
) -> Phase1A2Report:
    """执行 Phase 1A.2 的真实数据链路；Provider 由依赖注入提供，编排器不创建具体实现。"""
    started = time.perf_counter()
    database = dependencies.database
    database.initialize()
    run = AnalysisRun.create_live(request.requested_at)
    industry, concept = await __import__("asyncio").gather(
        dependencies.market.fetch_sector_universe(SectorKind.INDUSTRY, AnalysisMode.LIVE),
        dependencies.market.fetch_sector_universe(SectorKind.CONCEPT, AnalysisMode.LIVE),
    )
    thresholds = QualityThresholds(
        min_industry_count=request.min_industry_count,
        min_concept_count=request.min_concept_count,
    )
    industry_quality = evaluate_universe(industry, thresholds)
    concept_quality = evaluate_universe(concept, thresholds)
    market_quality = {"industry": industry_quality, "concept": concept_quality}
    if (
        industry.data is None
        or concept.data is None
        or any(report.status is QualityStatus.BLOCKED for report in market_quality.values())
    ):
        return _empty_report(request, run, started, market_quality, "MARKET_BLOCKED")
    observed = max(industry.data.observed_at, concept.data.observed_at)
    run = run.lock_live_cutoff(observed, datetime.now(UTC))
    cutoff = run.run_cutoff_at
    if cutoff is None:  # 防御性检查，保证后续新闻查询始终使用已锁定 cutoff。
        return _empty_report(request, run, started, market_quality, "CUTOFF_NOT_LOCKED")
    SQLiteMarketSnapshotRepository(database).save(run, industry)
    SQLiteMarketSnapshotRepository(database).save(run, concept)
    precandidates = select_market_precandidates(
        industry.data, concept.data, request.precandidate_limit
    )
    memberships: dict[str, tuple[tuple[str, str], ...]] = {}
    for candidate in precandidates:
        result = await dependencies.constituents.fetch_constituents(candidate.name, candidate.kind)
        memberships[candidate.provider_sector_id] = result.data or ()
    plan = build_news_query_plan(
        precandidates,
        dependencies.entity_config,
        memberships,
        cutoff - timedelta(hours=request.lookback_hours),
        cutoff,
    )
    executions = await execute_news_query_plan(
        plan, dependencies.global_news, dependencies.keyword_news, dependencies.disclosure_news
    )
    documents = tuple(document for execution in executions for document in execution.documents)
    events = deduplicate_documents(documents)
    sector_rows = tuple(industry.data.sectors) + tuple(concept.data.sectors)
    stock_memberships = {
        code: tuple(
            sector_id
            for sector_id, members in memberships.items()
            if any(code == row[0] for row in members)
        )
        for members in memberships.values()
        for code, _name in members
    }
    links = resolve_sector_links(
        run.run_id,
        events,
        sector_rows,
        stock_memberships,
        dependencies.entity_config,
        {doc.document_id: doc for doc in documents},
    )
    sector_event_ids: dict[str, list[str]] = defaultdict(list)
    for link in links:
        sector_event_ids[link.sector_id].append(link.event_id)
    events = tuple(
        event.model_copy(
            update={
                "sector_ids": tuple(
                    sorted(
                        sector_id
                        for sector_id, ids in sector_event_ids.items()
                        if event.event_id in ids
                    )
                )
            }
        )
        for event in events
    )
    source_statuses: dict[str, DataStatus] = {}
    source_counts: defaultdict[str, int] = defaultdict(int)
    source_attempts: defaultdict[str, int] = defaultdict(int)
    source_errors: defaultdict[str, list[str]] = defaultdict(list)
    for execution in executions:
        source_statuses[execution.query.source_id] = execution.status
        source_counts[execution.query.source_id] += len(execution.documents)
        source_attempts[execution.query.source_id] += execution.attempts
        if execution.error_code:
            source_errors[execution.query.source_id].append(execution.error_code)
    news_quality = evaluate_news_quality(documents, events, source_statuses, cutoff)
    final_candidates = select_candidates(
        industry.data, concept.data, events, request.final_candidate_limit
    )
    packs = tuple(
        build_evidence_pack(candidate, (industry.data, concept.data), events, run.run_id)
        for candidate in final_candidates
    )
    SQLiteNewsRepository(database).save(documents, events)
    SQLiteEvidenceRepository(database).save(packs)
    SQLiteNewsRetrievalRepository(database).save_audit(
        run.run_id,
        (),
        tuple(
            (execution.query, execution.status, len(execution.documents), execution.error_code)
            for execution in executions
        ),
        links,
    )
    source_metrics = {
        source_id: SourceMetricSummary(
            status=status,
            call_count=sum(execution.query.source_id == source_id for execution in executions),
            retry_count=max(
                source_attempts[source_id]
                - sum(execution.query.source_id == source_id for execution in executions),
                0,
            ),
            duration_ms=0,
            document_count=source_counts[source_id],
            error_codes=tuple(sorted(set(source_errors[source_id]))),
        )
        for source_id, status in source_statuses.items()
    }
    unique_events = len(events)
    dedup_rate = 1 - unique_events / len(documents) if documents else 0.0
    mapping_rate = len(links) / unique_events if unique_events else 0.0
    return Phase1A2Report(
        run=run,
        run_kind=request.run_kind,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        market_quality=market_quality,
        news_quality=news_quality,
        market_precandidate_count=len(precandidates),
        final_candidate_count=len(final_candidates),
        source_metrics=source_metrics,
        document_count=len(documents),
        event_count=unique_events,
        link_count=len(links),
        deduplication_rate=dedup_rate,
        mapping_rate=mapping_rate,
        cutoff_violation_count=news_quality.excluded_after_cutoff_count,
        downgrade_reasons=news_quality.blocking_reasons,
        ready_for_phase1b=news_quality.status is not QualityStatus.BLOCKED,
        evidence_pack_count=len(packs),
    )
