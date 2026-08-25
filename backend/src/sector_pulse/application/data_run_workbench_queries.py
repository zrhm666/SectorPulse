from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, cast
from uuid import UUID

from sector_pulse.domain.market import SectorKind, SectorUniverseSnapshot
from sector_pulse.domain.news import NewsDocument, NewsEvent
from sector_pulse.domain.news_retrieval import (
    NewsQueryAuditRecord,
    NewsQueryDocumentLink,
    SectorEventLink,
    SourceRunMetric,
)
from sector_pulse.domain.provider import DataStatus
from sector_pulse.domain.real_data_run import RealDataCandidate, RealDataRun
from sector_pulse.storage.phase1b_runs_repository import Phase1BRunRow
from sector_pulse.storage.runtime_bundle import RuntimeStorageBundle


class MarketSnapshotReader(Protocol):
    def get(self, run_id: UUID, kind: SectorKind) -> SectorUniverseSnapshot | None: ...


class RealDataRunReader(Protocol):
    def get_run(self, run_id: UUID) -> RealDataRun | None: ...

    def get_candidates(self, run_id: UUID) -> list[RealDataCandidate]: ...


class NewsRetrievalReader(Protocol):
    def list_links(self, run_id: UUID) -> tuple[SectorEventLink, ...]: ...

    def list_query_documents(self, run_id: UUID) -> tuple[NewsQueryDocumentLink, ...]: ...

    def list_queries(self, run_id: UUID) -> tuple[NewsQueryAuditRecord, ...]: ...

    def list_source_metrics(self, run_id: UUID) -> tuple[SourceRunMetric, ...]: ...


class NewsReader(Protocol):
    def get_events(self, event_ids: Sequence[str]) -> tuple[NewsEvent, ...]: ...

    def get_documents(self, document_ids: Sequence[str]) -> dict[str, NewsDocument]: ...


class ContentRunReader(Protocol):
    def get_run(self, run_id: UUID) -> Phase1BRunRow | None: ...


