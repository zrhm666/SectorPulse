from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sector_pulse.application.data_run_workbench_queries import DataRunWorkbenchQueries
from sector_pulse.domain.candidate_selection import candidate_data_version
from sector_pulse.domain.market import SectorKind, SectorSnapshot, SectorUniverseSnapshot
from sector_pulse.domain.news import NewsDocument, NewsEvent, SourceGrade
from sector_pulse.domain.news_retrieval import (
    MappingConfidence,
    NewsQuery,
    NewsQueryDocumentLink,
    QueryType,
    SectorEventLink,
    SourceRunMetric,
)
from sector_pulse.domain.provider import DataStatus, ProviderResult
from sector_pulse.domain.quality import QualityStatus
from sector_pulse.domain.real_data_run import (
    RealDataCandidate,
    RealDataQualitySummary,
    RealDataRun,
    RealDataRunRequest,
    RealDataRunStatus,
)
from sector_pulse.domain.time import AnalysisRun
from sector_pulse.storage.phase1b_runs_repository import Phase1BRunRow
from sector_pulse.storage.runtime_bundle import RuntimeStorageBundle, build_sqlite_storage
from sector_pulse.storage.sqlite import SQLiteDatabase

NOW = datetime(2026, 8, 25, 7, 0, tzinfo=UTC)


def _snapshot(kind: SectorKind, names: tuple[str, ...]) -> SectorUniverseSnapshot:
    return SectorUniverseSnapshot(
        provider_id="fixture-market",
        classification_version="2026-08-25",
        source_version="fixture-v1",
        kind=kind,
        observed_at=NOW,
        collected_at=NOW,
        available_fields=frozenset(
            {
                "provider_sector_id",
                "name",
                "pct_change",
                "turnover_rate",
                "advancers",
                "decliners",
                "leader_name",
                "leader_pct_change",
            }
        ),
        raw_artifact_sha256=f"hash-{kind.value.lower()}",
        sectors=tuple(
            SectorSnapshot(
                provider_sector_id=f"{kind.value.lower()}-{index}",
                name=name,
                kind=kind,
                pct_change=Decimal(str(index)),
                turnover_rate=Decimal("1.2"),
                advancers=10,
                decliners=5,
                leader_name=f"{name}龙头",
                leader_pct_change=Decimal("3.1"),
            )
            for index, name in enumerate(names, start=1)
        ),
    )


def _save_snapshot(
    storage: RuntimeStorageBundle,
    analysis_run: AnalysisRun,
    snapshot: SectorUniverseSnapshot,
) -> None:
    storage.market_snapshots.save(
        analysis_run,
        ProviderResult(
            provider_id=snapshot.provider_id,
            capability=f"sector_universe.{snapshot.kind.value.lower()}",
            status=DataStatus.SUCCESS,
            data=snapshot,
            observed_at=snapshot.observed_at,
            collected_at=snapshot.collected_at,
            source_version=snapshot.source_version,
        ),
    )


