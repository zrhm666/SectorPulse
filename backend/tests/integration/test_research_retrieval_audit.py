"""What a retrieval leaves behind: the audit, the cache key, and the metrics (spec 17, 20.1, 20.2).

Task 11 already writes a retrieval audit; this file is about what that audit is *allowed to
contain*. Three properties are only observable over real components:

- The audit and the plain-log projection have to be serialised and then searched for a
  substring. Writing the document body into a free-text field is invisible to a test that reads
  fields back one by one, because the field it landed in is not the one being asserted on.
- `CorpusGeneration` fingerprints the authoritative store, so a document that was published,
  deleted, restored, or re-weighted has to move the fingerprint. That needs a repository whose
  `list_documents`/`list_versions` answer like the real one, not a stub list.
- The cache's invalidation rule is that a document deleted since an entry was written must not
  be served from it. The strongest form of that test runs a real search, keys the result,
  deletes the document, and then asks for the key again — and the key has to be built from what
  the audit recorded, because on a real store that is the only copy that survives.

The vector index is the in-memory implementation: this file is about the corpus and the audit,
not about Milvus.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from sector_pulse.application.research_library.audit import (
    UnsafeResultReference,
    candidate_reference,
    retrieval_log_entry,
    safe_result_reference,
)
from sector_pulse.application.research_library.cache import (
    CACHE_KEY_COMPONENTS,
    NO_NLI_MODEL,
    CacheKey,
    CorpusGeneration,
    IncompleteCorpusScan,
    InMemoryRetrievalCache,
    cache_key,
)
from sector_pulse.application.research_library.observability import (
    MetricName,
    MetricsRegistry,
    UnsafeMetricLabel,
)
from sector_pulse.application.research_library.retrieval import (
    ResearchRetrievalService,
    RetrievalContext,
    RetrievalOutcome,
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
from sector_pulse.domain.research_library.retrieval import (
    ConflictDecision,
    ConflictRule,
    ConflictStatus,
    RetrievalQuery,
)
from sector_pulse.infrastructure.research_library.providers.fixture import (
    FixtureEmbeddingProvider,
    FixtureRerankerProvider,
)
from sector_pulse.infrastructure.research_library.vector.memory import InMemoryVectorIndex
from sector_pulse.ports.vector_index import VectorRecord

from backend.tests.research_library_fakes import InMemoryResearchLibraryRepository

NOW = datetime(2026, 9, 18, 9, 0, tzinfo=UTC)
PUBLISHED = date(2026, 6, 1)
GENERATION = "gen_2026_09_18"
QUESTION = "储能海外需求"
#: 正文刻意包含问题里的词，BM25 那一半才召得回来；也刻意足够长，好让"正文没被写进审计"
#: 这件事在截断之后依然可断言。
CORPUS_TEXT = "储能海外需求在 2026 年上半年同比增长 42%，欧洲市场贡献了主要增量，美国市场持平。"
SECOND_TEXT = "储能海外需求的价格战集中在 2025 年下半年，主要厂商毛利率下滑 3 个百分点。"
QUERY_VECTOR = (1.0, 0.0, 0.0, 0.0)
DOCUMENT_VECTOR = (1.0, 0.0, 0.0, 0.0)

CONTEXT = RetrievalContext(run_id="run_0001", task_id="task_0001", attempt_id=1, role="A2")


def settings(**overrides: Any) -> RagSettings:
    base: dict[str, Any] = {
        "dense_top_k": 3,
        "bm25_top_k": 3,
        "fusion_top_k": 4,
        "rerank_top_k": 3,
        "max_candidates_per_document": 3,
        "duplicate_overlap_ratio": 0.8,
        "max_candidate_text_chars": 200,
        "max_inspected_chars": 400,
        "max_parent_expansion_chunks": 2,
    }
    return RagSettings(**(base | overrides))


@dataclass(frozen=True)
class _Doc:
    chunk_id: str
    text: str
    document_id: str = "doc_0001"
    version_id: str = "ver_0001"
    version_number: int = 1
    page: int = 3
    section: tuple[str, ...] = ("海外需求",)
    status: DocumentVersionStatus = DocumentVersionStatus.ACTIVE
    content_origin: ExtractionMethod = ExtractionMethod.NATIVE


@dataclass
class _Corpus:
    """A small corpus, indexed and searchable, over the in-memory repository."""

    docs: list[_Doc] = field(default_factory=list)
    source_weight: Decimal = Decimal("0.5")
    scan_limit: int = 100
    config: RagSettings = field(default_factory=settings)
    repository: InMemoryResearchLibraryRepository = field(init=False)
    index: InMemoryVectorIndex = field(init=False)
    service: ResearchRetrievalService = field(init=False)
    generation: CorpusGeneration = field(init=False)

    def __post_init__(self) -> None:
        self.repository = InMemoryResearchLibraryRepository()
        self.index = InMemoryVectorIndex()
        self.generation = CorpusGeneration(self.repository, scan_limit=self.scan_limit)
        self.service = ResearchRetrievalService(
            repository=self.repository,
            vector_index=self.index,
            embedding_provider=FixtureEmbeddingProvider(
                dimension=len(QUERY_VECTOR), vectors={QUESTION: QUERY_VECTOR}
            ),
            reranker=FixtureRerankerProvider(),
            settings=self.config,
            corpus_generation=self.generation,
            clock=lambda: NOW,
        )

    # --- 摆语料 ---

    def add(self, *docs: _Doc) -> None:
        self.docs.extend(docs)

    def publish(self, *, generation: str = GENERATION) -> None:
        for document_id in dict.fromkeys(doc.document_id for doc in self.docs):
            if self.repository.get_document(document_id) is not None:
                continue
            self.repository.create_document(
                ResearchDocument(
                    document_id=document_id,
                    title=f"{document_id} 标题",
                    document_type=DocumentType.REPORT,
                    source_weight=self.source_weight,
                    created_at=NOW,
                )
            )
        for version_id in dict.fromkeys(doc.version_id for doc in self.docs):
            group = [doc for doc in self.docs if doc.version_id == version_id]
            head = group[0]
            if self.repository.get_version(version_id) is not None:
                continue
            self.repository.create_version(
                ResearchDocumentVersion(
                    document_version_id=version_id,
                    document_id=head.document_id,
                    version_number=head.version_number,
                    status=head.status,
                    published_at=NOW if head.status is DocumentVersionStatus.ACTIVE else None,
                    uploaded_at=NOW,
                    original_file_hash=f"hash_{version_id}",
                    index_generation=generation,
                    expected_chunk_count=len(group),
                    indexed_at=NOW,
                )
            )
            self.repository.append_chunks(tuple(self._chunk(doc) for doc in group))
        records = [
            self._record(doc) for doc in self.docs if doc.status is DocumentVersionStatus.ACTIVE
        ]
        if records:
            self.index.stage(generation=generation, records=records)
            self.index.publish(generation=generation)

    def _chunk(self, doc: _Doc) -> ResearchChunk:
        return ResearchChunk(
            chunk_id=doc.chunk_id,
            document_id=doc.document_id,
            document_version_id=doc.version_id,
            chunk_type=ChunkType.TEXT,
            content=doc.text,
            content_hash=f"hash_{doc.chunk_id}",
            source=SourceLocator(page_start=doc.page, page_end=doc.page, section_path=doc.section),
            content_origin=doc.content_origin,
            created_at=NOW,
        )

    def _record(self, doc: _Doc) -> VectorRecord:
        return VectorRecord(
            chunk_id=doc.chunk_id,
            document_id=doc.document_id,
            document_version_id=doc.version_id,
            chunk_type=ChunkType.TEXT,
            document_type=DocumentType.REPORT,
            published_at=datetime(PUBLISHED.year, PUBLISHED.month, PUBLISHED.day, tzinfo=UTC),
            content_origin=doc.content_origin,
            content=doc.text,
            dense_vector=DOCUMENT_VECTOR,
        )

    # --- 用 ---

    def search(self, **query: Any) -> RetrievalOutcome:
        return self.service.search(CONTEXT, RetrievalQuery(question=QUESTION, **query))

    def audit(self, outcome: RetrievalOutcome):
        record = self.repository.get_retrieval_audit(outcome.retrieval_id)
        assert record is not None, "every search must leave an audit record behind"
        return record

    def key_for(self, outcome: RetrievalOutcome) -> CacheKey:
        """拼出这次检索的缓存键——用的全是审计里已经记下的东西。"""
        return self.key_from(self.audit(outcome))

    def key_from(self, audit) -> CacheKey:
        return cache_key(
            query_fingerprint=audit.query_fingerprint,
            corpus_generation=audit.corpus_generation,
            filters=audit.filters,
            provider_versions={**audit.provider_versions, "nli_model_version": NO_NLI_MODEL},
            settings=self.config,
        )

    def delete(self, document_id: str = "doc_0001") -> None:
        self.repository.soft_delete_document(document_id, now=NOW, retention_days=30)

    def restore(self, document_id: str = "doc_0001") -> None:
        self.repository.restore_document(document_id, now=NOW)


def build(*docs: _Doc, **kwargs: Any) -> _Corpus:
    corpus = _Corpus(**kwargs)
    corpus.add(*docs)
    corpus.publish()
    return corpus


# --- 审计记录里有什么、没有什么（规格 20.1） ---------------------------------


def test_the_audit_carries_the_identity_of_the_run_that_asked() -> None:
    corpus = build(_Doc(chunk_id="c_1", text=CORPUS_TEXT))

    outcome = corpus.search()
    audit = corpus.audit(outcome)

    assert (audit.run_id, audit.task_id, audit.attempt_id, audit.role) == (
        CONTEXT.run_id,
        CONTEXT.task_id,
        CONTEXT.attempt_id,
        CONTEXT.role,
    )
    assert audit.question == QUESTION
    assert audit.query_fingerprint == outcome.query_fingerprint
    assert audit.corpus_generation == corpus.generation()
    assert audit.provider_versions["embedding_model_version"] == "fixture-embedding-v1"
    assert audit.provider_versions["reranker_model_version"] == "fixture-reranker-v1"
    assert audit.provider_calls == 2
    assert audit.duration_ms is not None and audit.duration_ms >= 0
    assert audit.created_at == NOW


def test_the_audit_does_not_carry_the_document_body() -> None:
    """规格 20.1：普通日志不写完整文档正文。审计是同一份东西的另一面。"""
    corpus = build(_Doc(chunk_id="c_1", text=CORPUS_TEXT))

    audit = corpus.audit(corpus.search())
    serialised = json.dumps(audit.model_dump(mode="json"), ensure_ascii=False)

    assert len(audit.returned_evidence) == 1
    assert CORPUS_TEXT not in serialised
    assert CORPUS_TEXT[:20] not in serialised
    assert "text" not in audit.returned_evidence[0]


def test_the_returned_evidence_keeps_the_handle_and_the_locator_inspection_needs() -> None:
    corpus = build(_Doc(chunk_id="c_1", text=CORPUS_TEXT, page=7, section=("海外需求", "欧洲")))
    outcome = corpus.search()

    entry = corpus.audit(outcome).returned_evidence[0]

    assert entry["candidate_id"] == outcome.candidates[0].candidate_id
    assert entry["chunk_id"] == "c_1"
    assert entry["document_id"] == "doc_0001"
    assert entry["document_version_id"] == "ver_0001"
    assert entry["page_start"] == 7
    assert entry["section_path"] == ["海外需求", "欧洲"]
    assert entry["content_origin"] == ExtractionMethod.NATIVE.value
    assert entry["requires_verification"] is False
    assert entry["rerank_score"] is not None


def test_inspection_still_returns_the_body_the_audit_refused_to_store() -> None:
    """授权名单从审计里读，正文从权威库里读：审计省下的那一列不影响查看原文。"""
    corpus = build(_Doc(chunk_id="c_1", text=CORPUS_TEXT))
    outcome = corpus.search()

    inspection = corpus.service.inspect(
        CONTEXT, outcome.retrieval_id, outcome.candidates[0].candidate_id
    )

    assert isinstance(inspection, SourceInspection)
    assert inspection.text.startswith(CORPUS_TEXT[:20])
    assert inspection.chunk_id == "c_1"


def test_a_plain_log_entry_keeps_the_identities_and_the_counts_but_no_free_text() -> None:
    corpus = build(_Doc(chunk_id="c_1", text=CORPUS_TEXT))
    audit = corpus.audit(corpus.search())

    entry = retrieval_log_entry(audit)
    serialised = json.dumps(entry.model_dump(mode="json"), ensure_ascii=False)

    assert entry.retrieval_id == audit.retrieval_id
    assert (entry.run_id, entry.task_id, entry.role) == (CONTEXT.run_id, CONTEXT.task_id, "A2")
    assert (entry.returned, entry.fused, entry.provider_calls) == (1, 1, 2)
    assert entry.corpus_generation == audit.corpus_generation
    assert QUESTION not in serialised
    assert CORPUS_TEXT[:20] not in serialised


def test_a_result_reference_that_could_carry_a_body_is_refused() -> None:
    assert (
        safe_result_reference("provider.embedding", "openai", "text-embedding-3-small")
        == "provider.embedding/openai/text-embedding-3-small"
    )
    with pytest.raises(UnsafeResultReference):
        safe_result_reference("provider.embedding", CORPUS_TEXT)
    with pytest.raises(UnsafeResultReference):
        safe_result_reference("provider.embedding", "")
    with pytest.raises(UnsafeResultReference):
        safe_result_reference("a" * 512)


def test_a_candidate_reference_can_be_built_from_a_candidate_without_its_text() -> None:
    corpus = build(_Doc(chunk_id="c_1", text=CORPUS_TEXT))
    outcome = corpus.search()

    reference = candidate_reference(outcome.candidates[0])

    assert set(reference) == {
        "candidate_id",
        "chunk_id",
        "document_id",
        "document_version_id",
        "page_start",
        "page_end",
        "section_path",
        "content_origin",
        "requires_verification",
        "dense_score",
        "lexical_score",
        "fused_score",
        "rerank_score",
    }
    assert reference["candidate_id"] == outcome.candidates[0].candidate_id


# --- 缓存键与语料世代（规格 17） ---------------------------------------------


def test_the_cache_key_names_every_component_spec_17_lists() -> None:
    assert CACHE_KEY_COMPONENTS == (
        "query_fingerprint",
        "corpus_generation",
        "filters",
        "embedding_model_version",
        "reranker_model_version",
        "nli_model_version",
        "conflict_policy_version",
    )
    assert set(CacheKey.model_fields) == set(CACHE_KEY_COMPONENTS)


def test_the_key_is_built_from_what_the_retrieval_actually_observed() -> None:
    corpus = build(_Doc(chunk_id="c_1", text=CORPUS_TEXT))
    outcome = corpus.search()

    audit = corpus.audit(outcome)
    key = corpus.key_from(audit)

    assert key.query_fingerprint == outcome.query_fingerprint
    assert key.corpus_generation == corpus.generation()
    assert key.embedding_model_version == "fixture-embedding-v1"
    assert key.reranker_model_version == "fixture-reranker-v1"
    assert key.nli_model_version == NO_NLI_MODEL
    assert key.filters["document_types"] == []
    assert key.conflict_policy_version.startswith("cp_")


def test_a_missing_version_component_is_refused_instead_of_silently_dropped() -> None:
    """少一项就拼出一个"看起来完整"的键，而它会把两代模型的结果混在一条缓存里。"""
    with pytest.raises(ValueError, match="nli_model_version"):
        cache_key(
            query_fingerprint="q" * 16,
            corpus_generation=GENERATION,
            filters={},
            provider_versions={
                "embedding_model_version": "fixture-embedding-v1",
                "reranker_model_version": "fixture-reranker-v1",
            },
            settings=settings(),
        )


@pytest.mark.parametrize("component", CACHE_KEY_COMPONENTS)
def test_changing_any_single_component_changes_the_digest(component: str) -> None:
    corpus = build(_Doc(chunk_id="c_1", text=CORPUS_TEXT))
    original = corpus.key_for(corpus.search())

    changed = original.model_copy(update={component: _other_value(component, original)})

    assert changed.digest != original.digest


def _other_value(component: str, key: CacheKey) -> object:
    """One component moved one step, everything else identical."""
    if component == "filters":
        return {**key.filters, "include_unverified_leads": True}
    if component == "query_fingerprint":
        return "f" * len(key.query_fingerprint)
    return f"{getattr(key, component)}-other"


def test_the_same_corpus_and_the_same_versions_land_on_the_same_key() -> None:
    corpus = build(_Doc(chunk_id="c_1", text=CORPUS_TEXT))
    cache: InMemoryRetrievalCache[RetrievalOutcome] = InMemoryRetrievalCache()

    first = corpus.key_for(corpus.search())
    cache.put(first, corpus.search())

    assert corpus.key_for(corpus.search()).digest == first.digest
    assert cache.get(corpus.key_for(corpus.search())) is not None


def test_a_document_deleted_since_the_cached_answer_is_not_served_from_it() -> None:
    corpus = build(
        _Doc(chunk_id="c_1", text=CORPUS_TEXT),
        _Doc(chunk_id="c_2", text=SECOND_TEXT, document_id="doc_0002", version_id="ver_0002"),
    )
    cache: InMemoryRetrievalCache[RetrievalOutcome] = InMemoryRetrievalCache()
    outcome = corpus.search()
    before = corpus.key_for(outcome)
    cache.put(before, outcome)

    corpus.delete("doc_0001")

    after = corpus.key_for(corpus.search())
    assert after.digest != before.digest
    assert cache.get(after) is None


def test_the_restored_corpus_returns_to_the_generation_it_had_before_the_deletion() -> None:
    """恢复之后语料与删除前逐字节相同，世代因此回到原来那一个：缓存里那条旧结果现在又是
    对的，不该被永久作废。"""
    corpus = build(_Doc(chunk_id="c_1", text=CORPUS_TEXT))
    before = corpus.generation()

    corpus.delete()
    deleted = corpus.generation()
    corpus.restore()

    assert deleted != before
    assert corpus.generation() == before


def test_publishing_a_new_version_moves_the_generation() -> None:
    corpus = build(_Doc(chunk_id="c_1", text=CORPUS_TEXT))
    before = corpus.generation()

    corpus.add(
        _Doc(
            chunk_id="c_2",
            text=SECOND_TEXT,
            version_id="ver_0002",
            version_number=2,
            status=DocumentVersionStatus.PROCESSING,
        )
    )
    corpus.publish(generation="gen_2026_09_19")
    staged = corpus.generation()
    corpus.repository.activate_version("ver_0002", expected_status=DocumentVersionStatus.PROCESSING)

    assert staged != before
    assert corpus.generation() != staged


def test_a_re_weighted_document_moves_the_generation() -> None:
    """权威库里权重不同，就是另一份语料。当前端口没有改权重的入口（Task 18 的文档管理
    才会有），因此这里比的是两份只差权重的语料——指纹读的是权威库里的那一列，改权重的
    那天它不可能被忘记。"""
    light = build(_Doc(chunk_id="c_1", text=CORPUS_TEXT))

    heavier = _Corpus(source_weight=Decimal("0.9"))
    heavier.add(_Doc(chunk_id="c_1", text=CORPUS_TEXT))
    heavier.publish()

    assert heavier.generation() != light.generation()


def test_the_generation_does_not_depend_on_the_wall_clock_or_on_a_search() -> None:
    """世代衡量的是语料，不是时间：否则每一次检索都会拿到一个新键，缓存等于不存在。"""
    corpus = build(_Doc(chunk_id="c_1", text=CORPUS_TEXT))

    first = corpus.generation()
    corpus.search()
    corpus.search()

    assert corpus.generation() == first


def test_a_full_page_of_documents_is_refused_rather_than_hashed_partially() -> None:
    """`list_documents` 只有一页，没有偏移量。按半份语料算出的世代会让没读到的那一半永远
    命中不到，而它看上去和一个正确的世代没有区别——满页就当作可能还有下一页，拒绝，不猜。"""
    corpus = build(
        _Doc(chunk_id="c_1", text=CORPUS_TEXT, document_id="doc_0001"),
        _Doc(chunk_id="c_2", text=SECOND_TEXT, document_id="doc_0002", version_id="ver_0002"),
        scan_limit=1,
    )

    with pytest.raises(IncompleteCorpusScan):
        corpus.generation()


def test_the_scan_limit_defaults_to_the_repository_page_size() -> None:
    """扫描上限必须与端口那一页对得上；对不上时，世代会安静地少读一批文档。"""
    corpus = _Corpus()

    assert corpus.generation.scan_limit == 100
    assert CorpusGeneration(corpus.repository).scan_limit == 100


def test_the_generation_scans_deleted_documents_too() -> None:
    """软删除的文档仍在权威库里，只是不可检索。世代必须看得见它——看不见，删除就不会推进
    世代，缓存会把已经被删掉的正文继续喂给 Agent。"""
    corpus = build(_Doc(chunk_id="c_1", text=CORPUS_TEXT))
    alive = corpus.generation()

    corpus.delete()

    assert corpus.repository.list_documents(include_deleted=False) == ()
    assert len(corpus.repository.list_documents(include_deleted=True)) == 1
    assert corpus.generation() != alive


def test_the_key_survives_being_rebuilt_from_the_stored_audit() -> None:
    """键是从审计记录拼的，不是从服务内存里那份状态拼的：真库上只有审计那一份留得下来，
    因此"提交检索"和"读回审计"必须落在同一个键上。"""
    corpus = build(_Doc(chunk_id="c_1", text=CORPUS_TEXT))
    outcome = corpus.search()

    stored = corpus.repository.get_retrieval_audit(outcome.retrieval_id)
    assert stored is not None

    assert corpus.key_from(stored).digest == corpus.key_for(outcome).digest


def test_the_audit_keeps_the_generation_the_corpus_had_at_search_time() -> None:
    """检索时写下的世代必须与"当时的语料"对得上，否则审计无法解释自己给出的答案。"""
    corpus = build(_Doc(chunk_id="c_1", text=CORPUS_TEXT))
    at_search_time = corpus.generation()
    audit = corpus.audit(corpus.search())

    corpus.delete()

    assert audit.corpus_generation == at_search_time
    assert corpus.generation() != at_search_time


def test_the_fused_and_reranked_lists_survive_the_body_being_dropped() -> None:
    """审计要能回答"为什么是这几条"：名次留下来，正文不留。"""
    corpus = build(_Doc(chunk_id="c_1", text=CORPUS_TEXT))

    audit = corpus.audit(corpus.search())

    assert audit.fused_candidates[0]["chunk_id"] == "c_1"
    assert audit.fused_candidates[0]["fused_score"] is not None
    assert audit.reranked_candidates[0]["rerank_score"] is not None


def test_two_identically_answered_searches_are_still_two_audited_retrievals() -> None:
    """候选句柄是一次检索的授权凭据，两次检索不能共用一个 ID。"""
    corpus = build(_Doc(chunk_id="c_1", text=CORPUS_TEXT))

    first = corpus.search()
    second = corpus.search()

    assert first.retrieval_id != second.retrieval_id
    assert corpus.audit(first).retrieval_id != corpus.audit(second).retrieval_id


def test_a_retrieval_with_no_admissible_hit_still_names_its_generation() -> None:
    corpus = build(_Doc(chunk_id="c_1", text=CORPUS_TEXT, status=DocumentVersionStatus.SUPERSEDED))

    audit = corpus.audit(corpus.search())

    assert audit.returned_evidence == ()
    assert audit.corpus_generation == corpus.generation()


def test_the_cache_does_not_answer_for_a_different_question() -> None:
    corpus = build(_Doc(chunk_id="c_1", text=CORPUS_TEXT))
    cache: InMemoryRetrievalCache[RetrievalOutcome] = InMemoryRetrievalCache()
    cache.put(corpus.key_for(corpus.search()), corpus.search())

    other = corpus.service.search(CONTEXT, RetrievalQuery(question="光伏出口"))

    assert corpus.key_for(other).digest != corpus.key_for(corpus.search()).digest
    assert cache.get(corpus.key_for(other)) is None


# --- 指标（规格 20.2） --------------------------------------------------------


REQUIRED_SIGNALS: Mapping[str, MetricName] = {
    "ingestion duration": MetricName.INGESTION_DURATION_MS,
    "ingestion success": MetricName.INGESTION_OUTCOMES,
    "ocr page ratio": MetricName.OCR_PAGE_RATIO,
    "ocr low confidence ratio": MetricName.OCR_LOW_CONFIDENCE_RATIO,
    "chunk count": MetricName.CHUNK_COUNT,
    "provider latency": MetricName.PROVIDER_LATENCY_MS,
    "provider errors": MetricName.PROVIDER_ERRORS,
    "provider cost": MetricName.PROVIDER_COST_CNY,
    "dense contribution": MetricName.DENSE_CONTRIBUTION,
    "bm25 contribution": MetricName.LEXICAL_CONTRIBUTION,
    "empty retrieval": MetricName.EMPTY_RETRIEVALS,
    "duplicate rate": MetricName.DUPLICATE_RATE,
    "source diversity": MetricName.SOURCE_DIVERSITY,
    "conflict outcomes": MetricName.CONFLICT_OUTCOMES,
    "stale document returns": MetricName.STALE_DOCUMENT_RETURNS,
    "storage inconsistency": MetricName.STORAGE_INCONSISTENCIES,
}


def test_every_signal_spec_20_2_asks_for_has_a_name() -> None:
    assert set(REQUIRED_SIGNALS.values()) <= set(MetricName)
    assert len(set(REQUIRED_SIGNALS.values())) == len(REQUIRED_SIGNALS)


def test_a_retrieval_is_counted_from_its_own_audit() -> None:
    corpus = build(_Doc(chunk_id="c_1", text=CORPUS_TEXT))
    metrics = MetricsRegistry()
    audit = corpus.audit(corpus.search())

    metrics.record_retrieval(audit)

    assert metrics.total(MetricName.RETRIEVAL_COUNT) == 1
    assert metrics.total(MetricName.EMPTY_RETRIEVALS) == 0
    assert metrics.total(MetricName.SOURCE_DIVERSITY) == 1
    assert metrics.total(MetricName.DUPLICATE_RATE) == 0
    assert metrics.total(MetricName.PROVIDER_CALLS) == 2
    assert metrics.total(MetricName.INGESTION_DURATION_MS) == 0


def test_an_empty_retrieval_is_counted_as_empty_rather_than_as_a_missing_row() -> None:
    corpus = build(_Doc(chunk_id="c_1", text=CORPUS_TEXT, status=DocumentVersionStatus.PROCESSING))
    metrics = MetricsRegistry()

    outcome = corpus.search()
    metrics.record_retrieval(corpus.audit(outcome))

    assert outcome.candidates == ()
    assert metrics.total(MetricName.EMPTY_RETRIEVALS) == 1
    assert metrics.total(MetricName.RETRIEVAL_COUNT) == 1


def test_the_duplicate_rate_counts_what_the_service_dropped_after_reranking() -> None:
    """同一段正文进了两个切片，重排之后只交出一条——重复率就是被丢掉的那一半。"""
    corpus = build(
        _Doc(chunk_id="c_1", text=CORPUS_TEXT),
        _Doc(chunk_id="c_2", text=CORPUS_TEXT),
    )
    metrics = MetricsRegistry()

    outcome = corpus.search()

    assert len(outcome.candidates) == 1
    metrics.record_retrieval(corpus.audit(outcome))
    assert metrics.total(MetricName.DUPLICATE_RATE) == pytest.approx(0.5)


def test_source_diversity_counts_distinct_documents_not_distinct_chunks() -> None:
    """同一份资料的两段话不是两个来源——冲突裁决用的就是这条判据。"""
    corpus = build(
        _Doc(chunk_id="c_1", text=CORPUS_TEXT),
        _Doc(chunk_id="c_2", text=SECOND_TEXT),
    )
    metrics = MetricsRegistry()

    outcome = corpus.search()

    assert len(outcome.candidates) == 2
    metrics.record_retrieval(corpus.audit(outcome))
    assert metrics.total(MetricName.SOURCE_DIVERSITY) == pytest.approx(0.5)


def test_the_recall_contribution_is_not_guessed_from_a_fused_list() -> None:
    """索引端口只回传融合结果（`VectorHit` 的文档写明了这一点）。从融合分反推"哪一侧召回
    了它"是猜的，因此这里只允许调用方把它报进来，服务自己不编。"""
    corpus = build(_Doc(chunk_id="c_1", text=CORPUS_TEXT))
    metrics = MetricsRegistry()

    metrics.record_retrieval(corpus.audit(corpus.search()))

    assert metrics.samples(MetricName.DENSE_CONTRIBUTION) == ()
    assert metrics.samples(MetricName.LEXICAL_CONTRIBUTION) == ()

    metrics.record_recall_contribution(dense_only=2, lexical_only=5, both=3)

    # A slice both sides recall is counted by both: each line answers "is my half working",
    # not "how many survived the fusion".
    assert metrics.total(MetricName.DENSE_CONTRIBUTION) == 5
    assert metrics.total(MetricName.LEXICAL_CONTRIBUTION) == 8