class DataRunWorkbenchQueries:
    """Read persisted workbench data without invoking market, news, or LLM providers."""

    def __init__(self, storage: RuntimeStorageBundle) -> None:
        self._market_snapshots = cast(MarketSnapshotReader, storage.market_snapshots)
        self._real_data_runs = cast(RealDataRunReader, storage.real_data_runs)
        self._news_retrieval = cast(NewsRetrievalReader, storage.news_retrieval)
        self._news = cast(NewsReader, storage.news)
        self._content_runs = cast(ContentRunReader | None, storage.phase1b_runs)

    def market(
        self,
        run_id: UUID,
        kind: SectorKind,
        *,
        offset: int,
        limit: int,
    ) -> dict[str, object]:
        self._require_run(run_id)
        snapshots = self._snapshots(run_id)
        selected = snapshots.get(kind)
        sectors = selected.sectors if selected else ()
        items = []
        for sector in sectors[offset : offset + limit]:
            payload = sector.model_dump(mode="json")
            payload["sector_id"] = payload.pop("provider_sector_id")
            available = set(self._available_fields(selected)) if selected else set()
            payload["field_availability"] = {
                field: field in available
                for field in (
                    "pct_change",
                    "turnover_rate",
                    "total_market_cap",
                    "advancers",
                    "decliners",
                    "leader_name",
                    "leader_pct_change",
                )
            }
            items.append(payload)
        return {
            "snapshots": [self._snapshot_summary(snapshot) for snapshot in snapshots.values()],
            "kind": kind.value,
            "items": items,
            "total": len(sectors),
            "offset": offset,
            "limit": limit,
        }

    def candidates(self, run_id: UUID) -> list[dict[str, object]]:
        self._require_run(run_id)
        names = {
            (snapshot.kind, sector.provider_sector_id): sector.name
            for snapshot in self._snapshots(run_id).values()
            for sector in snapshot.sectors
        }
        result: list[dict[str, object]] = []
        for candidate in self._real_data_runs.get_candidates(run_id):
            payload = candidate.model_dump(mode="json")
            payload["name"] = names.get((candidate.sector_kind, candidate.sector_id))
            result.append(payload)
        return result

    def evidence(self, run_id: UUID) -> dict[str, object]:
        self._require_run(run_id)
        names = {
            (snapshot.kind, sector.provider_sector_id): sector.name
            for snapshot in self._snapshots(run_id).values()
            for sector in snapshot.sectors
        }
        links = self._news_retrieval.list_links(run_id)
        event_ids = tuple(dict.fromkeys(link.event_id for link in links))
        events_by_id = {event.event_id: event for event in self._news.get_events(event_ids)}
        document_ids = tuple(
            dict.fromkeys(
                document_id
                for event_id in event_ids
                if (event := events_by_id.get(event_id)) is not None
                for document_id in event.document_ids
            )
        )
        documents = self._news.get_documents(document_ids)
        items: list[dict[str, object]] = []
        for event_id in event_ids:
            event = events_by_id.get(event_id)
            if event is None:
                continue
            event_links = [link for link in links if link.event_id == event_id]
            items.append(
                {
                    "event_id": event.event_id,
                    "canonical_title": event.canonical_title,
                    "first_published_at": self._datetime(event.first_published_at),
                    "deduplication_reason": event.deduplication_reason,
                    "sector_ids": list(dict.fromkeys(link.sector_id for link in event_links)),
                    "links": [
                        {
                            **link.model_dump(mode="json"),
                            "sector_name": names.get((link.sector_kind, link.sector_id)),
                        }
                        for link in event_links
                    ],
                    "documents": [
                        self._document_summary(documents[document_id])
                        for document_id in event.document_ids
                        if document_id in documents
                    ],
                }
            )
        return {"events": items, "total": len(items)}

    def acquisition(self, run_id: UUID) -> dict[str, object]:
        self._require_run(run_id)
        snapshots = self._snapshots(run_id)
        queries = self._news_retrieval.list_queries(run_id)
        metrics = {
            item.source_id: item
            for item in self._news_retrieval.list_source_metrics(run_id)
        }
        query_documents = self._news_retrieval.list_query_documents(run_id)
        coverage = "COMPLETE" if metrics or query_documents else "LINKED_ONLY"
        linked_event_ids, linked_document_ids = self._linked_news_ids(run_id)
        normalized_document_ids = (
            {item.document_id for item in query_documents}
            if coverage == "COMPLETE"
            else linked_document_ids
        )
        source_ids = sorted({item.source_id for item in queries} | set(metrics))
        news_sources: list[dict[str, object]] = []
        for source_id in source_ids:
            source_queries = [item for item in queries if item.source_id == source_id]
            metric = metrics.get(source_id)
            statuses = {status.value: 0 for status in DataStatus}
            for item in source_queries:
                statuses[item.status.value] += 1
            news_sources.append(
                {
                    "source_id": source_id,
                    "status": (
                        metric.status.value
                        if metric
                        else self._aggregate_status(tuple(item.status for item in source_queries))
                    ),
                    "query_count": len(source_queries),
                    "status_counts": statuses,
                    "result_count": sum(item.result_count for item in source_queries),
                    "call_count": metric.call_count if metric else len(source_queries),
                    "retry_count": metric.retry_count if metric else 0,
                    "duration_ms": metric.duration_ms if metric else None,
                    "error_codes": sorted(
                        {
                            code
                            for code in (
                                *(item.error_code for item in source_queries),
                                metric.error_code if metric else None,
                            )
                            if code
                        }
                    ),
                }
            )
        return {
            "market_sources": [
                self._snapshot_summary(snapshot) for snapshot in snapshots.values()
            ],
            "news_sources": news_sources,
            "counts": {
                "provider_results": sum(item.result_count for item in queries),
                "normalized_documents": len(normalized_document_ids),
                "evidence_events": len(linked_event_ids),
            },
            "coverage": coverage,
            "coverage_notice": self._coverage_notice(coverage),
        }

    def news_records(
        self,
        run_id: UUID,
        *,
        source_id: str | None,
        status: DataStatus | None,
        offset: int,
        limit: int,
    ) -> dict[str, object]:
        self._require_run(run_id)
        queries = {item.query_id: item for item in self._news_retrieval.list_queries(run_id)}
        query_documents = self._news_retrieval.list_query_documents(run_id)
        metrics = self._news_retrieval.list_source_metrics(run_id)
        coverage = "COMPLETE" if metrics or query_documents else "LINKED_ONLY"
        rows: list[dict[str, object]] = []
        if coverage == "COMPLETE":
            document_ids = tuple(dict.fromkeys(item.document_id for item in query_documents))
            documents = self._news.get_documents(document_ids)
            for document_id in document_ids:
                document = documents.get(document_id)
                if document is None:
                    continue
                document_queries = [
                    queries[item.query_id]
                    for item in query_documents
                    if item.document_id == document_id and item.query_id in queries
                ]
                if source_id and not any(item.source_id == source_id for item in document_queries):
                    continue
                if status and not any(item.status is status for item in document_queries):
                    continue
                primary = document_queries[0] if document_queries else None
                rows.append(
                    {
                        **self._document_summary(document),
                        "query_ids": [item.query_id for item in document_queries],
                        "query_type": primary.query_type.value if primary else None,
                        "query_status": primary.status.value if primary else None,
                        "query_source_id": primary.source_id if primary else document.source_id,
                    }
                )
        else:
            _event_ids, linked_document_ids = self._linked_news_ids(run_id)
            documents = self._news.get_documents(tuple(sorted(linked_document_ids)))
            for document in documents.values():
                if source_id and document.source_id != source_id:
                    continue
                if status is not None:
                    continue
                rows.append(
                    {
                        **self._document_summary(document),
                        "query_ids": [],
                        "query_type": None,
                        "query_status": None,
                        "query_source_id": document.source_id,
                    }
                )
        rows.sort(
            key=lambda item: (
                str(item.get("published_at") or item.get("collected_at") or ""),
                str(item["document_id"]),
            ),
            reverse=True,
        )
        return {
            "items": rows[offset : offset + limit],
            "total": len(rows),
            "offset": offset,
            "limit": limit,
            "coverage": coverage,
            "coverage_notice": self._coverage_notice(coverage),
        }

    def quality(self, run_id: UUID) -> dict[str, object]:
        run = self._require_run(run_id)
        quality = run.quality.model_dump(mode="json")
        return {
            **quality,
            "error_code": run.error_code,
        }

    def content_run(self, run_id: UUID) -> dict[str, object] | None:
        self._require_run(run_id)
        if self._content_runs is None:
            return None
        content = self._content_runs.get_run(run_id)
        if content is None:
            return None
        return {
            "run_id": str(content.run_id),
            "status": content.status,
            "draft_id": str(content.draft_id) if content.draft_id else None,
            "can_view_draft": content.draft_id is not None,
            "requested_at": self._datetime(content.requested_at),
            "finished_at": self._datetime(content.finished_at),
        }

    def _require_run(self, run_id: UUID) -> RealDataRun:
        run = self._real_data_runs.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    def _snapshots(self, run_id: UUID) -> dict[SectorKind, SectorUniverseSnapshot]:
        snapshots: dict[SectorKind, SectorUniverseSnapshot] = {}
        for kind in SectorKind:
            snapshot = self._market_snapshots.get(run_id, kind)
            if snapshot is not None:
                snapshots[kind] = snapshot
        return snapshots

    @staticmethod
    def _snapshot_summary(snapshot: SectorUniverseSnapshot) -> dict[str, object]:
        return {
            "kind": snapshot.kind.value,
            "provider_id": snapshot.provider_id,
            "classification_version": snapshot.classification_version,
            "source_version": snapshot.source_version,
            "observed_at": DataRunWorkbenchQueries._datetime(snapshot.observed_at),
            "collected_at": DataRunWorkbenchQueries._datetime(snapshot.collected_at),
            "sector_count": snapshot.sector_count,
            "available_fields": DataRunWorkbenchQueries._available_fields(snapshot),
            "raw_artifact_sha256": snapshot.raw_artifact_sha256,
        }

    @staticmethod
    def _available_fields(snapshot: SectorUniverseSnapshot) -> list[str]:
        order = (
            "provider_sector_id",
            "name",
            "pct_change",
            "turnover_rate",
            "total_market_cap",
            "advancers",
            "decliners",
            "leader_name",
            "leader_pct_change",
        )
        if snapshot.available_fields:
            return [item for item in order if item in snapshot.available_fields]
        if snapshot.provider_id == "akshare-ths":
            return ["provider_sector_id", "name"]
        return []

    def _linked_news_ids(self, run_id: UUID) -> tuple[set[str], set[str]]:
        event_ids = {item.event_id for item in self._news_retrieval.list_links(run_id)}
        events = self._news.get_events(tuple(sorted(event_ids)))
        document_ids = {
            document_id for event in events for document_id in event.document_ids
        }
        return event_ids, document_ids

    @staticmethod
    def _aggregate_status(statuses: tuple[DataStatus, ...]) -> str:
        unique = set(statuses)
        if not unique:
            return DataStatus.UNAVAILABLE.value
        if len(unique) == 1:
            return next(iter(unique)).value
        if unique <= {DataStatus.SUCCESS, DataStatus.EMPTY}:
            return DataStatus.SUCCESS.value
        return DataStatus.PARTIAL.value

    @staticmethod
    def _coverage_notice(coverage: str) -> str | None:
        if coverage == "COMPLETE":
            return None
        return "该历史运行未记录完整查询与文档血缘，仅展示已进入证据链的新闻。"

    @staticmethod
    def _document_summary(document: NewsDocument) -> dict[str, object]:
        return {
            "document_id": document.document_id,
            "source_id": document.source_id,
            "citation_url": document.citation_url,
            "title": document.title,
            "publisher": document.publisher,
            "summary": document.summary,
            "published_at": DataRunWorkbenchQueries._datetime(document.published_at),
            "source_observed_at": DataRunWorkbenchQueries._datetime(document.source_observed_at),
            "collected_at": DataRunWorkbenchQueries._datetime(document.collected_at),
            "source_grade": document.source_grade.value,
        }

    @staticmethod
    def _datetime(value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.isoformat().replace("+00:00", "Z")
