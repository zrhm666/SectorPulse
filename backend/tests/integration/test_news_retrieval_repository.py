from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.news_retrieval import (
    MappingConfidence,
    NewsQuery,
    NewsQueryDocumentLink,
    QueryType,
    SectorEventLink,
    SourceRunMetric,
)
from sector_pulse.domain.provider import DataStatus
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.news_retrieval_repository import SQLiteNewsRetrievalRepository


def test_save_audit_is_idempotent_and_hashes_query_values(tmp_path: Path) -> None:
    run_id = uuid4()
    now = datetime(2026, 8, 14, 2, 0, tzinfo=UTC)
    query = NewsQuery(
        query_id="q-1",
        query_type=QueryType.KEYWORD,
        source_id="eastmoney",
        value="人工智能",
        sector_ids=("concept-1",),
        priority=10,
        start_at=datetime(2026, 8, 13, 2, 0, tzinfo=UTC),
        cutoff_at=now,
    )
    metric = SourceRunMetric(
        run_id=run_id,
        source_id="eastmoney",
        started_at=now,
        completed_at=now,
        call_count=1,
        retry_count=0,
        status=DataStatus.SUCCESS,
        duration_ms=12,
    )
    link = SectorEventLink(
        run_id=run_id,
        event_id="event-1",
        sector_id="concept-1",
        sector_kind=SectorKind.CONCEPT,
        relation_type="alias",
        matched_entities=("人工智能",),
        mapping_confidence=MappingConfidence.MEDIUM,
        mapping_reason="approved alias",
        rule_version="2026-08-14.1",
    )
    database = SQLiteDatabase(tmp_path / "sector-pulse.db")
    database.initialize()
    # 外键要求先有运行和事件；审计 Repository 只负责自己的三张表。
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO analysis_runs (run_id, mode, requested_at) VALUES (?, ?, ?)",
            (str(run_id), "LIVE", now.isoformat()),
        )
        connection.execute(
            """
            INSERT INTO news_events (
                event_id, canonical_title, deduplication_reason, metadata_json
            ) VALUES (?, ?, ?, ?)
            """,
            ("event-1", "人工智能政策", "content_hash", "{}"),
        )
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO news_documents (
                document_id, source_id, canonical_url, title, observed_at,
                content_hash, source_grade, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "doc-1", "eastmoney", "https://example.com/doc-1", "Document 1",
                now.isoformat(), "hash-1", "REPUTABLE_MEDIA", "{}",
            ),
        )
    repository = SQLiteNewsRetrievalRepository(database)
    query_documents = (
        NewsQueryDocumentLink(run_id=run_id, query_id="q-1", document_id="doc-1"),
    )
    repository.save_audit(
        run_id, (metric,), ((query, DataStatus.SUCCESS, 3, None),), (link,), query_documents
    )
    repository.save_audit(
        run_id, (metric,), ((query, DataStatus.SUCCESS, 3, None),), (link,), query_documents
    )
    with database.connection() as connection:
        source_count = connection.execute("SELECT COUNT(*) FROM news_source_runs").fetchone()[0]
        query_row = connection.execute(
            "SELECT value_hash FROM news_queries WHERE query_id = ?", ("q-1",)
        ).fetchone()
        link_count = connection.execute("SELECT COUNT(*) FROM sector_event_links").fetchone()[0]
        query_document_count = connection.execute(
            "SELECT COUNT(*) FROM news_query_documents"
        ).fetchone()[0]
    assert source_count == 1
    assert query_row[0] != "人工智能"
    assert link_count == 1
    assert query_document_count == 1
    assert repository.list_query_documents(run_id) == query_documents