def _seed(
    tmp_path: Path,
    *,
    with_content_run: bool = True,
    with_lineage: bool = True,
) -> tuple[DataRunWorkbenchQueries, RealDataRun]:
    storage = build_sqlite_storage(SQLiteDatabase(tmp_path / "workbench.sqlite"))
    run_id = uuid4()
    run = RealDataRun(
        run_id=run_id,
        provider="fixture",
        request=RealDataRunRequest(mode="intraday", requested_at=NOW),
        status=RealDataRunStatus.READY_FOR_ATTRIBUTION,
        cutoff_at=NOW,
        quality=RealDataQualitySummary(
            market_quality={"industry": QualityStatus.NORMAL},
            news_quality={"news": QualityStatus.DEGRADED},
            cutoff_violation_count=1,
            duplicate_document_count=2,
            downgrade_reasons=("NEWS_SOURCE_PARTIAL",),
        ),
    )
    storage.real_data_runs.insert(run)
    storage.real_data_runs.save_candidates(
        run_id,
        (
            RealDataCandidate(
                sector_id="industry-1",
                sector_kind=SectorKind.INDUSTRY,
                rank=2,
                score=Decimal("8.0"),
                reasons=("成交活跃",),
            ),
            RealDataCandidate(
                sector_id="industry-2",
                sector_kind=SectorKind.INDUSTRY,
                rank=1,
                score=Decimal("9.8"),
                reasons=("涨幅领先",),
            ),
            RealDataCandidate(
                sector_id="industry-3",
                sector_kind=SectorKind.INDUSTRY,
                rank=3,
                score=Decimal("8.0"),
                reasons=("新闻升温",),
            ),
        ),
    )
    analysis_run = AnalysisRun.create_live(NOW, run_id=run_id).lock_live_cutoff(NOW, NOW)
    _save_snapshot(
        storage,
        analysis_run,
        _snapshot(SectorKind.INDUSTRY, ("行业一", "行业二", "行业三")),
    )
    _save_snapshot(storage, analysis_run, _snapshot(SectorKind.CONCEPT, ("概念一",)))

    linked_document = NewsDocument(
        document_id="doc-linked",
        source_id="fixture-news",
        canonical_locator="https://example.com/linked",
        citation_url="https://example.com/linked",
        title="关联新闻",
        publisher="示例媒体",
        summary="只返回摘要，不返回正文。",
        published_at=NOW,
        source_observed_at=NOW,
        collected_at=NOW,
        content_hash="a" * 64,
        source_grade=SourceGrade.REPUTABLE_MEDIA,
    )
    unrelated_document = linked_document.model_copy(
        update={
            "document_id": "doc-unrelated",
            "canonical_locator": "https://example.com/unrelated",
            "citation_url": "javascript:alert(1)",
            "title": "无关新闻",
            "summary": None,
            "content_hash": "b" * 64,
        }
    )
    linked_event = NewsEvent(
        event_id="event-linked",
        canonical_title="关联新闻事件",
        first_published_at=NOW,
        document_ids=(linked_document.document_id,),
        deduplication_reason="canonical_url",
    )
    unrelated_event = NewsEvent(
        event_id="event-unrelated",
        canonical_title="无关新闻事件",
        first_published_at=NOW,
        document_ids=(unrelated_document.document_id,),
        deduplication_reason="canonical_url",
    )
    storage.news.save((linked_document, unrelated_document), (linked_event, unrelated_event))
    linked_query = NewsQuery(
        query_id="query-linked",
        query_type=QueryType.KEYWORD,
        source_id="fixture-news",
        value="linked",
        sector_ids=("industry-2",),
        priority=10,
        start_at=NOW,
        cutoff_at=NOW,
    )
    unrelated_query = linked_query.model_copy(
        update={
            "query_id": "query-unrelated",
            "source_id": "other-news",
            "value": "unrelated",
            "sector_ids": (),
        }
    )
    metrics = (
        SourceRunMetric(
            run_id=run_id,
            source_id="fixture-news",
            started_at=NOW,
            completed_at=NOW,
            call_count=1,
            retry_count=0,
            status=DataStatus.SUCCESS,
            duration_ms=12,
        ),
        SourceRunMetric(
            run_id=run_id,
            source_id="other-news",
            started_at=NOW,
            completed_at=NOW,
            call_count=1,
            retry_count=1,
            status=DataStatus.PARTIAL,
            duration_ms=18,
            error_code="UPSTREAM_PARTIAL",
        ),
    )
    query_documents = (
        (
            NewsQueryDocumentLink(
                run_id=run_id,
                query_id=linked_query.query_id,
                document_id=linked_document.document_id,
            ),
            NewsQueryDocumentLink(
                run_id=run_id,
                query_id=unrelated_query.query_id,
                document_id=unrelated_document.document_id,
            ),
        )
        if with_lineage
        else ()
    )
    storage.news_retrieval.save_audit(
        run_id,
        metrics if with_lineage else (),
        (
            (linked_query, DataStatus.SUCCESS, 1, None),
            (unrelated_query, DataStatus.PARTIAL, 1, "UPSTREAM_PARTIAL"),
        ),
        (
            SectorEventLink(
                run_id=run_id,
                event_id=linked_event.event_id,
                sector_id="industry-2",
                sector_kind=SectorKind.INDUSTRY,
                relation_type="alias",
                matched_entities=("行业二",),
                mapping_confidence=MappingConfidence.HIGH,
                mapping_reason="名称命中",
                rule_version="fixture-v1",
            ),
        ),
        query_documents,
    )
    if with_content_run:
        storage.phase1b_runs.insert(
            Phase1BRunRow(
                run_id=run_id,
                requested_at=NOW,
                provider="fixture",
                status="READY_FOR_HUMAN_REVIEW",
                draft_id=uuid4(),
            )
        )
    return DataRunWorkbenchQueries(storage), run


