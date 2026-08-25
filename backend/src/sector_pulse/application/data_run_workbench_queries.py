from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, cast
from uuid import UUID

from sector_pulse.domain.market import SectorKind, SectorUniverseSnapshot
from sector_pulse.domain.news import NewsDocument, NewsEvent
from sector_pulse.domain.news_retrieval import SectorEventLink
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
                    "links": [link.model_dump(mode="json") for link in event_links],
                    "documents": [
                        self._document_summary(documents[document_id])
                        for document_id in event.document_ids
                        if document_id in documents
                    ],
                }
            )
        return {"events": items, "total": len(items)}

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
        }

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