def test_conflict_outcomes_are_counted_by_status_and_never_by_their_rationale() -> None:
    metrics = MetricsRegistry()
    decisions = (
        ConflictDecision(
            status=ConflictStatus.RESOLVED,
            claim_ids=("cl_a", "cl_b"),
            selected_claim_id="cl_a",
            rule=ConflictRule.STATUS,
            rationale=f"左侧版本在架，右侧为 DELETED：{CORPUS_TEXT}",
        ),
        ConflictDecision(
            status=ConflictStatus.UNRESOLVED,
            claim_ids=("cl_c", "cl_d"),
            rationale="两条来源互相独立，保留双方待人工判断",
        ),
        ConflictDecision(
            status=ConflictStatus.UNRESOLVED,
            claim_ids=("cl_e", "cl_f"),
            rationale="模型判定无法确定两条事实的关系",
        ),
    )

    metrics.record_conflicts(decisions)

    assert metrics.total(MetricName.CONFLICT_OUTCOMES, status="RESOLVED") == 1
    assert metrics.total(MetricName.CONFLICT_OUTCOMES, status="RESOLVED", rule="STATUS") == 1
    assert metrics.total(MetricName.CONFLICT_OUTCOMES, status="UNRESOLVED") == 2
    assert metrics.total(MetricName.CONFLICT_OUTCOMES, status="CHECK_FAILED") == 0
    assert CORPUS_TEXT not in json.dumps(
        [sample.model_dump(mode="json") for sample in metrics.snapshot()], ensure_ascii=False
    )


