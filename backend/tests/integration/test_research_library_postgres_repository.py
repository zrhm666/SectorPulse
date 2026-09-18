"""PostgreSQL contract for the research library authority store.

Spec 4: PostgreSQL is the authoritative state source; MinIO and Milvus are reachable
only through pluggable ports and Milvus is a rebuildable derived index. That makes
this repository the only place where "what is visible to retrieval" is decided, so
the races it has to win are tested here against a real server rather than a fake:
two workers leasing one job, a version activation superseding its predecessor in one
transaction, and an upload replayed under the same idempotency key.

These tests only ever touch a database whose name ends in `_test`; the session guard
in `backend/tests/postgres_isolation.py` refuses to run otherwise.
"""

import os
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sector_pulse.domain.research_library.models import (
    ChunkEmbeddingStatus,
    ChunkType,
    DocumentVersionStatus,
    ExtractionMethod,
    IndexOutboxEvent,
    IngestionJob,
    IngestionStatus,
    OutboxOperation,
    OutboxStatus,
    ResearchChunk,
    ResearchDocument,
    ResearchDocumentVersion,
    SourceLocator,
    SourceSpan,
)
from sector_pulse.domain.research_library.retrieval import RetrievalAuditRecord
from sector_pulse.storage.ports.research_library import ResearchLibraryConflict
from sector_pulse.storage.postgres.database import PostgresDatabase
from sector_pulse.storage.postgres.research_library.repository import (
    PostgresResearchLibraryRepository,
)

pytestmark = pytest.mark.postgres

NOW = datetime.fromisoformat("2026-09-18T02:00:00+00:00")
LEASE_SECONDS = 300

RESEARCH_TABLES = (
    "internal_research_evidence_sources",
    "internal_research_evidence",
    "research_conflict_decisions",
    "research_retrieval_audits",
    "research_index_outbox",
    "research_ingestion_jobs",
    "research_chunks",
    "research_document_assets",
    "research_document_versions",
    "research_documents",
)


def _dedicated_test_url() -> str:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL", "")
    if not url:
        pytest.skip("no dedicated _test PostgreSQL database is configured")
    return url


@pytest.fixture(scope="module")
def database() -> PostgresDatabase:
    instance = PostgresDatabase(_dedicated_test_url())
    try:
        instance.initialize()
        yield instance
    finally:
        instance.close()


@pytest.fixture
def repo(database: PostgresDatabase) -> PostgresResearchLibraryRepository:
    """An empty research library: every case starts from the same known state."""
    repository = PostgresResearchLibraryRepository(database)
    with database.start().begin() as connection:
        connection.exec_driver_sql(
            f"TRUNCATE {', '.join(RESEARCH_TABLES)} RESTART IDENTITY CASCADE"
        )
    return repository


@pytest.fixture
def mint() -> Callable[[str], str]:
    """A per-call unique suffix, so cases never collide inside a shared database."""

    def _mint(prefix: str) -> str:
        return f"{prefix}_{uuid4().hex[:12]}"

    return _mint


def _document(mint, prefix: str = "doc", **overrides: object) -> ResearchDocument:
    payload: dict[str, object] = {
        "document_id": mint(prefix),
        "title": "2026 年储能行业中期策略",
        "document_type": "report",
        "source_weight": Decimal("0.8"),
        "created_at": NOW,
    }
    payload.update(overrides)
    return ResearchDocument.model_validate(payload)


def _version(
    mint,
    document_id: str,
    *,
    version_number: int = 1,
    status: str = "PROCESSING",
    generation: str | None = None,
    file_hash: str | None = None,
    **overrides: object,
) -> ResearchDocumentVersion:
    payload: dict[str, object] = {
        "document_version_id": mint("docv"),
        "document_id": document_id,
        "version_number": version_number,
        "status": status,
        "uploaded_at": NOW,
        "original_file_hash": file_hash or mint("sha256"),
        "index_generation": generation or mint("gen"),
        "indexed_at": NOW,
        "expected_chunk_count": 2,
    }
    payload.update(overrides)
    return ResearchDocumentVersion.model_validate(payload)


