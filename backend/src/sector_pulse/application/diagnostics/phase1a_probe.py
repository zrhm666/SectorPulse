import asyncio
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from sector_pulse.application.data_runs.candidate_selection import (
    build_evidence_pack,
    select_candidates,
)
from sector_pulse.application.news.news_ingestion import ingest_news
from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.provider import DataStatus
from sector_pulse.domain.quality import (
    QualityReport,
    QualityStatus,
    QualityThresholds,
    evaluate_universe,
    lock_cutoff_from_core_market,
)
from sector_pulse.domain.time import AnalysisMode, AnalysisRun
from sector_pulse.ports.market_data import MarketDataPort
from sector_pulse.ports.news import NewsPort
from sector_pulse.storage.evidence_repository import SQLiteEvidenceRepository
from sector_pulse.storage.market_snapshot_repository import SQLiteMarketSnapshotRepository
from sector_pulse.storage.news_repository import SQLiteNewsRepository
from sector_pulse.storage.sqlite import SQLiteDatabase


class Phase1AReport(BaseModel):
    """Phase 1A 只报告结构化链路状态，不包含新闻全文或模型输出。"""

    model_config = ConfigDict(frozen=True)

    run: AnalysisRun
    provider_id: str
    news_status: DataStatus
    industry_quality: QualityReport
    concept_quality: QualityReport
    event_count: int
    candidate_count: int
    evidence_pack_count: int
    usable: bool


async def run_phase1a_probe(
    provider: MarketDataPort,
    news_provider: NewsPort,
    database: SQLiteDatabase,
    requested_at: datetime,
    thresholds: QualityThresholds,
    source_ids: tuple[str, ...],
) -> Phase1AReport:
    """串联行情快照、新闻事件、候选和证据包，形成可审计垂直切片。"""
    database.initialize()
    run = AnalysisRun.create_live(requested_at)
    industry, concept = await asyncio.gather(
        provider.fetch_sector_universe(SectorKind.INDUSTRY, AnalysisMode.LIVE),
        provider.fetch_sector_universe(SectorKind.CONCEPT, AnalysisMode.LIVE),
    )
    industry_quality = evaluate_universe(industry, thresholds)
    concept_quality = evaluate_universe(concept, thresholds)
    if industry.data is None or concept.data is None:
        return Phase1AReport(
            run=run,
            provider_id=provider.manifest.provider_id,
            news_status=DataStatus.UNAVAILABLE,
            industry_quality=industry_quality,
            concept_quality=concept_quality,
            event_count=0,
            candidate_count=0,
            evidence_pack_count=0,
            usable=False,
        )
    locked_run = lock_cutoff_from_core_market(
        run,
        [industry, concept],
        datetime.now(UTC),
        120,
    )
    market_repository = SQLiteMarketSnapshotRepository(database)
    market_repository.save(locked_run, industry)
    market_repository.save(locked_run, concept)
    news_result = await ingest_news(
        news_provider,
        SQLiteNewsRepository(database),
        locked_run,
        source_ids,
    )
    events = news_result.data or ()
    candidates = select_candidates(industry.data, concept.data, events)
    snapshots = (industry.data, concept.data)
    packs = tuple(
        build_evidence_pack(candidate, snapshots, events, run_id=locked_run.run_id)
        for candidate in candidates
    )
    SQLiteEvidenceRepository(database).save(packs)
    return Phase1AReport(
        run=locked_run,
        provider_id=provider.manifest.provider_id,
        news_status=news_result.status,
        industry_quality=industry_quality,
        concept_quality=concept_quality,
        event_count=len(events),
        candidate_count=len(candidates),
        evidence_pack_count=len(packs),
        usable=industry_quality.status is not QualityStatus.BLOCKED
        and concept_quality.status is not QualityStatus.BLOCKED,
    )