def test_an_ingestion_run_reports_its_stages_pages_and_chunk_lengths() -> None:
    metrics = MetricsRegistry()

    metrics.record_ingestion(
        stage="parse",
        duration_ms=1200,
        succeeded=True,
        pages=10,
        ocr_pages=4,
        low_confidence_pages=1,
        chunk_lengths=(400, 600),
    )

    assert metrics.total(MetricName.INGESTION_DURATION_MS, stage="parse") == 1200
    assert metrics.total(MetricName.INGESTION_OUTCOMES, stage="parse", status="succeeded") == 1
    # Both ratios share the page base (spec line 813 lists them in parallel), so the second is
    # "1 page in 10 came out shaky", not "1 OCR'd page in 4". The spec does not name the
    # denominator; picking the shared one keeps the two numbers additively comparable.
    assert metrics.mean(MetricName.OCR_PAGE_RATIO) == pytest.approx(0.4)
    assert metrics.mean(MetricName.OCR_LOW_CONFIDENCE_RATIO) == pytest.approx(0.1)
    assert metrics.total(MetricName.CHUNK_COUNT) == 2
    assert metrics.mean(MetricName.CHUNK_LENGTH_MEAN) == pytest.approx(500)


def test_a_run_that_parsed_nothing_reports_zero_pages_rather_than_no_ratio() -> None:
    """零页的解析不是"没有数据"：它是"这一份文档一页都没读出内容"，两者在告警上不同。"""
    metrics = MetricsRegistry()

    metrics.record_ingestion(
        stage="parse",
        duration_ms=5,
        succeeded=False,
        pages=0,
        ocr_pages=0,
        low_confidence_pages=0,
        chunk_lengths=(),
    )

    assert metrics.mean(MetricName.OCR_PAGE_RATIO) == 0
    assert metrics.total(MetricName.CHUNK_COUNT) == 0
    assert metrics.mean(MetricName.CHUNK_LENGTH_MEAN) == 0