def test_market_paginates_and_candidates_resolve_names(tmp_path: Path) -> None:
    queries, run = _seed(tmp_path)

    market = queries.market(run.run_id, SectorKind.INDUSTRY, offset=1, limit=1)

    assert [item["name"] for item in market["items"]] == ["行业二"]
    assert market["total"] == 3
    assert market["offset"] == 1
    assert {item["kind"] for item in market["snapshots"]} == {"INDUSTRY", "CONCEPT"}
    candidates = queries.candidates(
        run.run_id,
        query=None,
        sort="rank",
        direction="asc",
        offset=0,
        limit=20,
    )
    assert candidates["items"][0]["name"] == "行业二"


def test_candidates_search_sort_page_and_expose_persisted_facts(tmp_path: Path) -> None:
    queries, run = _seed(tmp_path)

    result = queries.candidates(
        run.run_id,
        query="行业",
        sort="score",
        direction="desc",
        offset=1,
        limit=1,
    )

    assert result["total"] == 3
    assert result["offset"] == 1
    assert result["limit"] == 1
    assert result["query"] == "行业"
    assert result["sort"] == "score"
    assert result["direction"] == "desc"
    assert result["items"][0]["sector_id"] == "industry-1"
    assert result["items"][0]["pct_change"] == "1"
    assert result["items"][0]["news_count"] == 0
    assert result["data_version"] == candidate_data_version(
        tuple(queries._real_data_runs.get_candidates(run.run_id))
    )


def test_candidates_use_rank_as_a_stable_tie_breaker(tmp_path: Path) -> None:
    queries, run = _seed(tmp_path)

    result = queries.candidates(
        run.run_id,
        query=None,
        sort="score",
        direction="desc",
        offset=0,
        limit=20,
    )

    assert [item["sector_id"] for item in result["items"]] == [
        "industry-2",
        "industry-1",
        "industry-3",
    ]
    assert result["items"][0]["news_count"] == 1


def test_evidence_returns_only_events_linked_to_the_run(tmp_path: Path) -> None:
    queries, run = _seed(tmp_path)

    result = queries.evidence(run.run_id)

    assert [item["event_id"] for item in result["events"]] == ["event-linked"]
    assert result["events"][0]["sector_ids"] == ["industry-2"]
    document = result["events"][0]["documents"][0]
    assert document["title"] == "关联新闻"
    assert document["summary"] == "只返回摘要，不返回正文。"
    assert document["content"] == "只返回摘要，不返回正文。"
    assert document["content_kind"] == "SUMMARY"


def test_quality_and_content_run_are_restored(tmp_path: Path) -> None:
    queries, run = _seed(tmp_path)

    quality = queries.quality(run.run_id)
    content_run = queries.content_run(run.run_id)

    assert quality["cutoff_violation_count"] == 1
    assert quality["duplicate_document_count"] == 2
    assert quality["downgrade_reasons"] == ["NEWS_SOURCE_PARTIAL"]
    assert content_run is not None
    assert content_run["status"] == "READY_FOR_HUMAN_REVIEW"
    assert content_run["can_view_draft"] is True


