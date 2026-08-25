import hashlib
import json
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sector_pulse.domain.news_retrieval import (
    NewsQuery,
    NewsQueryAuditRecord,
    NewsQueryDocumentLink,
    SectorEventLink,
    SourceRunMetric,
)
from sector_pulse.domain.provider import DataStatus
from sector_pulse.storage.sqlite import SQLiteDatabase


class SQLiteNewsRetrievalRepository:
    """保存 Phase 1A.2 的来源、查询和板块关联审计记录。"""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def save_audit(
        self,
        run_id: UUID,
        metrics: Sequence[SourceRunMetric],
        query_results: Sequence[tuple[NewsQuery, DataStatus, int, str | None]],
        links: Sequence[SectorEventLink],
        query_documents: Sequence[NewsQueryDocumentLink] = (),
    ) -> None:
        with self._database.transaction() as connection:
            for metric in metrics:
                connection.execute(
                    """
                    INSERT INTO news_source_runs (
                        run_id, source_id, started_at, completed_at, call_count,
                        retry_count, status, duration_ms, error_code
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, source_id) DO UPDATE SET
                        completed_at = excluded.completed_at, call_count = excluded.call_count,
                        retry_count = excluded.retry_count, status = excluded.status,
                        duration_ms = excluded.duration_ms, error_code = excluded.error_code
                    """,
                    (
                        str(metric.run_id), metric.source_id, metric.started_at.isoformat(),
                        metric.completed_at.isoformat(), metric.call_count, metric.retry_count,
                        metric.status.value, metric.duration_ms, metric.error_code,
                    ),
                )
            for query, status, result_count, error_code in query_results:
                value_hash = hashlib.sha256(query.value.encode("utf-8")).hexdigest()
                connection.execute(
                    """
                    INSERT INTO news_queries (
                        run_id, query_id, query_type, source_id, value_hash,
                        sector_ids_json, priority, start_at, cutoff_at,
                        status, result_count, error_code
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, query_id) DO UPDATE SET
                        status = excluded.status, result_count = excluded.result_count,
                        error_code = excluded.error_code
                    """,
                    (
                        str(run_id), query.query_id, query.query_type.value, query.source_id,
                        value_hash, json.dumps(query.sector_ids, ensure_ascii=False),
                        query.priority, query.start_at.isoformat(), query.cutoff_at.isoformat(),
                        status.value, result_count, error_code,
                    ),
                )
            for link in links:
                connection.execute(
                    """
                    INSERT INTO sector_event_links (
                        run_id, event_id, sector_id, sector_kind, relation_type,
                        matched_entities_json, mapping_confidence, mapping_reason, rule_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, event_id, sector_id, sector_kind) DO UPDATE SET
                        relation_type = excluded.relation_type,
                        matched_entities_json = excluded.matched_entities_json,
                        mapping_confidence = excluded.mapping_confidence,
                        mapping_reason = excluded.mapping_reason,
                        rule_version = excluded.rule_version
                    """,
                    (
                        str(link.run_id), link.event_id, link.sector_id, link.sector_kind.value,
                        link.relation_type, json.dumps(link.matched_entities, ensure_ascii=False),
                        link.mapping_confidence.value, link.mapping_reason, link.rule_version,
                    ),
                )
            for item in query_documents:
                connection.execute(
                    """
                    INSERT INTO news_query_documents (run_id, query_id, document_id)
                    VALUES (?, ?, ?)
                    ON CONFLICT(run_id, query_id, document_id) DO NOTHING
                    """,
                    (str(item.run_id), item.query_id, item.document_id),
                )

    def list_links(self, run_id: UUID) -> tuple[SectorEventLink, ...]:
        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT event_id, sector_id, sector_kind, relation_type, "
                "matched_entities_json, mapping_confidence, mapping_reason, rule_version "
                "FROM sector_event_links WHERE run_id = ? ORDER BY event_id, sector_id",
                (str(run_id),),
            ).fetchall()
        return tuple(
            SectorEventLink(
                run_id=run_id, event_id=row[0], sector_id=row[1], sector_kind=row[2],
                relation_type=row[3], matched_entities=tuple(json.loads(row[4])),
                mapping_confidence=row[5], mapping_reason=row[6], rule_version=row[7],
            )
            for row in rows
        )

    def list_query_documents(self, run_id: UUID) -> tuple[NewsQueryDocumentLink, ...]:
        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT query_id, document_id FROM news_query_documents "
                "WHERE run_id = ? ORDER BY query_id, document_id",
                (str(run_id),),
            ).fetchall()
        return tuple(
            NewsQueryDocumentLink(run_id=run_id, query_id=row[0], document_id=row[1])
            for row in rows
        )

    def list_queries(self, run_id: UUID) -> tuple[NewsQueryAuditRecord, ...]:
        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT query_id, query_type, source_id, sector_ids_json, priority, "
                "start_at, cutoff_at, status, result_count, error_code "
                "FROM news_queries WHERE run_id = ? ORDER BY source_id, query_id",
                (str(run_id),),
            ).fetchall()
        return tuple(
            NewsQueryAuditRecord(
                run_id=run_id,
                query_id=row[0],
                query_type=row[1],
                source_id=row[2],
                sector_ids=tuple(json.loads(row[3])),
                priority=row[4],
                start_at=datetime.fromisoformat(row[5]),
                cutoff_at=datetime.fromisoformat(row[6]),
                status=row[7],
                result_count=row[8],
                error_code=row[9],
            )
            for row in rows
        )

    def list_source_metrics(self, run_id: UUID) -> tuple[SourceRunMetric, ...]:
        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT source_id, started_at, completed_at, call_count, retry_count, "
                "status, duration_ms, error_code FROM news_source_runs "
                "WHERE run_id = ? ORDER BY source_id",
                (str(run_id),),
            ).fetchall()
        return tuple(
            SourceRunMetric(
                run_id=run_id,
                source_id=row[0],
                started_at=datetime.fromisoformat(row[1]),
                completed_at=datetime.fromisoformat(row[2]),
                call_count=row[3],
                retry_count=row[4],
                status=row[5],
                duration_ms=row[6],
                error_code=row[7],
            )
            for row in rows
        )