def test_a_metric_label_carrying_a_document_body_is_refused() -> None:
    """标签是身份，不是内容。允许正文进标签，等于让"日志里没有正文"这句话失效。"""
    metrics = MetricsRegistry()

    with pytest.raises(UnsafeMetricLabel):
        metrics.increment(MetricName.STORAGE_INCONSISTENCIES, store="postgres", detail=CORPUS_TEXT)
    with pytest.raises(UnsafeMetricLabel):
        metrics.observe(MetricName.SOURCE_DIVERSITY, 1.0, question=QUESTION)

    metrics.record_storage_inconsistency(store="milvus", table="research_chunks", count=3)

    assert (
        metrics.total(MetricName.STORAGE_INCONSISTENCIES, store="milvus", table="research_chunks")
        == 3
    )


def test_the_metrics_snapshot_holds_no_document_body_and_no_question() -> None:
    corpus = build(
        _Doc(chunk_id="c_1", text=CORPUS_TEXT),
        _Doc(chunk_id="c_2", text=CORPUS_TEXT),
    )
    metrics = MetricsRegistry()

    metrics.record_retrieval(corpus.audit(corpus.search()))

    serialised = json.dumps(
        [sample.model_dump(mode="json") for sample in metrics.snapshot()], ensure_ascii=False
    )

    assert MetricName.RETRIEVAL_COUNT.value in serialised
    assert QUESTION not in serialised
    assert CORPUS_TEXT[:20] not in serialised


