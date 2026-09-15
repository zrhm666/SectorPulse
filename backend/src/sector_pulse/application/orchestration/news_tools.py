import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from sector_pulse.application.news.entity_resolution import resolve_sector_links
from sector_pulse.application.news.news_ingestion import deduplicate_documents
from sector_pulse.application.news.news_quality import evaluate_news_quality
from sector_pulse.application.news.news_retrieval import (
    QueryExecutionResult,
    build_news_query_plan,
    execute_news_query_plan,
)
from sector_pulse.application.orchestration.artifacts import AtomicArtifactCommitter
from sector_pulse.application.orchestration.data_tools import require_live_task_owner
from sector_pulse.domain.market.market import SectorKind
from sector_pulse.domain.news.news import NewsDocument, NewsEvent
from sector_pulse.domain.news.news_batch import (
    NewsBatch,
    NewsBatchQuality,
    NewsCollectionReason,
)
from sector_pulse.domain.news.news_retrieval import (
    NewsQueryDocumentLink,
    SectorEntityConfig,
    SectorEventLink,
    SourceRunMetric,
)
from sector_pulse.domain.provider import DataStatus
from sector_pulse.ports.news_sources import (
    DisclosureSearchPort,
    GlobalNewsDiscoveryPort,
    KeywordNewsSearchPort,
    SectorConstituentPort,
)
from sector_pulse.ports.orchestration import SnapshotRepository, TransactionSession
from sector_pulse.storage.ports.market import (
    CandidateBatchRepositoryPort,
    MarketSnapshotRepositoryPort,
)


class NewsCollectionLimits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    lookback_hours: int = Field(ge=1, le=168)
    keyword_budget: int = Field(ge=0, le=24)
    disclosure_code_budget: int = Field(ge=0, le=12)
    max_retries: int = Field(ge=0, le=2)


def _source_status(values: Sequence[DataStatus]) -> DataStatus:
    unique = set(values)
    if not unique:
        return DataStatus.UNAVAILABLE
    if len(unique) == 1:
        return next(iter(unique))
    if unique <= {DataStatus.SUCCESS, DataStatus.EMPTY}:
        return DataStatus.SUCCESS
    return DataStatus.PARTIAL


