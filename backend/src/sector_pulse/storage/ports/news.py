from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable
from uuid import UUID

from sector_pulse.domain.news.evidence import EvidencePack
from sector_pulse.domain.news.news import NewsDocument, NewsEvent
from sector_pulse.domain.news.news_batch import NewsBatch
from sector_pulse.domain.news.news_retrieval import (
    NewsQuery,
    NewsQueryAuditRecord,
    NewsQueryDocumentLink,
    SectorEventLink,
    SourceRunMetric,
)
from sector_pulse.domain.news.research import NewsDetailSnapshot, ResearchSearchBatch
from sector_pulse.domain.provider import DataStatus
from sector_pulse.storage.sqlite.news.news_evidence_repository import NewsEvidenceItem


@runtime_checkable
class NewsRepositoryPort(Protocol):
    def save(self, documents: Sequence[NewsDocument], events: Sequence[NewsEvent]) -> None: ...

    def get_event(self, event_id: str) -> NewsEvent | None: ...

    def get_events(self, event_ids: Sequence[str]) -> tuple[NewsEvent, ...]: ...

    def get_documents(self, document_ids: Sequence[str]) -> dict[str, NewsDocument]: ...


@runtime_checkable
class NewsBatchRepositoryPort(Protocol):
    def get(self, batch_id: UUID) -> NewsBatch | None: ...


@runtime_checkable
class ResearchSearchRepositoryPort(Protocol):
    def get(self, batch_id: UUID) -> ResearchSearchBatch | None: ...


@runtime_checkable
class NewsDetailSnapshotRepositoryPort(Protocol):
    def get(self, detail_id: UUID) -> NewsDetailSnapshot | None: ...



@runtime_checkable
class EvidenceRepositoryPort(Protocol):
    def save(self, packs: Sequence[EvidencePack]) -> None: ...

    def list_for_run(self, run_id: UUID) -> tuple[EvidencePack, ...]: ...



@runtime_checkable
class NewsRetrievalRepositoryPort(Protocol):
    def save_audit(
        self,
        run_id: UUID,
        metrics: Sequence[SourceRunMetric],
        query_results: Sequence[tuple[NewsQuery, DataStatus, int, str | None]],
        links: Sequence[SectorEventLink],
        query_documents: Sequence[NewsQueryDocumentLink] = (),
    ) -> None: ...

    def list_links(self, run_id: UUID) -> tuple[SectorEventLink, ...]: ...

    def list_query_documents(self, run_id: UUID) -> tuple[NewsQueryDocumentLink, ...]: ...

    def list_queries(self, run_id: UUID) -> tuple[NewsQueryAuditRecord, ...]: ...

    def list_source_metrics(self, run_id: UUID) -> tuple[SourceRunMetric, ...]: ...



@runtime_checkable
class NewsEvidenceRepositoryPort(Protocol):
    def get_events(self, event_ids: tuple[str, ...]) -> tuple[NewsEvidenceItem, ...]: ...
