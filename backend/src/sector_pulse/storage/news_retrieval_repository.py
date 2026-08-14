import hashlib
import json
from collections.abc import Sequence
from uuid import UUID

from sector_pulse.domain.news_retrieval import NewsQuery, SectorEventLink, SourceRunMetric
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
                        completed_at = excluded.completed_at,
                        call_count = excluded.call_count,
                        retry_count = excluded.retry_count,
                        status = excluded.status,
                        duration_ms = excluded.duration_ms,
                        error_code = excluded.error_code
                    """,
                    (
                        str(metric.run_id),
                        metric.source_id,
                        metric.started_at.isoformat(),
                        metric.completed_at.isoformat(),
                        metric.call_count,
                        metric.retry_count,
                        metric.status.value,
                        metric.duration_ms,
                        metric.error_code,
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
                        status = excluded.status,
                        result_count = excluded.result_count,
                        error_code = excluded.error_code
                    """,
                    (
                        str(run_id),
                        query.query_id,
                        query.query_type.value,
                        query.source_id,
                        value_hash,
                        json.dumps(query.sector_ids, ensure_ascii=False),
                        query.priority,
                        query.start_at.isoformat(),
                        query.cutoff_at.isoformat(),
                        status.value,
                        result_count,
                        error_code,
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
                        str(link.run_id),
                        link.event_id,
                        link.sector_id,
                        link.sector_kind.value,
                        link.relation_type,
                        json.dumps(link.matched_entities, ensure_ascii=False),
                        link.mapping_confidence.value,
                        link.mapping_reason,
                        link.rule_version,
                    ),
                )