def _chunk(mint, document: ResearchDocument, version: ResearchDocumentVersion, **overrides):
    payload: dict[str, object] = {
        "chunk_id": mint("chunk"),
        "document_id": document.document_id,
        "document_version_id": version.document_version_id,
        "chunk_type": ChunkType.TEXT,
        "content": "海外储能订单在 2026 年第二季度明显增长。",
        "content_hash": mint("hash"),
        "source": SourceLocator(
            page_start=18,
            page_end=18,
            section_path=("第三章 行业跟踪",),
            spans=(SourceSpan(start=0, end=12),),
        ),
        "content_origin": ExtractionMethod.NATIVE,
        "created_at": NOW,
    }
    payload.update(overrides)
    return ResearchChunk.model_validate(payload)


def _job(mint, document: ResearchDocument, version: ResearchDocumentVersion, **overrides):
    payload: dict[str, object] = {
        "job_id": mint("job"),
        "document_id": document.document_id,
        "document_version_id": version.document_version_id,
        "status": IngestionStatus.RECEIVED,
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return IngestionJob.model_validate(payload)


def _outbox_event(mint, version: ResearchDocumentVersion, **overrides) -> IndexOutboxEvent:
    payload: dict[str, object] = {
        "event_id": mint("evt"),
        "document_version_id": version.document_version_id,
        "index_generation": version.index_generation,
        "operation": OutboxOperation.PUBLISH_GENERATION,
        "available_at": NOW,
        "created_at": NOW,
    }
    payload.update(overrides)
    return IndexOutboxEvent.model_validate(payload)


def test_create_document_and_version_round_trip(repo, mint):
    document = repo.create_document(_document(mint))
    assert repo.get_document(document.document_id) == document

    version = repo.create_version(
        _version(mint, document.document_id), upload_key=mint("upload")
    )
    assert repo.get_version(version.document_version_id) == version
    assert repo.list_versions(document.document_id) == (version,)


def test_unknown_document_and_version_read_back_as_none(repo):
    assert repo.get_document("doc_missing") is None
    assert repo.get_version("docv_missing") is None


def test_replaying_an_upload_key_returns_the_same_version_instead_of_a_second_row(repo, mint):
    """The whole point of the idempotency key: a retried upload must not fork a version."""
    document = repo.create_document(_document(mint))
    upload_key = mint("upload")
    content_hash = mint("sha256")

    first = repo.create_version(
        _version(mint, document.document_id, file_hash=content_hash), upload_key=upload_key
    )
    replayed = repo.create_version(
        _version(mint, document.document_id, file_hash=content_hash), upload_key=upload_key
    )

    assert replayed.document_version_id == first.document_version_id
    assert len(repo.list_versions(document.document_id)) == 1


def test_reusing_an_upload_key_for_different_content_is_a_conflict(repo, mint):
    document = repo.create_document(_document(mint))
    upload_key = mint("upload")
    repo.create_version(
        _version(mint, document.document_id, file_hash=mint("sha256")), upload_key=upload_key
    )
    with pytest.raises(ResearchLibraryConflict):
        repo.create_version(
            _version(mint, document.document_id, file_hash=mint("sha256")),
            upload_key=upload_key,
        )


def test_a_document_cannot_carry_two_versions_with_the_same_number(repo, mint):
    document = repo.create_document(_document(mint))
    repo.create_version(_version(mint, document.document_id, version_number=1))
    with pytest.raises(ResearchLibraryConflict):
        repo.create_version(_version(mint, document.document_id, version_number=1))


def seeded_versions(repo, mint) -> tuple[ResearchDocumentVersion, ResearchDocumentVersion]:
    document = repo.create_document(_document(mint))
    old = _version(mint, document.document_id, version_number=1, status="ACTIVE")
    repo.create_version(old)
    new = _version(mint, document.document_id, version_number=2, status="PROCESSING")
    repo.create_version(new)
    repo.set_current_version(document.document_id, old.document_version_id)
    return old, new


def test_activate_version_atomically_supersedes_previous(repo, mint):
    old, new = seeded_versions(repo, mint)
    repo.activate_version(new.document_version_id, expected_status=DocumentVersionStatus.PROCESSING)
    assert repo.get_version(old.document_version_id).status is DocumentVersionStatus.SUPERSEDED
    assert repo.get_version(new.document_version_id).status is DocumentVersionStatus.ACTIVE


def test_activation_also_moves_the_document_pointer(repo, mint):
    old, new = seeded_versions(repo, mint)
    repo.activate_version(new.document_version_id, expected_status=DocumentVersionStatus.PROCESSING)
    assert repo.get_document(new.document_id).current_version_id == new.document_version_id


def test_activation_is_refused_when_the_expected_status_is_already_gone(repo, mint):
    """Two publishers racing on one version: the loser must fail, not overwrite."""
    _, new = seeded_versions(repo, mint)
    repo.activate_version(new.document_version_id, expected_status=DocumentVersionStatus.PROCESSING)
    with pytest.raises(ResearchLibraryConflict):
        repo.activate_version(
            new.document_version_id, expected_status=DocumentVersionStatus.PROCESSING
        )


def test_no_document_ends_up_with_two_active_versions(repo, mint):
    old, new = seeded_versions(repo, mint)
    repo.activate_version(new.document_version_id, expected_status=DocumentVersionStatus.PROCESSING)
    statuses = repo.load_version_statuses([old.document_version_id, new.document_version_id])
    assert list(statuses.values()).count(DocumentVersionStatus.ACTIVE) == 1


def test_only_one_worker_can_hold_the_ingestion_lease(repo, mint):
    document = repo.create_document(_document(mint))
    version = repo.create_version(_version(mint, document.document_id))
    job = repo.create_ingestion_job(_job(mint, document, version))

    claimed = repo.acquire_ingestion_job(
        job.job_id, worker_id="worker-1", now=NOW, lease_seconds=LEASE_SECONDS
    )
    assert claimed.attempt_id == 1
    assert claimed.worker_id == "worker-1"

    with pytest.raises(ResearchLibraryConflict):
        repo.acquire_ingestion_job(
            job.job_id, worker_id="worker-2", now=NOW, lease_seconds=LEASE_SECONDS
        )


def test_the_same_worker_may_renew_its_own_live_lease(repo, mint):
    document = repo.create_document(_document(mint))
    version = repo.create_version(_version(mint, document.document_id))
    job = repo.create_ingestion_job(_job(mint, document, version))
    repo.acquire_ingestion_job(
        job.job_id, worker_id="worker-1", now=NOW, lease_seconds=LEASE_SECONDS
    )

    renewed = repo.acquire_ingestion_job(
        job.job_id,
        worker_id="worker-1",
        now=NOW + timedelta(seconds=30),
        lease_seconds=LEASE_SECONDS,
    )
    assert renewed.attempt_id == 1
    assert renewed.lease_expires_at == NOW + timedelta(seconds=30 + LEASE_SECONDS)


def test_a_live_lease_blocks_takeover_but_an_expired_one_allows_it(repo, mint):
    document = repo.create_document(_document(mint))
    version = repo.create_version(_version(mint, document.document_id))
    job = repo.create_ingestion_job(_job(mint, document, version))
    repo.acquire_ingestion_job(
        job.job_id, worker_id="worker-1", now=NOW, lease_seconds=LEASE_SECONDS
    )

    with pytest.raises(ResearchLibraryConflict):
        repo.acquire_ingestion_job(
            job.job_id,
            worker_id="worker-2",
            now=NOW + timedelta(seconds=LEASE_SECONDS - 1),
            lease_seconds=LEASE_SECONDS,
        )

    taken_over = repo.acquire_ingestion_job(
        job.job_id,
        worker_id="worker-2",
        now=NOW + timedelta(seconds=LEASE_SECONDS + 1),
        lease_seconds=LEASE_SECONDS,
    )
    assert taken_over.attempt_id == 2
    assert taken_over.worker_id == "worker-2"


def test_a_stale_attempt_cannot_write_its_result_back(repo, mint):
    """The late result of a superseded attempt is rejected by the row predicate."""
    document = repo.create_document(_document(mint))
    version = repo.create_version(_version(mint, document.document_id))
    job = repo.create_ingestion_job(_job(mint, document, version))
    first = repo.acquire_ingestion_job(
        job.job_id, worker_id="worker-1", now=NOW, lease_seconds=LEASE_SECONDS
    )
    second = repo.acquire_ingestion_job(
        job.job_id,
        worker_id="worker-2",
        now=NOW + timedelta(seconds=LEASE_SECONDS + 1),
        lease_seconds=LEASE_SECONDS,
    )

    repo.save_ingestion_job(
        second,
        expected_status=IngestionStatus.RECEIVED,
        expected_attempt=second.attempt_id,
    )

    with pytest.raises(ResearchLibraryConflict):
        repo.save_ingestion_job(
            first,
            expected_status=IngestionStatus.RECEIVED,
            expected_attempt=first.attempt_id,
        )


def test_chunks_are_appended_in_order_and_read_back_with_their_locator(repo, mint):
    document = repo.create_document(_document(mint))
    version = repo.create_version(_version(mint, document.document_id))
    first = _chunk(mint, document, version)
    second = _chunk(
        mint, document, version, content="碳酸锂价格在同期明显回落。", chunk_type=ChunkType.TABLE
    )

    repo.append_chunks([first, second])

    stored = repo.list_chunks(version.document_version_id)
    assert [chunk.chunk_id for chunk in stored] == [first.chunk_id, second.chunk_id]
    assert stored[1].chunk_type is ChunkType.TABLE
    assert stored[1].source.page_start == 18
    assert repo.count_chunks(version.document_version_id) == 2


def test_chunk_embedding_status_advances_only_for_known_chunks(repo, mint):
    document = repo.create_document(_document(mint))
    version = repo.create_version(_version(mint, document.document_id))
    chunk = _chunk(mint, document, version)
    repo.append_chunks([chunk])
    assert chunk.embedding_status is ChunkEmbeddingStatus.PENDING

    repo.mark_chunks_embedded([chunk.chunk_id])

    assert repo.get_chunk(chunk.chunk_id).embedding_status is ChunkEmbeddingStatus.EMBEDDED


def test_an_outbox_event_is_claimed_once_and_finished_by_its_claimer(repo, mint):
    document = repo.create_document(_document(mint))
    version = repo.create_version(_version(mint, document.document_id))
    event = repo.enqueue_index_event(_outbox_event(mint, version))

    claimed = repo.claim_outbox_events(worker_id="indexer-1", now=NOW, limit=10)
    assert [item.event_id for item in claimed] == [event.event_id]
    assert claimed[0].status is OutboxStatus.CLAIMED
    assert claimed[0].claimed_by == "indexer-1"

    assert repo.claim_outbox_events(worker_id="indexer-2", now=NOW, limit=10) == ()

    finished = repo.finish_outbox_event(
        event.event_id, worker_id="indexer-1", now=NOW + timedelta(seconds=5)
    )
    assert finished.status is OutboxStatus.DONE
    assert repo.claim_outbox_events(worker_id="indexer-3", now=NOW, limit=10) == ()


def test_an_event_scheduled_for_later_is_not_claimable_yet(repo, mint):
    document = repo.create_document(_document(mint))
    version = repo.create_version(_version(mint, document.document_id))
    repo.enqueue_index_event(
        _outbox_event(mint, version, available_at=NOW + timedelta(minutes=10))
    )
    assert repo.claim_outbox_events(worker_id="indexer-1", now=NOW, limit=10) == ()

    later = repo.claim_outbox_events(
        worker_id="indexer-1", now=NOW + timedelta(minutes=11), limit=10
    )
    assert len(later) == 1


def test_a_failed_event_records_why_and_another_worker_may_retry_it(repo, mint):
    document = repo.create_document(_document(mint))
    version = repo.create_version(_version(mint, document.document_id))
    event = repo.enqueue_index_event(_outbox_event(mint, version))
    repo.claim_outbox_events(worker_id="indexer-1", now=NOW, limit=10)

    failed = repo.finish_outbox_event(
        event.event_id, worker_id="indexer-1", now=NOW, error="milvus refused the upsert"
    )
    assert failed.status is OutboxStatus.FAILED
    assert failed.last_error == "milvus refused the upsert"

    retried = repo.claim_outbox_events(
        worker_id="indexer-2", now=NOW + timedelta(seconds=5), limit=10
    )
    assert [item.event_id for item in retried] == [event.event_id]
    assert retried[0].attempt_count == 2


def test_only_the_claimer_may_finish_an_event(repo, mint):
    document = repo.create_document(_document(mint))
    version = repo.create_version(_version(mint, document.document_id))
    event = repo.enqueue_index_event(_outbox_event(mint, version))
    repo.claim_outbox_events(worker_id="indexer-1", now=NOW, limit=10)

    with pytest.raises(ResearchLibraryConflict):
        repo.finish_outbox_event(event.event_id, worker_id="indexer-2", now=NOW)


def test_soft_delete_defers_purge_and_restore_clears_it(repo, mint):
    document = repo.create_document(_document(mint))
    deleted = repo.soft_delete_document(document.document_id, now=NOW, retention_days=30)
    assert deleted.deleted_at == NOW
    assert deleted.purge_after == NOW + timedelta(days=30)
    assert repo.list_documents() == ()
    assert [item.document_id for item in repo.list_documents(include_deleted=True)] == [
        document.document_id
    ]

    restored = repo.restore_document(document.document_id, now=NOW + timedelta(days=2))
    assert restored.deleted_at is None
    assert restored.purge_after is None
    assert [item.document_id for item in repo.list_documents()] == [document.document_id]


def test_a_deleted_document_cannot_be_deleted_twice(repo, mint):
    document = repo.create_document(_document(mint))
    repo.soft_delete_document(document.document_id, now=NOW, retention_days=30)
    with pytest.raises(ResearchLibraryConflict):
        repo.soft_delete_document(document.document_id, now=NOW, retention_days=30)


def test_retrieval_audit_keeps_the_whole_ranking_provenance(repo, mint):
    audit = RetrievalAuditRecord.model_validate(
        {
            "retrieval_id": mint("retr"),
            "run_id": "run_2026_09_18",
            "task_id": "task_a2_research",
            "attempt_id": 1,
            "role": "A2",
            "question": "储能板块近期上涨是否与海外需求改善有关？",
            "query_fingerprint": mint("fp"),
            "filters": {"sector": "储能", "document_types": ["report"]},
            "corpus_generation": "gen_2026_09_18",
            "provider_versions": {"embedding": "bge-m3@1", "reranker": "bge-reranker-v2@1"},
            "dense_candidates": ({"chunk_id": "chunk_a", "score": 0.81},),
            "bm25_candidates": ({"chunk_id": "chunk_a", "score": 12.5},),
            "fused_candidates": ({"chunk_id": "chunk_a", "score": 0.03},),
            "reranked_candidates": ({"chunk_id": "chunk_a", "score": 0.77},),
            "parent_expansions": ({"chunk_id": "chunk_parent", "child_id": "chunk_a"},),
            "claims": ({"claim_id": "claim_1", "source_chunk_id": "chunk_a"},),
            "conflicts": ({"status": "UNRESOLVED", "claim_ids": ["claim_1", "claim_2"]},),
            "returned_evidence": ({"chunk_id": "chunk_a", "rank": 1},),
            "duration_ms": 812,
            "provider_calls": 3,
            "input_tokens": 4096,
            "output_tokens": 512,
            "cost_cny": Decimal("0.0123"),
            "created_at": NOW,
        }
    )
    repo.record_retrieval_audit(audit)

    stored = repo.get_retrieval_audit(audit.retrieval_id)
    assert stored == audit
    assert stored.cost_cny == Decimal("0.0123")


def test_an_unresolved_conflict_is_persisted_as_unresolved(repo, mint):
    """Spec 14: a conflict NLI cannot settle must stay visible, not be silently won."""
    audit = RetrievalAuditRecord.model_validate(
        {
            "retrieval_id": mint("retr"),
            "question": "储能趋势",
            "query_fingerprint": mint("fp"),
            "corpus_generation": "gen_1",
            "conflicts": (
                {
                    "status": "UNRESOLVED",
                    "claim_ids": ["claim_a", "claim_b"],
                    "selected_claim_id": None,
                },
            ),
            "created_at": NOW,
        }
    )
    repo.record_retrieval_audit(audit)
    stored = repo.get_retrieval_audit(audit.retrieval_id)
    assert stored.conflicts[0]["status"] == "UNRESOLVED"
    assert stored.conflicts[0]["selected_claim_id"] is None


def test_an_audit_row_is_never_rewritten_by_a_second_retrieval(repo, mint):
    retrieval_id = mint("retr")
    first = RetrievalAuditRecord.model_validate(
        {
            "retrieval_id": retrieval_id,
            "question": "第一次提问",
            "query_fingerprint": mint("fp"),
            "corpus_generation": "gen_1",
            "created_at": NOW,
        }
    )
    repo.record_retrieval_audit(first)
    second = RetrievalAuditRecord.model_validate(
        {
            "retrieval_id": retrieval_id,
            "question": "第二次提问",
            "query_fingerprint": mint("fp"),
            "corpus_generation": "gen_1",
            "created_at": NOW,
        }
    )
    with pytest.raises(ResearchLibraryConflict):
        repo.record_retrieval_audit(second)
    assert repo.get_retrieval_audit(retrieval_id).question == "第一次提问"