def test_content_run_is_none_when_phase1b_has_not_started(tmp_path: Path) -> None:
    queries, run = _seed(tmp_path, with_content_run=False)

    assert queries.content_run(run.run_id) is None


def test_acquisition_distinguishes_provider_normalized_and_evidence_counts(
    tmp_path: Path,
) -> None:
    queries, run = _seed(tmp_path)

    result = queries.acquisition(run.run_id)

    assert [item["sector_count"] for item in result["market_sources"]] == [3, 1]
    assert result["market_sources"][0]["raw_artifact_sha256"] == "hash-industry"
    assert {item["source_id"] for item in result["news_sources"]} == {
        "fixture-news",
        "other-news",
    }
    assert result["counts"] == {
        "provider_results": 2,
        "normalized_documents": 2,
        "evidence_events": 1,
    }
    assert result["coverage"] == "COMPLETE"


def test_news_records_are_run_scoped_filtered_and_paginated(tmp_path: Path) -> None:
    queries, run = _seed(tmp_path)

    result = queries.news_records(
        run.run_id,
        source_id="other-news",
        status=DataStatus.PARTIAL,
        offset=0,
        limit=1,
    )

    assert result["coverage"] == "COMPLETE"
    assert result["total"] == 1
    assert result["items"][0]["document_id"] == "doc-unrelated"
    assert result["items"][0]["query_status"] == "PARTIAL"


def test_news_detail_labels_saved_summary_and_rejects_unsafe_links(tmp_path: Path) -> None:
    queries, run = _seed(tmp_path)

    linked = queries.news_record(run.run_id, "doc-linked")
    unrelated = queries.news_record(run.run_id, "doc-unrelated")

    assert linked["content_kind"] == "SUMMARY"
    assert linked["content_available"] is True
    assert linked["content"] == "只返回摘要，不返回正文。"
    assert linked["citation_url"] == "https://example.com/linked"
    assert unrelated["citation_url"] is None


def test_news_detail_returns_link_only_and_null_for_unsafe_url(tmp_path: Path) -> None:
    queries, run = _seed(tmp_path)

    detail = queries.news_record(run.run_id, "doc-unrelated")

    assert detail["content_kind"] == "LINK_ONLY"
    assert detail["content_available"] is False
    assert detail["content"] is None
    assert detail["citation_url"] is None


def test_cls_summary_is_truthfully_labeled_as_flash(tmp_path: Path) -> None:
    queries, _run = _seed(tmp_path)
    document = NewsDocument(
        document_id="doc-flash",
        source_id="cls",
        canonical_locator="urn:flash:1",
        title="盘中快讯",
        summary="板块异动。",
        published_at=NOW,
        collected_at=NOW,
        content_hash="c" * 64,
        source_grade=SourceGrade.REPUTABLE_MEDIA,
    )

    detail = queries._document_summary(document)

    assert detail["content_kind"] == "FLASH"
    assert detail["content"] == "板块异动。"


def test_workflow_summary_is_derived_from_persisted_run_state(tmp_path: Path) -> None:
    queries, run = _seed(tmp_path)

    summary = queries.summary(run.run_id)

    assert summary["status"] == "READY_FOR_ATTRIBUTION"
    assert summary["workflow_stage"] == "ATTRIBUTION_READY"
    assert summary["workflow_stage_index"] == 5
    assert summary["terminal"] is True
    assert summary["candidate_count"] == 3


def test_historical_news_records_are_explicitly_linked_only(tmp_path: Path) -> None:
    queries, run = _seed(tmp_path, with_lineage=False)

    result = queries.news_records(run.run_id, source_id=None, status=None, offset=0, limit=20)

    assert result["coverage"] == "LINKED_ONLY"
    assert result["total"] == 1
    assert result["items"][0]["document_id"] == "doc-linked"
    assert result["coverage_notice"]