def test_samples_with_different_labels_are_kept_apart() -> None:
    metrics = MetricsRegistry()
    metrics.increment(MetricName.PROVIDER_ERRORS, kind="ProviderTimeout")
    metrics.increment(MetricName.PROVIDER_ERRORS, kind="ProviderUnavailable")
    metrics.increment(MetricName.PROVIDER_ERRORS, kind="ProviderTimeout")

    assert metrics.total(MetricName.PROVIDER_ERRORS, kind="ProviderTimeout") == 2
    assert metrics.total(MetricName.PROVIDER_ERRORS, kind="ProviderUnavailable") == 1
    assert len(metrics.samples(MetricName.PROVIDER_ERRORS)) == 2


def test_a_stale_return_is_counted_where_it_happened() -> None:
    metrics = MetricsRegistry()

    metrics.record_stale_document_return()
    metrics.record_stale_document_return()

    assert metrics.total(MetricName.STALE_DOCUMENT_RETURNS) == 2
    assert metrics.samples(MetricName.DUPLICATE_RATE) == ()


def test_an_unasked_metric_reads_as_zero_rather_than_as_absent() -> None:
    """读不到的指标要能与"真的是 0"分开：`samples()` 为空说明没人报过，`total()` 为 0 说明
    报上来的就是 0。混在一起，一条断掉的采集线和一次安静的正常运行看起来一模一样。"""
    metrics = MetricsRegistry()

    assert metrics.total(MetricName.PROVIDER_COST_CNY) == 0
    assert metrics.samples(MetricName.PROVIDER_COST_CNY) == ()