class NewsBatchPersistence:
    def __init__(
        self,
        batch: NewsBatch,
        *,
        documents: tuple[NewsDocument, ...],
        events: tuple[NewsEvent, ...],
        executions: tuple[QueryExecutionResult, ...],
        links: tuple[SectorEventLink, ...],
        query_documents: tuple[NewsQueryDocumentLink, ...],
    ) -> None:
        self._batch = batch
        self._documents = documents
        self._events = events
        self._executions = executions
        self._links = links
        self._query_documents = query_documents

    def write(self, session: TransactionSession, artifact: object) -> None:
        del artifact
        canonical_ids: dict[str, str] = {}
        for document in self._documents:
            existing = session.rows(
                "SELECT document_id FROM news_documents WHERE canonical_url=:url",
                {"url": document.canonical_locator},
            )
            canonical_id = str(existing[0][0]) if existing else document.document_id
            canonical_ids[document.document_id] = canonical_id
            if existing and canonical_id != document.document_id:
                continue
            session.execute(
                "INSERT INTO news_documents (document_id, source_id, canonical_url, title, "
                "published_at, observed_at, content_hash, source_grade, metadata_json, "
                "citation_url, publisher, summary, source_observed_at, use_grade, "
                "quality_flags_json) VALUES (:document_id, :source_id, :canonical_url, "
                ":title, :published_at, :observed_at, :content_hash, :source_grade, "
                ":metadata_json, :citation_url, :publisher, :summary, :source_observed_at, "
                ":use_grade, :quality_flags_json) ON CONFLICT(document_id) DO UPDATE SET "
                "title=excluded.title, observed_at=excluded.observed_at, "
                "citation_url=excluded.citation_url, publisher=excluded.publisher, "
                "summary=excluded.summary, source_observed_at=excluded.source_observed_at, "
                "quality_flags_json=excluded.quality_flags_json, "
                "metadata_json=excluded.metadata_json",
                {
                    "document_id": document.document_id,
                    "source_id": document.source_id,
                    "canonical_url": document.canonical_locator,
                    "title": document.title,
                    "published_at": (
                        document.published_at.isoformat() if document.published_at else None
                    ),
                    "observed_at": document.collected_at.isoformat(),
                    "content_hash": document.content_hash,
                    "source_grade": document.source_grade.value,
                    "metadata_json": document.model_dump_json(),
                    "citation_url": document.citation_url,
                    "publisher": document.publisher,
                    "summary": document.summary,
                    "source_observed_at": (
                        document.source_observed_at.isoformat()
                        if document.source_observed_at
                        else None
                    ),
                    "use_grade": "EVIDENCE" if document.published_at else "BACKGROUND",
                    "quality_flags_json": "[]",
                },
            )
        for event in self._events:
            normalized = event.model_copy(
                update={
                    "document_ids": tuple(
                        canonical_ids.get(document_id, document_id)
                        for document_id in event.document_ids
                    )
                }
            )
            session.execute(
                "INSERT INTO news_events (event_id, canonical_title, first_published_at, "
                "deduplication_reason, metadata_json) VALUES (:event_id, :title, "
                ":published_at, :reason, :metadata_json) ON CONFLICT(event_id) DO UPDATE SET "
                "canonical_title=excluded.canonical_title, metadata_json=excluded.metadata_json",
                {
                    "event_id": normalized.event_id,
                    "title": normalized.canonical_title,
                    "published_at": (
                        normalized.first_published_at.isoformat()
                        if normalized.first_published_at
                        else None
                    ),
                    "reason": normalized.deduplication_reason,
                    "metadata_json": normalized.model_dump_json(),
                },
            )
            session.execute(
                "DELETE FROM news_event_documents WHERE event_id=:event_id",
                {"event_id": normalized.event_id},
            )
            for document_id in normalized.document_ids:
                session.execute(
                    "INSERT INTO news_event_documents (event_id, document_id) VALUES "
                    "(:event_id, :document_id) ON CONFLICT(event_id, document_id) DO NOTHING",
                    {"event_id": normalized.event_id, "document_id": document_id},
                )
        for metric in self._batch.source_metrics:
            session.execute(
                "INSERT INTO news_source_runs (run_id, source_id, started_at, completed_at, "
                "call_count, retry_count, result_count, status, duration_ms, error_code) VALUES "
                "(:run_id, :source_id, :started_at, :completed_at, :call_count, :retry_count, "
                ":result_count, :status, :duration_ms, :error_code) "
                "ON CONFLICT(run_id, source_id) DO UPDATE SET "
                "completed_at=excluded.completed_at, call_count=excluded.call_count, "
                "retry_count=excluded.retry_count, result_count=excluded.result_count, "
                "status=excluded.status, "
                "duration_ms=excluded.duration_ms, error_code=excluded.error_code",
                {
                    "run_id": str(metric.run_id),
                    "source_id": metric.source_id,
                    "started_at": metric.started_at.isoformat(),
                    "completed_at": metric.completed_at.isoformat(),
                    "call_count": metric.call_count,
                    "retry_count": metric.retry_count,
                    "result_count": metric.result_count,
                    "status": metric.status.value,
                    "duration_ms": metric.duration_ms,
                    "error_code": metric.error_code,
                },
            )
        for execution in self._executions:
            query = execution.query
            session.execute(
                "INSERT INTO news_queries (run_id, query_id, query_type, source_id, value_hash, "
                "sector_ids_json, priority, start_at, cutoff_at, status, result_count, "
                "error_code) VALUES (:run_id, :query_id, :query_type, :source_id, :value_hash, "
                ":sector_ids_json, :priority, :start_at, :cutoff_at, :status, :result_count, "
                ":error_code) ON CONFLICT(run_id, query_id) DO UPDATE SET status=excluded.status, "
                "result_count=excluded.result_count, error_code=excluded.error_code",
                {
                    "run_id": str(self._batch.run_id),
                    "query_id": query.query_id,
                    "query_type": query.query_type.value,
                    "source_id": query.source_id,
                    "value_hash": hashlib.sha256(query.value.encode("utf-8")).hexdigest(),
                    "sector_ids_json": json.dumps(query.sector_ids, ensure_ascii=False),
                    "priority": query.priority,
                    "start_at": query.start_at.isoformat(),
                    "cutoff_at": query.cutoff_at.isoformat(),
                    "status": execution.status.value,
                    "result_count": len(execution.documents),
                    "error_code": execution.error_code,
                },
            )
        for link in self._links:
            session.execute(
                "INSERT INTO sector_event_links (run_id, event_id, sector_id, sector_kind, "
                "relation_type, matched_entities_json, mapping_confidence, mapping_reason, "
                "rule_version) VALUES (:run_id, :event_id, :sector_id, :sector_kind, "
                ":relation_type, :entities, :confidence, :reason, :rule_version) "
                "ON CONFLICT(run_id, event_id, sector_id, sector_kind) DO UPDATE SET "
                "relation_type=excluded.relation_type, "
                "matched_entities_json=excluded.matched_entities_json, "
                "mapping_confidence=excluded.mapping_confidence, "
                "mapping_reason=excluded.mapping_reason, "
                "rule_version=excluded.rule_version",
                {
                    "run_id": str(link.run_id),
                    "event_id": link.event_id,
                    "sector_id": link.sector_id,
                    "sector_kind": link.sector_kind.value,
                    "relation_type": link.relation_type,
                    "entities": json.dumps(link.matched_entities, ensure_ascii=False),
                    "confidence": link.mapping_confidence.value,
                    "reason": link.mapping_reason,
                    "rule_version": link.rule_version,
                },
            )
        for item in self._query_documents:
            session.execute(
                "INSERT INTO news_query_documents (run_id, query_id, document_id) VALUES "
                "(:run_id, :query_id, :document_id) "
                "ON CONFLICT(run_id, query_id, document_id) DO NOTHING",
                {
                    "run_id": str(item.run_id),
                    "query_id": item.query_id,
                    "document_id": canonical_ids.get(item.document_id, item.document_id),
                },
            )
        batch = self._batch
        session.execute(
            "INSERT INTO news_batches (batch_id, run_id, candidate_batch_id, input_fingerprint, "
            "collection_reason, start_at, cutoff_at, quality_status, document_count, event_count, "
            "link_count, source_metrics_json, quality_json, payload_json, created_at) VALUES "
            "(:batch_id, :run_id, :candidate_batch_id, :input_fingerprint, :collection_reason, "
            ":start_at, :cutoff_at, :quality_status, :document_count, :event_count, :link_count, "
            ":source_metrics_json, :quality_json, :payload_json, :created_at)",
            {
                "batch_id": str(batch.batch_id),
                "run_id": str(batch.run_id),
                "candidate_batch_id": str(batch.candidate_batch_id),
                "input_fingerprint": batch.input_fingerprint,
                "collection_reason": batch.collection_reason.value,
                "start_at": batch.start_at.isoformat(),
                "cutoff_at": batch.cutoff_at.isoformat(),
                "quality_status": batch.quality.status.value,
                "document_count": batch.document_count,
                "event_count": batch.event_count,
                "link_count": batch.link_count,
                "source_metrics_json": json.dumps(
                    [item.model_dump(mode="json") for item in batch.source_metrics]
                ),
                "quality_json": batch.quality.model_dump_json(),
                "payload_json": batch.model_dump_json(),
                "created_at": batch.created_at.isoformat(),
            },
        )
        for document in self._documents:
            session.execute(
                "INSERT INTO news_batch_documents (batch_id, document_id) VALUES "
                "(:batch_id, :document_id) ON CONFLICT(batch_id, document_id) DO NOTHING",
                {
                    "batch_id": str(batch.batch_id),
                    "document_id": canonical_ids[document.document_id],
                },
            )
        for event in self._events:
            session.execute(
                "INSERT INTO news_batch_events (batch_id, event_id) VALUES "
                "(:batch_id, :event_id) ON CONFLICT(batch_id, event_id) DO NOTHING",
                {"batch_id": str(batch.batch_id), "event_id": event.event_id},
            )

    def exists(self, session: TransactionSession, artifact: object) -> bool:
        del artifact
        return bool(
            session.rows(
                "SELECT 1 FROM news_batches WHERE batch_id=:batch_id",
                {"batch_id": str(self._batch.batch_id)},
            )
        )


