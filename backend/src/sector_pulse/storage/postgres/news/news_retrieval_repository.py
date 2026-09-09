# ruff: noqa: E501
import hashlib
import json
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from sector_pulse.domain.news.news_retrieval import (
    NewsQuery,
    NewsQueryAuditRecord,
    NewsQueryDocumentLink,
    SectorEventLink,
    SourceRunMetric,
)
from sector_pulse.domain.provider import DataStatus
from sector_pulse.storage.postgres.database import PostgresDatabase


class PostgresNewsRetrievalRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def save_audit(self, run_id: UUID, metrics: Sequence[SourceRunMetric],
                         query_results: Sequence[tuple[NewsQuery, DataStatus, int, str | None]],
                         links: Sequence[SectorEventLink],
                         query_documents: Sequence[NewsQueryDocumentLink] = ()) -> None:
        with self._database.start().begin() as connection:
            for metric in metrics:
                connection.execute(
                    text("INSERT INTO news_source_runs (run_id, source_id, started_at, completed_at, call_count, retry_count, status, duration_ms, error_code) "
                         "VALUES (:run_id, :source_id, :started_at, :completed_at, :call_count, :retry_count, :status, :duration_ms, :error_code) "
                         "ON CONFLICT (run_id, source_id) DO UPDATE SET completed_at = EXCLUDED.completed_at, call_count = EXCLUDED.call_count, retry_count = EXCLUDED.retry_count, status = EXCLUDED.status, duration_ms = EXCLUDED.duration_ms, error_code = EXCLUDED.error_code"),
                    {"run_id": str(metric.run_id), "source_id": metric.source_id,
                     "started_at": metric.started_at.isoformat(), "completed_at": metric.completed_at.isoformat(),
                     "call_count": metric.call_count, "retry_count": metric.retry_count,
                     "status": metric.status.value, "duration_ms": metric.duration_ms, "error_code": metric.error_code},
                )
            for query, status, result_count, error_code in query_results:
                connection.execute(
                    text("INSERT INTO news_queries (run_id, query_id, query_type, source_id, value_hash, sector_ids_json, priority, start_at, cutoff_at, status, result_count, error_code) "
                         "VALUES (:run_id, :query_id, :query_type, :source_id, :value_hash, :sector_ids, :priority, :start_at, :cutoff_at, :status, :result_count, :error_code) "
                         "ON CONFLICT (run_id, query_id) DO UPDATE SET status = EXCLUDED.status, result_count = EXCLUDED.result_count, error_code = EXCLUDED.error_code"),
                    {"run_id": str(run_id), "query_id": query.query_id, "query_type": query.query_type.value,
                     "source_id": query.source_id, "value_hash": hashlib.sha256(query.value.encode()).hexdigest(),
                     "sector_ids": json.dumps(query.sector_ids), "priority": query.priority,
                     "start_at": query.start_at.isoformat(), "cutoff_at": query.cutoff_at.isoformat(),
                     "status": status.value, "result_count": result_count, "error_code": error_code},
                )
            for link in links:
                connection.execute(
                    text("INSERT INTO sector_event_links (run_id, event_id, sector_id, sector_kind, relation_type, matched_entities_json, mapping_confidence, mapping_reason, rule_version) "
                         "VALUES (:run_id, :event_id, :sector_id, :sector_kind, :relation_type, :entities, :confidence, :reason, :rule_version) "
                         "ON CONFLICT (run_id, event_id, sector_id, sector_kind) DO UPDATE SET relation_type = EXCLUDED.relation_type, matched_entities_json = EXCLUDED.matched_entities_json, mapping_confidence = EXCLUDED.mapping_confidence, mapping_reason = EXCLUDED.mapping_reason, rule_version = EXCLUDED.rule_version"),
                    {"run_id": str(link.run_id), "event_id": link.event_id, "sector_id": link.sector_id,
                     "sector_kind": link.sector_kind.value, "relation_type": link.relation_type,
                     "entities": json.dumps(link.matched_entities), "confidence": link.mapping_confidence.value,
                     "reason": link.mapping_reason, "rule_version": link.rule_version},
                )
            for item in query_documents:
                connection.execute(
                    text("INSERT INTO news_query_documents (run_id, query_id, document_id) "
                         "VALUES (:run_id, :query_id, :document_id) "
                         "ON CONFLICT (run_id, query_id, document_id) DO NOTHING"),
                    {"run_id": str(item.run_id), "query_id": item.query_id,
                     "document_id": item.document_id},
                )

    def list_links(self, run_id: UUID) -> tuple[SectorEventLink, ...]:
        with self._database.start().connect() as connection:
            result = connection.execute(
                text("SELECT event_id, sector_id, sector_kind, relation_type, matched_entities_json, mapping_confidence, mapping_reason, rule_version FROM sector_event_links WHERE run_id = :run_id ORDER BY event_id, sector_id"),
                {"run_id": str(run_id)},
            )
            rows = result.fetchall()
        return tuple(SectorEventLink(
            run_id=run_id, event_id=row[0], sector_id=row[1], sector_kind=row[2], relation_type=row[3],
            matched_entities=tuple(json.loads(row[4])), mapping_confidence=row[5], mapping_reason=row[6], rule_version=row[7],
        ) for row in rows)

    def list_query_documents(
        self, run_id: UUID
    ) -> tuple[NewsQueryDocumentLink, ...]:
        with self._database.start().connect() as connection:
            result = connection.execute(
                text("SELECT query_id, document_id FROM news_query_documents "
                     "WHERE run_id = :run_id ORDER BY query_id, document_id"),
                {"run_id": str(run_id)},
            )
            rows = result.fetchall()
        return tuple(
            NewsQueryDocumentLink(run_id=run_id, query_id=row[0], document_id=row[1])
            for row in rows
        )

    def list_queries(self, run_id: UUID) -> tuple[NewsQueryAuditRecord, ...]:
        with self._database.start().connect() as connection:
            result = connection.execute(
                text("SELECT query_id, query_type, source_id, sector_ids_json, priority, "
                     "start_at, cutoff_at, status, result_count, error_code "
                     "FROM news_queries WHERE run_id = :run_id ORDER BY source_id, query_id"),
                {"run_id": str(run_id)},
            )
            rows = result.fetchall()
        return tuple(
            NewsQueryAuditRecord(
                run_id=run_id, query_id=row[0], query_type=row[1], source_id=row[2],
                sector_ids=tuple(json.loads(row[3])), priority=row[4],
                start_at=datetime.fromisoformat(row[5]),
                cutoff_at=datetime.fromisoformat(row[6]), status=row[7],
                result_count=row[8], error_code=row[9],
            )
            for row in rows
        )

    def list_source_metrics(self, run_id: UUID) -> tuple[SourceRunMetric, ...]:
        with self._database.start().connect() as connection:
            result = connection.execute(
                text("SELECT source_id, started_at, completed_at, call_count, retry_count, "
                     "status, duration_ms, error_code FROM news_source_runs "
                     "WHERE run_id = :run_id ORDER BY source_id"),
                {"run_id": str(run_id)},
            )
            rows = result.fetchall()
        return tuple(
            SourceRunMetric(
                run_id=run_id, source_id=row[0],
                started_at=datetime.fromisoformat(row[1]),
                completed_at=datetime.fromisoformat(row[2]), call_count=row[3],
                retry_count=row[4], status=row[5], duration_ms=row[6],
                error_code=row[7],
            )
            for row in rows
        )
