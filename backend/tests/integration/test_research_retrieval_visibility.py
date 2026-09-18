"""检索与原文查看落在真库上的那一半。

`test_retrieval.py` 用内存权威库把逻辑跑了一遍；这里跑的是同一套逻辑里**只有真库才
成立**的部分：

- 审计记录要先被序列化成 JSONB 再读回来。内存假实现存的是 Python 对象本身，因此
  "候选句柄读回来还是不是同一个"在那里永远为真——而 `inspect` 的授权完全建立在这件
  事上。这条线上任何一处把 `candidate_id` 变成了别的东西，检索功能看起来仍然正常，
  只有查看原文会全线失败。
- `load_chunks` 是这一次新加的批量读：查不到的 ID 必须安静地缺席，而不是被编成一条
  空记录。
- 状态复核读的是真库的 `research_document_versions`。删除、取代都不是这里做的事，
  这里是"删掉之后，一次已经发出的候选还能不能看"。

向量索引仍然是内存实现：Milvus 需要一台真服务器，而这份用例要验的是 PostgreSQL 那一侧。
只跑真库：没有配置专用测试库时整体跳过。
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from datetime import datetime

import pytest
from sector_pulse.application.research_library.retrieval import (
    CandidateWithdrawn,
    ResearchRetrievalService,
    RetrievalAccessDenied,
    RetrievalContext,
    SourceInspection,
)
from sector_pulse.config.rag_settings import RagSettings
from sector_pulse.domain.research_library.models import (
    ChunkType,
    DocumentType,
    DocumentVersionStatus,
    ExtractionMethod,
    ResearchChunk,
    ResearchDocument,
    ResearchDocumentVersion,
    SourceLocator,
)
from sector_pulse.domain.research_library.retrieval import RetrievalQuery
from sector_pulse.infrastructure.research_library.providers.fixture import (
    FixtureEmbeddingProvider,
    FixtureRerankerProvider,
)
from sector_pulse.infrastructure.research_library.vector.memory import InMemoryVectorIndex
from sector_pulse.ports.vector_index import VectorRecord
from sector_pulse.storage.postgres.database import PostgresDatabase
from sector_pulse.storage.postgres.research_library.repository import (
    PostgresResearchLibraryRepository,
)
from sqlalchemy import text

pytestmark = pytest.mark.postgres

NOW = datetime.fromisoformat("2026-09-18T02:00:00+00:00")
QUESTION = "储能海外需求"
QUERY_VECTOR = (1.0, 0.0, 0.0, 0.0)
SECTION = ("海外需求", "欧洲市场")

CONTEXT = RetrievalContext(run_id="run_0001", task_id="task_0001", attempt_id=1, role="A2")
OTHER_TASK = RetrievalContext(run_id="run_0001", task_id="task_0002", attempt_id=1, role="A2")

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
    counter = {"value": 0}

    def _mint(prefix: str) -> str:
        counter["value"] += 1
        return f"{prefix}_{counter['value']:04d}_{os.urandom(4).hex()}"

    return _mint


SETTINGS = RagSettings(
    dense_top_k=5,
    bm25_top_k=5,
    fusion_top_k=6,
    rerank_top_k=3,
    max_candidates_per_document=3,
    max_candidate_text_chars=200,
    max_inspected_chars=400,
    max_parent_expansion_chunks=2,
)


class Seeded:
    """一份刚写完、可以被检索的语料。"""

    def __init__(
        self,
        *,
        document_id: str,
        version_id: str,
        generation: str,
        chunks: tuple[str, ...],
        index: InMemoryVectorIndex,
    ) -> None:
        self.document_id = document_id
        self.version_id = version_id
        self.generation = generation
        self.chunks = chunks
        self.index = index


@pytest.fixture
def seed(
    repo: PostgresResearchLibraryRepository, database: PostgresDatabase, mint: Callable[[str], str]
) -> Callable[..., Seeded]:
    """登记一版，连同它的切片与索引记录。

    走的是摄取的**写入路径**而不是它前面的解析流水线：检索要的是"库里已经有这些切片"，
    切片怎么被切出来是 Task 8 的事，而这里要验的是它们读回来时是什么样子。
    """

    def _seed(
        texts: Sequence[str],
        *,
        status: DocumentVersionStatus = DocumentVersionStatus.ACTIVE,
        requires_verification: Sequence[bool] | None = None,
    ) -> Seeded:
        document_id = mint("doc")
        version_id = mint("ver")
        generation = mint("gen")
        flags = tuple(requires_verification or (False,) * len(texts))

        repo.create_document(
            ResearchDocument(
                document_id=document_id,
                title="年度策略",
                document_type=DocumentType.REPORT,
                created_at=NOW,
            )
        )
        version = repo.create_version(
            ResearchDocumentVersion(
                document_version_id=version_id,
                document_id=document_id,
                version_number=1,
                status=DocumentVersionStatus.PROCESSING,
                uploaded_at=NOW,
                original_file_hash=f"hash_{version_id}",
                parser_version="parser-v1",
                chunking_policy_version="policy-v1",
                embedding_provider="fixture",
                embedding_model_version="fixture-embedding-v1",
                index_generation=generation,
                expected_chunk_count=len(texts),
                indexed_at=NOW,
            )
        )
        repo.save_version_metadata(version, expected_status=DocumentVersionStatus.PROCESSING)
        chunk_ids = tuple(f"{version_id}_chunk_{index}" for index in range(len(texts)))
        repo.append_chunks(
            tuple(
                ResearchChunk(
                    chunk_id=chunk_ids[index],
                    document_id=document_id,
                    document_version_id=version_id,
                    chunk_type=ChunkType.TEXT,
                    content=text,
                    content_hash=f"hash_{chunk_ids[index]}",
                    source=SourceLocator(
                        page_start=index + 1, page_end=index + 1, section_path=SECTION
                    ),
                    content_origin=ExtractionMethod.NATIVE,
                    requires_verification=flags[index],
                    created_at=NOW,
                )
                for index, text in enumerate(texts)
            )
        )
        if status is DocumentVersionStatus.ACTIVE:
            repo.activate_version(version_id, expected_status=DocumentVersionStatus.PROCESSING)
        else:
            # 其余状态没有正向路径：它们由删除、取代或失败产生，这里直接写成目标状态，
            # 因为这一条用例要问的是"处于这个状态的版本，检索还看得见吗"。
            with database.start().begin() as connection:
                connection.execute(
                    text(
                        "UPDATE research_document_versions SET status = :status "
                        "WHERE document_version_id = :version_id"
                    ),
                    {"status": status.value, "version_id": version_id},
                )

        index = InMemoryVectorIndex()
        index.stage(
            generation=generation,
            records=tuple(
                VectorRecord(
                    chunk_id=chunk_ids[index],
                    document_id=document_id,
                    document_version_id=version_id,
                    chunk_type=ChunkType.TEXT,
                    document_type=DocumentType.REPORT,
                    published_at=NOW,
                    content_origin=ExtractionMethod.NATIVE,
                    requires_verification=flags[index],
                    content=text,
                    dense_vector=QUERY_VECTOR,
                )
                for index, text in enumerate(texts)
            ),
        )
        index.publish(generation=generation)
        return Seeded(
            document_id=document_id,
            version_id=version_id,
            generation=generation,
            chunks=chunk_ids,
            index=index,
        )

    return _seed


def build_service(
    repo: PostgresResearchLibraryRepository, index: InMemoryVectorIndex, generation: str
) -> ResearchRetrievalService:
    return ResearchRetrievalService(
        repository=repo,
        vector_index=index,
        embedding_provider=FixtureEmbeddingProvider(
            dimension=len(QUERY_VECTOR), vectors={QUESTION: QUERY_VECTOR}
        ),
        reranker=FixtureRerankerProvider(),
        settings=SETTINGS,
        corpus_generation=lambda: generation,
        clock=lambda: NOW,
    )


def test_load_chunks_returns_exactly_the_slices_that_were_stored(
    repo: PostgresResearchLibraryRepository, seed: Callable[..., Seeded]
) -> None:
    corpus = seed([QUESTION, f"{QUESTION}增长", f"{QUESTION}回落"])

    loaded = repo.load_chunks([corpus.chunks[0], corpus.chunks[2], "chunk_never_written"])

    assert sorted(loaded) == sorted([corpus.chunks[0], corpus.chunks[2]])
    assert loaded[corpus.chunks[0]].content == QUESTION
    assert loaded[corpus.chunks[0]].source.page_start == 1
    assert loaded[corpus.chunks[2]].source.section_path == SECTION


def test_load_chunks_answers_an_empty_request_without_a_query(
    repo: PostgresResearchLibraryRepository,
) -> None:
    assert repo.load_chunks([]) == {}


def test_a_retrieval_survives_a_fresh_service_and_can_still_be_inspected(
    repo: PostgresResearchLibraryRepository,
    database: PostgresDatabase,
    seed: Callable[..., Seeded],
) -> None:
    """授权名单是从 JSONB 里读回来的，不是内存里留着的。"""
    corpus = seed([QUESTION])

    first = build_service(repo, corpus.index, corpus.generation)
    outcome = first.search(CONTEXT, RetrievalQuery(question=QUESTION))
    assert len(outcome.candidates) == 1

    reader = PostgresResearchLibraryRepository(database)
    second = build_service(reader, InMemoryVectorIndex(), corpus.generation)
    inspection = second.inspect(
        CONTEXT, outcome.retrieval_id, outcome.candidates[0].candidate_id
    )

    assert isinstance(inspection, SourceInspection)
    assert inspection.chunk_id == corpus.chunks[0]
    assert inspection.text == QUESTION
    assert inspection.document_version_id == corpus.version_id


def test_the_stored_audit_carries_the_filters_and_the_returned_candidates(
    repo: PostgresResearchLibraryRepository, seed: Callable[..., Seeded]
) -> None:
    corpus = seed([QUESTION])

    outcome = build_service(repo, corpus.index, corpus.generation).search(
        CONTEXT, RetrievalQuery(question=QUESTION, document_types=(DocumentType.REPORT,))
    )
    stored = repo.get_retrieval_audit(outcome.retrieval_id)

    assert stored is not None
    assert stored.query_fingerprint == outcome.query_fingerprint
    assert stored.filters["document_types"] == ["report"]
    assert stored.fused_candidates[0]["chunk_id"] == corpus.chunks[0]
    assert stored.returned_evidence[0]["candidate_id"] == (
        outcome.candidates[0].candidate_id
    )
    assert stored.created_at == NOW


def test_an_inspection_from_another_task_is_still_refused_after_the_round_trip(
    repo: PostgresResearchLibraryRepository, seed: Callable[..., Seeded]
) -> None:
    corpus = seed([QUESTION])

    outcome = build_service(repo, corpus.index, corpus.generation).search(
        CONTEXT, RetrievalQuery(question=QUESTION)
    )

    with pytest.raises(RetrievalAccessDenied):
        build_service(repo, corpus.index, corpus.generation).inspect(
            OTHER_TASK, outcome.retrieval_id, outcome.candidates[0].candidate_id
        )


def test_a_version_deleted_after_the_search_makes_its_candidate_uninspectable(
    repo: PostgresResearchLibraryRepository,
    database: PostgresDatabase,
    seed: Callable[..., Seeded],
) -> None:
    """规格 16.3：删除立刻生效，一条已经发出的候选也不能例外。"""
    corpus = seed([QUESTION])
    outcome = build_service(repo, corpus.index, corpus.generation).search(
        CONTEXT, RetrievalQuery(question=QUESTION)
    )
    candidate_id = outcome.candidates[0].candidate_id

    with database.start().begin() as connection:
        connection.execute(
            text(
                "UPDATE research_document_versions SET status = 'DELETED' "
                "WHERE document_version_id = :version_id"
            ),
            {"version_id": corpus.version_id},
        )

    with pytest.raises(CandidateWithdrawn):
        build_service(repo, corpus.index, corpus.generation).inspect(
            CONTEXT, outcome.retrieval_id, candidate_id
        )


def test_a_search_that_finds_nothing_still_leaves_a_readable_audit(
    repo: PostgresResearchLibraryRepository,
) -> None:
    outcome = build_service(repo, InMemoryVectorIndex(), "gen_empty").search(
        CONTEXT, RetrievalQuery(question=QUESTION)
    )

    stored = repo.get_retrieval_audit(outcome.retrieval_id)

    assert stored is not None
    assert stored.returned_evidence == ()
    assert stored.fused_candidates == ()
    assert stored.corpus_generation == "gen_empty"
    assert stored.provider_calls == 1


def test_an_empty_audit_is_not_confused_with_a_missing_one(
    repo: PostgresResearchLibraryRepository,
) -> None:
    assert repo.get_retrieval_audit("ret_never_issued") is None

