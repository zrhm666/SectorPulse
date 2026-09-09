"""Persist small, hand-checked comparison inputs through either real storage adapter."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sector_pulse.domain.market.market import SectorKind, SectorSnapshot, SectorUniverseSnapshot
from sector_pulse.domain.news.news import NewsDocument, NewsEvent, SourceGrade
from sector_pulse.domain.news.news_retrieval import (
    MappingConfidence,
    NewsQuery,
    NewsQueryDocumentLink,
    QueryType,
    SectorEventLink,
)
from sector_pulse.domain.provider import DataStatus, ProviderResult
from sector_pulse.domain.runs.real_data_run import (
    RealDataCandidate,
    RealDataRun,
    RealDataRunRequest,
    RealDataRunStatus,
)
from sector_pulse.domain.runs.time import AnalysisRun
from sector_pulse.storage.runtime_bundle import RuntimeStorageBundle

NOW = datetime(2026, 9, 7, 1, tzinfo=UTC)
FIELDS = frozenset(
    {
        "provider_sector_id",
        "name",
        "pct_change",
        "turnover_rate",
        "advancers",
        "decliners",
        "leader_name",
    }
)


def save_snapshot(
    storage: RuntimeStorageBundle, run_id: UUID, snapshot: SectorUniverseSnapshot
) -> None:
    run = AnalysisRun.create_live(snapshot.observed_at, run_id=run_id).lock_live_cutoff(
        snapshot.observed_at, snapshot.collected_at
    )
    storage.market_snapshots.save(
        run,
        ProviderResult(
            provider_id=snapshot.provider_id,
            capability="comparison-fixture",
            status=DataStatus.SUCCESS,
            data=snapshot,
            observed_at=snapshot.observed_at,
            collected_at=snapshot.collected_at,
            source_version=snapshot.source_version,
        ),
    )


def seed_pair(storage: RuntimeStorageBundle) -> tuple[RealDataRun, RealDataRun]:
    runs = tuple(
        RealDataRun(
            provider="fixture",
            request=RealDataRunRequest(mode="post_close", requested_at=NOW + timedelta(days=index)),
            cutoff_at=NOW + timedelta(days=index),
            status=RealDataRunStatus.READY_FOR_ATTRIBUTION,
            finished_at=NOW + timedelta(days=index, minutes=1),
        )
        for index in range(2)
    )
    for index, run in enumerate(runs):
        storage.real_data_runs.insert(run)
        candidates = [
            RealDataCandidate(
                sector_id="001",
                sector_kind=SectorKind.INDUSTRY,
                rank=5 if index == 0 else 2,
                score=Decimal("0.50"),
                reasons=(),
            ),
            RealDataCandidate(
                sector_id="concept-001",
                sector_kind=SectorKind.CONCEPT,
                rank=1 if index == 0 else 4,
                score=Decimal("0.60"),
                reasons=(),
            ),
            RealDataCandidate(
                sector_id="002" if index == 0 else "003",
                sector_kind=SectorKind.INDUSTRY,
                rank=6 if index == 0 else 1,
                score=Decimal("0.40"),
                reasons=(),
            ),
        ]
        storage.real_data_runs.save_candidates(run.run_id, tuple(candidates))
        for kind in SectorKind:
            snapshot = SectorUniverseSnapshot(
                provider_id="fixture-market",
                classification_version="stable-v1",
                source_version="fixture-v1",
                kind=kind,
                observed_at=run.cutoff_at,
                collected_at=run.finished_at,
                available_fields=FIELDS,
                sectors=tuple(
                    SectorSnapshot(
                        provider_sector_id=sector_id,
                        name=f"{kind.value}-{sector_id}",
                        kind=kind,
                        pct_change=Decimal("0.10") if index else Decimal("0"),
                        turnover_rate=Decimal("1.5") if index else None,
                        advancers=0,
                        decliners=5,
                        leader_name="示例领涨股",
                    )
                    for sector_id in (
                        ("001", "002", "003")
                        if kind == SectorKind.INDUSTRY
                        else ("concept-001", "002", "003")
                    )
                ),
            )
            save_snapshot(storage, run.run_id, snapshot)
    return runs[0], runs[1]


def seed_news(
    storage: RuntimeStorageBundle,
    base_id: UUID,
    compare_id: UUID,
    *,
    count: int = 3,
    lineage: bool = True,
) -> tuple[list[str], str]:
    prefix = str(uuid4())
    ids = [f"{prefix}-{index:03}" for index in range(count)]
    documents = [
        NewsDocument(
            document_id=key,
            source_id="fixture-news",
            canonical_locator=f"https://example.com/{key}",
            citation_url="javascript:alert(1)" if index == 0 else f"https://example.com/{key}",
            title="同标题",
            summary="留存摘要",
            publisher="示例媒体",
            published_at=NOW,
            collected_at=NOW,
            content_hash=key,
            source_grade=SourceGrade.REPUTABLE_MEDIA,
        )
        for index, key in enumerate(ids)
    ]
    event_id = f"{prefix}-event"
    storage.news.save(
        documents,
        [
            NewsEvent(
                event_id=event_id,
                canonical_title="当前事件标题",
                first_published_at=NOW,
                document_ids=tuple(ids),
                deduplication_reason="fixture",
            )
        ],
    )
    for index, run_id in enumerate((base_id, compare_id)):
        member_ids = ids[:-1] if index == 0 else ids[1:]
        query = NewsQuery(
            query_id="q1",
            query_type=QueryType.GLOBAL,
            source_id="fixture-news",
            value="fixture",
            priority=1,
            start_at=NOW,
            cutoff_at=NOW,
        )
        links = [
            SectorEventLink(
                run_id=run_id,
                event_id=event_id,
                sector_id="001" if kind == SectorKind.INDUSTRY else "concept-001",
                sector_kind=kind,
                relation_type="mention",
                matched_entities=("001",),
                mapping_confidence=MappingConfidence.HIGH if index == 0 else MappingConfidence.LOW,
                mapping_reason=f"saved-{index}-{kind.value}",
                rule_version=f"v{index + 1}",
            )
            for kind in (SectorKind.INDUSTRY, SectorKind.CONCEPT)
            if index == 0 or kind == SectorKind.INDUSTRY
        ]
        storage.news_retrieval.save_audit(
            run_id,
            (),
            [(query, DataStatus.SUCCESS, len(member_ids), None)],
            links,
            tuple(
                NewsQueryDocumentLink(run_id=run_id, query_id="q1", document_id=key)
                for key in member_ids
            )
            if lineage
            else (),
        )
    return ids, event_id
