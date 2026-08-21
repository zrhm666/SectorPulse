# ruff: noqa: E501
import hashlib
import json
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import text

from sector_pulse.domain.news_retrieval import NewsQuery, SectorEventLink, SourceRunMetric
from sector_pulse.domain.provider import DataStatus
from sector_pulse.storage.postgres import PostgresDatabase


class PostgresNewsRetrievalRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    async def save_audit(self, run_id: UUID, metrics: Sequence[SourceRunMetric],
                         query_results: Sequence[tuple[NewsQuery, DataStatus, int, str | None]],
                         links: Sequence[SectorEventLink]) -> None:
        async with self._database.engine.begin() as connection:
            for metric in metrics:
                await connection.execute(
                    text("INSERT INTO news_source_runs (run_id, source_id, started_at, completed_at, call_count, retry_count, status, duration_ms, error_code) "
                         "VALUES (:run_id, :source_id, :started_at, :completed_at, :call_count, :retry_count, :status, :duration_ms, :error_code) "
                         "ON CONFLICT (run_id, source_id) DO UPDATE SET completed_at = EXCLUDED.completed_at, call_count = EXCLUDED.call_count, retry_count = EXCLUDED.retry_count, status = EXCLUDED.status, duration_ms = EXCLUDED.duration_ms, error_code = EXCLUDED.error_code"),
                    {"run_id": str(metric.run_id), "source_id": metric.source_id,
                     "started_at": metric.started_at.isoformat(), "completed_at": metric.completed_at.isoformat(),
                     "call_count": metric.call_count, "retry_count": metric.retry_count,
                     "status": metric.status.value, "duration_ms": metric.duration_ms, "error_code": metric.error_code},
                )
            for query, status, result_count, error_code in query_results:
                await connection.execute(
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
                await connection.execute(
                    text("INSERT INTO sector_event_links (run_id, event_id, sector_id, sector_kind, relation_type, matched_entities_json, mapping_confidence, mapping_reason, rule_version) "
                         "VALUES (:run_id, :event_id, :sector_id, :sector_kind, :relation_type, :entities, :confidence, :reason, :rule_version) "
                         "ON CONFLICT (run_id, event_id, sector_id, sector_kind) DO UPDATE SET relation_type = EXCLUDED.relation_type, matched_entities_json = EXCLUDED.matched_entities_json, mapping_confidence = EXCLUDED.mapping_confidence, mapping_reason = EXCLUDED.mapping_reason, rule_version = EXCLUDED.rule_version"),
                    {"run_id": str(link.run_id), "event_id": link.event_id, "sector_id": link.sector_id,
                     "sector_kind": link.sector_kind.value, "relation_type": link.relation_type,
                     "entities": json.dumps(link.matched_entities), "confidence": link.mapping_confidence.value,
                     "reason": link.mapping_reason, "rule_version": link.rule_version},
                )

    async def list_links(self, run_id: UUID) -> tuple[SectorEventLink, ...]:
        async with self._database.engine.connect() as connection:
            result = await connection.execute(
                text("SELECT event_id, sector_id, sector_kind, relation_type, matched_entities_json, mapping_confidence, mapping_reason, rule_version FROM sector_event_links WHERE run_id = :run_id ORDER BY event_id, sector_id"),
                {"run_id": str(run_id)},
            )
            rows = result.fetchall()
        return tuple(SectorEventLink(
            run_id=run_id, event_id=row[0], sector_id=row[1], sector_kind=row[2], relation_type=row[3],
            matched_entities=tuple(json.loads(row[4])), mapping_confidence=row[5], mapping_reason=row[6], rule_version=row[7],
        ) for row in rows)