class CollectInitialNewsService:
    def __init__(
        self,
        *,
        constituents: SectorConstituentPort,
        global_news: GlobalNewsDiscoveryPort,
        keyword_news: KeywordNewsSearchPort,
        disclosure_news: DisclosureSearchPort,
        entity_config: SectorEntityConfig,
        snapshots: MarketSnapshotRepositoryPort,
        candidate_batches: CandidateBatchRepositoryPort,
        orchestration: SnapshotRepository,
        committer: AtomicArtifactCommitter,
        limits: NewsCollectionLimits,
    ) -> None:
        self._constituents = constituents
        self._global_news = global_news
        self._keyword_news = keyword_news
        self._disclosure_news = disclosure_news
        self._entity_config = entity_config
        self._snapshots = snapshots
        self._candidate_batches = candidate_batches
        self._orchestration = orchestration
        self._committer = committer
        self._limits = limits

    async def collect(
        self,
        *,
        task_id: UUID,
        attempt: int,
        worker_id: str,
        candidate_artifact_id: UUID,
        reason: NewsCollectionReason,
        now: datetime | None = None,
        retry_backoff: Callable[[int], float] | None = None,
    ) -> NewsBatch:
        created_at = now or datetime.now(UTC)
        run_id = self._committer.run_id
        require_live_task_owner(
            self._orchestration,
            run_id,
            task_id=task_id,
            attempt=attempt,
            worker_id=worker_id,
            now=created_at,
        )
        state = self._orchestration.load(run_id)
        if state is None:
            raise KeyError("orchestration run not found")
        artifact = next(
            (item for item in state.artifacts if item.artifact_id == candidate_artifact_id),
            None,
        )
        if (
            artifact is None
            or artifact.kind != "candidate_batch"
            or artifact.task_id != task_id
            or artifact.attempt != attempt
        ):
            raise ValueError("candidate artifact is outside current task")
        prefix = "candidate-batch:"
        if not artifact.reference.startswith(prefix):
            raise ValueError("candidate artifact reference is invalid")
        candidate_batch = self._candidate_batches.get(
            UUID(artifact.reference[len(prefix) :])
        )
        if candidate_batch is None or candidate_batch.run_id != run_id:
            raise KeyError("candidate batch is unavailable")
        run = self._snapshots.get_run(run_id)
        if run is None or run.run_cutoff_at is None:
            raise ValueError("locked analysis cutoff is required")
        industry = self._snapshots.get(run_id, SectorKind.INDUSTRY)
        concept = self._snapshots.get(run_id, SectorKind.CONCEPT)
        if industry is None or concept is None:
            raise KeyError("core market snapshots are unavailable")
        memberships: dict[str, tuple[tuple[str, str], ...]] = {}
        for candidate in candidate_batch.candidates:
            result = await self._constituents.fetch_constituents(candidate.name, candidate.kind)
            memberships[candidate.provider_sector_id] = result.data or ()
        cutoff = run.run_cutoff_at
        start_at = cutoff - timedelta(hours=self._limits.lookback_hours)
        plan = build_news_query_plan(
            candidate_batch.candidates,
            self._entity_config,
            memberships,
            start_at,
            cutoff,
            keyword_budget=self._limits.keyword_budget,
            disclosure_code_budget=self._limits.disclosure_code_budget,
        )
        executions = await execute_news_query_plan(
            plan,
            self._global_news,
            self._keyword_news,
            self._disclosure_news,
            max_retries=self._limits.max_retries,
            retry_backoff=retry_backoff,
        )
        documents = tuple(document for item in executions for document in item.documents)
        events = deduplicate_documents(documents)
        stock_memberships = {
            code: tuple(
                sector_id
                for sector_id, members in memberships.items()
                if any(code == member[0] for member in members)
            )
            for members in memberships.values()
            for code, _name in members
        }
        links = resolve_sector_links(
            run_id,
            events,
            (*industry.sectors, *concept.sectors),
            stock_memberships,
            self._entity_config,
            {document.document_id: document for document in documents},
        )
        event_sectors: dict[str, list[str]] = defaultdict(list)
        for link in links:
            event_sectors[link.event_id].append(link.sector_id)
        events = tuple(
            event.model_copy(
                update={"sector_ids": tuple(sorted(event_sectors[event.event_id]))}
            )
            for event in events
        )
        grouped: dict[str, list[QueryExecutionResult]] = defaultdict(list)
        for execution in executions:
            grouped[execution.query.source_id].append(execution)
        statuses = {
            source_id: _source_status(tuple(item.status for item in items))
            for source_id, items in grouped.items()
        }
        quality = evaluate_news_quality(documents, events, statuses, cutoff)
        metrics = tuple(
            SourceRunMetric(
                run_id=run_id,
                source_id=source_id,
                started_at=min(item.started_at for item in items),
                completed_at=max(item.completed_at for item in items),
                call_count=sum(item.attempts for item in items),
                retry_count=sum(max(item.attempts - 1, 0) for item in items),
                result_count=sum(len(item.documents) for item in items),
                status=statuses[source_id],
                duration_ms=sum(item.duration_ms for item in items),
                error_code=(
                    next(iter(errors))
                    if len(errors := {item.error_code for item in items if item.error_code}) == 1
                    else "MULTIPLE_SOURCE_ERRORS"
                    if errors
                    else None
                ),
            )
            for source_id, items in sorted(grouped.items())
        )
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "candidate_artifact_id": str(candidate_artifact_id),
                    "reason": reason.value,
                    "cutoff": cutoff.isoformat(),
                    "entity_version": self._entity_config.version,
                    "limits": self._limits.model_dump(mode="json"),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        batch_id = uuid5(NAMESPACE_URL, f"news-batch:{run_id}:{fingerprint}")
        batch = NewsBatch(
            batch_id=batch_id,
            run_id=run_id,
            candidate_batch_id=candidate_batch.batch_id,
            input_fingerprint=fingerprint,
            collection_reason=reason,
            start_at=start_at,
            cutoff_at=cutoff,
            document_ids=tuple(document.document_id for document in documents),
            event_ids=tuple(event.event_id for event in events),
            link_count=len(links),
            source_metrics=metrics,
            quality=NewsBatchQuality.model_validate(quality.model_dump()),
            created_at=created_at,
        )
        query_documents = tuple(
            NewsQueryDocumentLink(
                run_id=run_id,
                query_id=execution.query.query_id,
                document_id=document.document_id,
            )
            for execution in executions
            for document in execution.documents
        )
        from sector_pulse.domain.orchestration.models import ArtifactRef

        news_artifact = ArtifactRef(
            artifact_id=uuid5(
                NAMESPACE_URL,
                f"news-artifact:{batch_id}:{task_id}:{attempt}",
            ),
            task_id=task_id,
            attempt=attempt,
            kind="news_batch",
            reference=f"news-batch:{batch_id}",
        )
        self._committer.commit(
            news_artifact,
            worker_id=worker_id,
            persistence=NewsBatchPersistence(
                batch,
                documents=documents,
                events=events,
                executions=executions,
                links=links,
                query_documents=query_documents,
            ),
            now=created_at,
        )
        return batch


__all__ = [
    "CollectInitialNewsService",
    "NewsCollectionLimits",
    "NewsCollectionReason",
]
