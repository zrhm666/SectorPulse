"""Bounded research-news tools for one server-owned A2 scope."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from sector_pulse.application.news.news_ingestion import deduplicate_documents
from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter
from sector_pulse.application.orchestration.data_tools import require_live_task_owner
from sector_pulse.application.orchestration.research_context import BoundSectorResearchContext
from sector_pulse.domain.news.news import NewsDocument, NewsEvent, NewsUse
from sector_pulse.domain.news.research import (
    NewsDetailSnapshot,
    ResearchSearchBatch,
    ResearchSearchStatus,
)
from sector_pulse.domain.orchestration.models import ArtifactRef
from sector_pulse.domain.provider import DataStatus
from sector_pulse.ports.news_detail import NewsDetailPort
from sector_pulse.ports.news_sources import KeywordNewsSearchPort
from sector_pulse.ports.orchestration import SnapshotRepository, TransactionSession
from sector_pulse.storage.ports.news import (
    NewsBatchRepositoryPort,
    NewsRepositoryPort,
    ResearchSearchRepositoryPort,
)


def research_search_artifact_id(batch: ResearchSearchBatch) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"research-search-artifact:{batch.batch_id}:{batch.task_id}:{batch.attempt}",
    )


def news_detail_artifact_id(snapshot: NewsDetailSnapshot) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"news-detail-artifact:{snapshot.detail_id}:{snapshot.task_id}:{snapshot.attempt}",
    )


class ResearchSearchPersistence:
    def __init__(
        self,
        batch: ResearchSearchBatch,
        documents: tuple[NewsDocument, ...],
        events: tuple[NewsEvent, ...],
    ) -> None:
        self._batch = batch
        self._documents = documents
        self._events = events

    def write(self, session: TransactionSession, artifact: object) -> None:
        del artifact
        for document in self._documents:
            session.execute(
                "INSERT INTO news_documents (document_id, source_id, canonical_url, title, "
                "published_at, observed_at, content_hash, source_grade, metadata_json, "
                "citation_url, publisher, summary, source_observed_at, use_grade, "
                "quality_flags_json) VALUES (:document_id, :source_id, :canonical_url, :title, "
                ":published_at, :observed_at, :content_hash, :source_grade, :metadata_json, "
                ":citation_url, :publisher, :summary, :source_observed_at, :use_grade, '[]') "
                "ON CONFLICT(document_id) DO UPDATE SET title=excluded.title, "
                "observed_at=excluded.observed_at, citation_url=excluded.citation_url, "
                "publisher=excluded.publisher, summary=excluded.summary, "
                "source_observed_at=excluded.source_observed_at, "
                "metadata_json=excluded.metadata_json",
                {
                    "document_id": document.document_id,
                    "source_id": document.source_id,
                    "canonical_url": document.canonical_locator,
                    "title": document.title,
                    "published_at": document.published_at.isoformat()
                    if document.published_at
                    else None,
                    "observed_at": document.collected_at.isoformat(),
                    "content_hash": document.content_hash,
                    "source_grade": document.source_grade.value,
                    "metadata_json": document.model_dump_json(),
                    "citation_url": document.citation_url,
                    "publisher": document.publisher,
                    "summary": document.summary,
                    "source_observed_at": document.source_observed_at.isoformat()
                    if document.source_observed_at
                    else None,
                    "use_grade": document.use_at(self._batch.cutoff_at).value,
                },
            )
        for event in self._events:
            session.execute(
                "INSERT INTO news_events (event_id, canonical_title, first_published_at, "
                "deduplication_reason, metadata_json) VALUES (:event_id, :title, :published_at, "
                ":reason, :metadata_json) ON CONFLICT(event_id) DO UPDATE SET "
                "canonical_title=excluded.canonical_title, metadata_json=excluded.metadata_json",
                {
                    "event_id": event.event_id,
                    "title": event.canonical_title,
                    "published_at": event.first_published_at.isoformat()
                    if event.first_published_at
                    else None,
                    "reason": event.deduplication_reason,
                    "metadata_json": event.model_dump_json(),
                },
            )
            for document_id in event.document_ids:
                session.execute(
                    "INSERT INTO news_event_documents (event_id, document_id) VALUES "
                    "(:event_id, :document_id) ON CONFLICT(event_id, document_id) DO NOTHING",
                    {"event_id": event.event_id, "document_id": document_id},
                )
        batch = self._batch
        session.execute(
            "INSERT INTO research_search_batches (batch_id, run_id, task_id, attempt, sector_id, "
            "sector_kind, query_text, start_at, cutoff_at, input_fingerprint, status, error_code, "
            "document_count, event_count, payload_json, created_at) VALUES (:batch_id, :run_id, "
            ":task_id, :attempt, :sector_id, :sector_kind, :query_text, :start_at, :cutoff_at, "
            ":fingerprint, :status, :error_code, :document_count, :event_count, :payload, "
            ":created_at)",
            {
                "batch_id": str(batch.batch_id),
                "run_id": str(batch.run_id),
                "task_id": str(batch.task_id),
                "attempt": batch.attempt,
                "sector_id": batch.sector_id,
                "sector_kind": batch.sector_kind.value,
                "query_text": batch.query,
                "start_at": batch.start_at.isoformat(),
                "cutoff_at": batch.cutoff_at.isoformat(),
                "fingerprint": batch.input_fingerprint,
                "status": batch.status.value,
                "error_code": batch.error_code,
                "document_count": len(batch.document_ids),
                "event_count": len(batch.event_ids),
                "payload": batch.model_dump_json(),
                "created_at": batch.created_at.isoformat(),
            },
        )
        for document_id in batch.document_ids:
            session.execute(
                "INSERT INTO research_search_documents (batch_id, document_id) VALUES "
                "(:batch_id, :document_id)",
                {"batch_id": str(batch.batch_id), "document_id": document_id},
            )
        for event_id in batch.event_ids:
            session.execute(
                "INSERT INTO research_search_events (batch_id, event_id) VALUES "
                "(:batch_id, :event_id)",
                {"batch_id": str(batch.batch_id), "event_id": event_id},
            )

    def exists(self, session: TransactionSession, artifact: object) -> bool:
        del artifact
        return bool(
            session.rows(
                "SELECT 1 FROM research_search_batches WHERE batch_id=:batch_id",
                {"batch_id": str(self._batch.batch_id)},
            )
        )


class SearchSectorNewsService:
    def __init__(
        self,
        *,
        search: KeywordNewsSearchPort,
        orchestration: SnapshotRepository,
        committer: AtomicArtifactCommitter,
    ) -> None:
        self._search = search
        self._orchestration = orchestration
        self._committer = committer

    async def search(
        self,
        *,
        context: BoundSectorResearchContext,
        query: str,
        now: datetime | None = None,
    ) -> ResearchSearchBatch:
        created_at = now or datetime.now(UTC)
        require_live_task_owner(
            self._orchestration,
            context.run_id,
            task_id=context.task_id,
            attempt=context.attempt,
            worker_id=context.worker_id,
            now=created_at,
        )
        normalized = " ".join(query.split())
        if not 2 <= len(normalized) <= 120:
            raise ValueError("research query length is invalid")
        bound_query = (
            normalized
            if context.sector_name in normalized
            else f"{context.sector_name} {normalized}"
        )
        start_at = context.cutoff_at - timedelta(days=7)
        try:
            result = await self._search.search(bound_query, start_at, context.cutoff_at)
            raw_documents = result.data or ()
            if result.status is DataStatus.SUCCESS:
                status = ResearchSearchStatus.SUCCESS
                error_code = None
            elif result.status is DataStatus.EMPTY:
                status = ResearchSearchStatus.EMPTY
                error_code = None
            else:
                status = ResearchSearchStatus.FAILED
                error_code = {
                    DataStatus.PARTIAL: "NEWS_SEARCH_PARTIAL",
                    DataStatus.STALE: "NEWS_SEARCH_STALE",
                    DataStatus.UNAVAILABLE: "NEWS_SEARCH_UNAVAILABLE",
                }.get(result.status, "NEWS_SEARCH_FAILED")
        except Exception:
            raw_documents = ()
            status = ResearchSearchStatus.FAILED
            error_code = "NEWS_SEARCH_FAILED"
        documents = tuple(
            document
            for document in raw_documents
            if document.use_at(context.cutoff_at) is not NewsUse.EXCLUDED
            and (document.published_at is None or document.published_at >= start_at)
        )[:10]
        if status is not ResearchSearchStatus.FAILED and not documents:
            status = ResearchSearchStatus.EMPTY
        events = tuple(
            event.model_copy(update={"sector_ids": (context.sector_id,)})
            for event in deduplicate_documents(documents)
        )
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "task_id": str(context.task_id),
                    "attempt": context.attempt,
                    "sector_id": context.sector_id,
                    "sector_kind": context.sector_kind.value,
                    "query": bound_query,
                    "start_at": start_at.isoformat(),
                    "cutoff_at": context.cutoff_at.isoformat(),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        batch = ResearchSearchBatch(
            batch_id=uuid5(NAMESPACE_URL, f"research-search:{context.run_id}:{fingerprint}"),
            run_id=context.run_id,
            task_id=context.task_id,
            attempt=context.attempt,
            sector_id=context.sector_id,
            sector_kind=context.sector_kind,
            query=bound_query,
            start_at=start_at,
            cutoff_at=context.cutoff_at,
            input_fingerprint=fingerprint,
            status=status,
            error_code=error_code,
            document_ids=tuple(document.document_id for document in documents),
            event_ids=tuple(event.event_id for event in events),
            created_at=created_at,
        )
        artifact = ArtifactRef(
            artifact_id=research_search_artifact_id(batch),
            task_id=context.task_id,
            attempt=context.attempt,
            kind="research_search",
            reference=f"research-search:{batch.batch_id}",
        )
        self._committer.commit(
            artifact,
            worker_id=context.worker_id,
            persistence=ResearchSearchPersistence(batch, documents, events),
            now=created_at,
        )
        return batch


class NewsDetailAccessError(ValueError):
    """A stable, non-sensitive rejection code for a T07 request."""


class NewsDetailSnapshotPersistence:
    def __init__(self, snapshot: NewsDetailSnapshot) -> None:
        self._snapshot = snapshot

    def write(self, session: TransactionSession, artifact: object) -> None:
        del artifact
        snapshot = self._snapshot
        session.execute(
            "INSERT INTO news_detail_snapshots (detail_id, run_id, task_id, attempt, "
            "sector_id, sector_kind, document_id, document_content_hash, input_fingerprint, "
            "availability, content, content_hash, truncated, historical_snapshot_verified, "
            "error_code, payload_json, created_at) VALUES (:detail_id, :run_id, :task_id, "
            ":attempt, :sector_id, :sector_kind, :document_id, :document_content_hash, "
            ":input_fingerprint, :availability, :content, :content_hash, :truncated, "
            ":historical_snapshot_verified, :error_code, :payload_json, :created_at)",
            {
                "detail_id": str(snapshot.detail_id),
                "run_id": str(snapshot.run_id),
                "task_id": str(snapshot.task_id),
                "attempt": snapshot.attempt,
                "sector_id": snapshot.sector_id,
                "sector_kind": snapshot.sector_kind.value,
                "document_id": snapshot.document_id,
                "document_content_hash": snapshot.document_content_hash,
                "input_fingerprint": snapshot.input_fingerprint,
                "availability": snapshot.availability,
                "content": snapshot.content,
                "content_hash": snapshot.content_hash,
                "truncated": int(snapshot.truncated),
                "historical_snapshot_verified": int(snapshot.historical_snapshot_verified),
                "error_code": snapshot.error_code,
                "payload_json": snapshot.model_dump_json(),
                "created_at": snapshot.created_at.isoformat(),
            },
        )

    def exists(self, session: TransactionSession, artifact: object) -> bool:
        del artifact
        return bool(
            session.rows(
                "SELECT 1 FROM news_detail_snapshots WHERE detail_id=:detail_id",
                {"detail_id": str(self._snapshot.detail_id)},
            )
        )


class ReadBoundNewsDetailService:
    def __init__(
        self,
        *,
        detail: NewsDetailPort,
        orchestration: SnapshotRepository,
        committer: AtomicArtifactCommitter,
        news: NewsRepositoryPort,
        research_searches: ResearchSearchRepositoryPort,
        news_batches: NewsBatchRepositoryPort | None = None,
    ) -> None:
        self._detail = detail
        self._orchestration = orchestration
        self._committer = committer
        self._news = news
        self._research_searches = research_searches
        self._news_batches = news_batches

    def _known_document_ids(self, context: BoundSectorResearchContext) -> set[str]:
        known: set[str] = set()
        for artifact in context.input_artifacts:
            prefix = "news-batch:"
            if artifact.kind != "news_batch" or not artifact.reference.startswith(prefix):
                continue
            if self._news_batches is None:
                continue
            news_batch = self._news_batches.get(UUID(artifact.reference[len(prefix) :]))
            if news_batch is not None and news_batch.run_id == context.run_id:
                known.update(news_batch.document_ids)

        state = self._orchestration.load(context.run_id)
        if state is None:
            raise KeyError("orchestration run not found")
        prefix = "research-search:"
        for artifact in state.artifacts:
            if (
                artifact.kind != "research_search"
                or artifact.task_id != context.task_id
                or artifact.attempt != context.attempt
                or not artifact.reference.startswith(prefix)
            ):
                continue
            search_batch = self._research_searches.get(UUID(artifact.reference[len(prefix) :]))
            if (
                search_batch is not None
                and search_batch.run_id == context.run_id
                and search_batch.task_id == context.task_id
                and search_batch.attempt == context.attempt
                and search_batch.sector_id == context.sector_id
                and search_batch.sector_kind == context.sector_kind
            ):
                known.update(search_batch.document_ids)
        return known

    async def read(
        self,
        *,
        context: BoundSectorResearchContext,
        document_id: str,
        now: datetime | None = None,
    ) -> NewsDetailSnapshot:
        created_at = now or datetime.now(UTC)
        require_live_task_owner(
            self._orchestration,
            context.run_id,
            task_id=context.task_id,
            attempt=context.attempt,
            worker_id=context.worker_id,
            now=created_at,
        )
        if document_id not in self._known_document_ids(context):
            raise NewsDetailAccessError("UNKNOWN_DOCUMENT_ID")
        document = self._news.get_documents((document_id,)).get(document_id)
        if document is None:
            raise NewsDetailAccessError("UNKNOWN_DOCUMENT_ID")
        if document.use_at(context.cutoff_at) is NewsUse.EXCLUDED:
            raise NewsDetailAccessError("DOCUMENT_AFTER_CUTOFF")
        try:
            detail = await self._detail.read(document)
            content = detail.content[:12000]
            availability = detail.availability
            error_code = detail.error_code
            fetched_at = detail.fetched_at
            historical_snapshot_verified = detail.historical_snapshot_verified
            truncated = detail.truncated or len(detail.content) > 12000
        except Exception:
            content = ""
            availability = "unavailable"
            error_code = "TOOL_FAILED"
            fetched_at = created_at
            historical_snapshot_verified = False
            truncated = False
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "task_id": str(context.task_id),
                    "attempt": context.attempt,
                    "sector_id": context.sector_id,
                    "document_id": document.document_id,
                    "document_content_hash": document.content_hash,
                    "cutoff_at": context.cutoff_at.isoformat(),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        snapshot = NewsDetailSnapshot(
            detail_id=uuid5(NAMESPACE_URL, f"news-detail:{context.run_id}:{fingerprint}"),
            run_id=context.run_id,
            task_id=context.task_id,
            attempt=context.attempt,
            sector_id=context.sector_id,
            sector_kind=context.sector_kind,
            document_id=document.document_id,
            document_content_hash=document.content_hash,
            input_fingerprint=fingerprint,
            availability=availability,
            content=content,
            content_hash=content_hash,
            fetched_at=fetched_at,
            truncated=truncated,
            historical_snapshot_verified=historical_snapshot_verified,
            error_code=error_code,
            created_at=created_at,
        )
        artifact = ArtifactRef(
            artifact_id=news_detail_artifact_id(snapshot),
            task_id=context.task_id,
            attempt=context.attempt,
            kind="news_detail",
            reference=f"news-detail:{snapshot.detail_id}",
        )
        self._committer.commit(
            artifact,
            worker_id=context.worker_id,
            persistence=NewsDetailSnapshotPersistence(snapshot),
            now=created_at,
        )
        return snapshot


__all__ = [
    "NewsDetailAccessError",
    "NewsDetailSnapshotPersistence",
    "ReadBoundNewsDetailService",
    "ResearchSearchPersistence",
    "SearchSectorNewsService",
]
