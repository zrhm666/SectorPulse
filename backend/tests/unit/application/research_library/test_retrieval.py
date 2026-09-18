"""Bounded hybrid retrieval and retrieval-bound source inspection (spec 11, 15.2).

Everything here is about what the *service* adds on top of an index that already does hybrid
search. The index answers "which chunks look like this text"; it cannot answer "which of them
are still allowed to be seen", "which of them are the same paragraph twice", "which of them
may this task read", or "which of them may leave this process at all". Those four questions
are this file.

Two of them are the reason the harness stages records into a real `InMemoryVectorIndex` and
then runs the service over it, rather than scoring a list the test itself wrote. Duplicate
suppression and per-document diversity are ranking decisions taken *after* fusion and
reranking, so a stub would only be asserting against itself. The `_RecordingIndex` wrapper
keeps the `HybridQuery` that actually went out, because "the caller cannot widen the recall"
is only visible in the query that left the service.

The divergence knob on `_Document` (`index_claims_verified`) exists to pin one property that
has no other observable form: the service re-checks `requires_verification` against
PostgreSQL instead of trusting the copy inside the index. That is the same argument
`filter_active_hits` already makes for version status (spec 10), and it is only testable by
staging a corpus where the two disagree.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import pytest
from pydantic import ValidationError
from sector_pulse.application.research_library.retrieval import (
    CandidateWithdrawn,
    ResearchRetrievalService,
    RetrievalAccessDenied,
    RetrievalContext,
    RetrievalNotFound,
    RetrievalOutcome,
    SourceInspection,
    UnknownCandidate,
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
from sector_pulse.domain.research_library.retrieval import RetrievalQuery, TimeRange
from sector_pulse.infrastructure.research_library.providers.fixture import (
    FixtureEmbeddingProvider,
    FixtureRerankerProvider,
)
from sector_pulse.infrastructure.research_library.vector.memory import InMemoryVectorIndex
from sector_pulse.ports.vector_index import (
    HybridQuery,
    IndexVerification,
    VectorHit,
    VectorRecord,
)

from backend.tests.research_library_fakes import InMemoryResearchLibraryRepository

NOW = datetime(2026, 9, 18, 9, 0, tzinfo=UTC)
GENERATION = "gen_2026_09_18"
QUESTION = "储能海外需求"
QUERY_VECTOR = (1.0, 0.0, 0.0, 0.0)
ORTHOGONAL_VECTOR = (0.0, 0.0, 1.0, 0.0)
PUBLISHED = date(2026, 6, 1)

CONTEXT = RetrievalContext(run_id="run_0001", task_id="task_0001", attempt_id=1, role="A2")
OTHER_TASK = RetrievalContext(run_id="run_0001", task_id="task_0002", attempt_id=1, role="A2")
LATER_ATTEMPT = RetrievalContext(
    run_id="run_0001", task_id="task_0001", attempt_id=2, role="A2"
)

OBJECT_KEY = "originals/doc_annual/ver_annual_1/annual-report-2026Q2.pdf"


def settings(**overrides: Any) -> RagSettings:
    """一套刻意很小的召回宽度，好让每个断言都能把整份候选列出来数一遍。"""
    base: dict[str, Any] = {
        "dense_top_k": 3,
        "bm25_top_k": 3,
        "fusion_top_k": 4,
        "rerank_top_k": 2,
        "max_candidates_per_document": 2,
        "duplicate_overlap_ratio": 0.8,
        "max_candidate_text_chars": 40,
        "max_inspected_chars": 60,
        "max_parent_expansion_chunks": 2,
    }
    return RagSettings(**(base | overrides))


@dataclass(frozen=True)
class _Document:
    """一段要摆进资料库的切片，连同它所属的文档、版本、章节与原文定位。"""

    chunk_id: str
    text: str
    document_id: str = "doc_0001"
    version_id: str = "ver_0001"
    section: tuple[str, ...] = ("海外需求",)
    page: int = 3
    requires_verification: bool = False
    content_origin: ExtractionMethod = ExtractionMethod.NATIVE
    document_type: DocumentType = DocumentType.REPORT
    published: date | None = PUBLISHED
    vector: tuple[float, ...] = ORTHOGONAL_VECTOR
    parent_chunk_id: str | None = None
    status: DocumentVersionStatus = DocumentVersionStatus.ACTIVE
    indexed: bool = True
    #: 索引里那一行对 `requires_verification` 的说法；`None` 表示与切片一致。
    index_claims_verified: bool | None = None


class _RecordingIndex:
    """留下每次召开发下去的那条 `HybridQuery`，其余原样交给内存索引。"""

    def __init__(self, inner: InMemoryVectorIndex) -> None:
        self._inner = inner
        self.queries: list[HybridQuery] = []

    def stage(self, *, generation: str, records: Sequence[VectorRecord]) -> None:
        self._inner.stage(generation=generation, records=records)

    def verify(self, *, generation: str, expected_ids: set[str]) -> IndexVerification:
        return self._inner.verify(generation=generation, expected_ids=expected_ids)

    def publish(self, *, generation: str) -> None:
        self._inner.publish(generation=generation)

    def hybrid_search(self, query: HybridQuery) -> tuple[VectorHit, ...]:
        self.queries.append(query)
        return self._inner.hybrid_search(query)

    def delete_generation(self, *, generation: str) -> None:
        self._inner.delete_generation(generation=generation)


@dataclass
class _Library:
    """登记切片、发布一代索引、再把服务搭起来。"""

    config: RagSettings = field(default_factory=settings)
    reranker_scores: dict[str, float] = field(default_factory=dict)
    synonyms: dict[str, tuple[str, ...]] = field(default_factory=dict)

    registered: list[_Document] = field(default_factory=list, init=False)
    repository: InMemoryResearchLibraryRepository = field(init=False)
    index: _RecordingIndex = field(init=False)
    embedding: FixtureEmbeddingProvider = field(init=False)
    reranker: FixtureRerankerProvider = field(init=False)
    service: ResearchRetrievalService = field(init=False)

    def __post_init__(self) -> None:
        self.registered = []
        self.repository = InMemoryResearchLibraryRepository()
        self.index = _RecordingIndex(InMemoryVectorIndex())
        self.embedding = FixtureEmbeddingProvider(
            dimension=len(QUERY_VECTOR), vectors={QUESTION: QUERY_VECTOR}
        )
        self.reranker = FixtureRerankerProvider(scores=self.reranker_scores)
        self.service = ResearchRetrievalService(
            repository=self.repository,
            vector_index=self.index,
            embedding_provider=self.embedding,
            reranker=self.reranker,
            settings=self.config,
            corpus_generation=lambda: GENERATION,
            synonyms=self.synonyms,
            clock=lambda: NOW,
        )

    # --- 摆语料 ---

    def add(self, *documents: _Document) -> None:
        self.registered.extend(documents)

    def publish(self) -> None:
        """把登记过的切片变成一份可检索的语料：文档、版本、切片与索引记录一次写齐。"""
        for document_id, group in self._group_by(lambda item: item.document_id).items():
            self.repository.create_document(
                ResearchDocument(
                    document_id=document_id,
                    title=f"{document_id} 标题",
                    document_type=group[0].document_type,
                    created_at=NOW,
                )
            )
        for version_id, group in self._group_by(lambda item: item.version_id).items():
            head = group[0]
            self.repository.create_version(
                ResearchDocumentVersion(
                    document_version_id=version_id,
                    document_id=head.document_id,
                    version_number=1,
                    status=head.status,
                    published_at=NOW if head.status is DocumentVersionStatus.ACTIVE else None,
                    uploaded_at=NOW,
                    original_file_hash=f"hash_{version_id}",
                    index_generation=GENERATION,
                    expected_chunk_count=len(group),
                    indexed_at=NOW,
                )
            )
            self.repository.append_chunks(tuple(self._chunk(item) for item in group))

        records = [self._record(item) for item in self.registered if item.indexed]
        if records:
            self.index.stage(generation=GENERATION, records=records)
            self.index.publish(generation=GENERATION)

    def _group_by(self, key: Any) -> dict[str, list[_Document]]:
        grouped: dict[str, list[_Document]] = {}
        for document in self.registered:
            grouped.setdefault(key(document), []).append(document)
        return grouped

    def _chunk(self, document: _Document) -> ResearchChunk:
        return ResearchChunk(
            chunk_id=document.chunk_id,
            document_id=document.document_id,
            document_version_id=document.version_id,
            parent_chunk_id=document.parent_chunk_id,
            chunk_type=ChunkType.TEXT,
            content=document.text,
            content_hash=f"hash_{document.chunk_id}",
            source=SourceLocator(
                page_start=document.page,
                page_end=document.page,
                section_path=document.section,
            ),
            content_origin=document.content_origin,
            requires_verification=document.requires_verification,
            created_at=NOW,
        )

    def _record(self, document: _Document) -> VectorRecord:
        published = document.published
        return VectorRecord(
            chunk_id=document.chunk_id,
            document_id=document.document_id,
            document_version_id=document.version_id,
            parent_chunk_id=document.parent_chunk_id,
            chunk_type=ChunkType.TEXT,
            document_type=document.document_type,
            published_at=(
                None
                if published is None
                else datetime(published.year, published.month, published.day, tzinfo=UTC)
            ),
            content_origin=document.content_origin,
            requires_verification=(
                document.requires_verification
                if document.index_claims_verified is None
                else document.index_claims_verified
            ),
            content=document.text,
            dense_vector=document.vector,
        )

    # --- 用 ---

    def search(self, question: str = QUESTION, **query: Any) -> RetrievalOutcome:
        return self.service.search(CONTEXT, RetrievalQuery(question=question, **query))

    def audit(self, outcome: RetrievalOutcome):
        record = self.repository.get_retrieval_audit(outcome.retrieval_id)
        assert record is not None, "every search must leave an audit record behind"
        return record

    def chunk_ids(self, outcome: RetrievalOutcome) -> list[str]:
        return [candidate.chunk_id for candidate in outcome.candidates]

    def inspect(self, outcome: RetrievalOutcome, candidate_id: str) -> SourceInspection:
        return self.service.inspect(CONTEXT, outcome.retrieval_id, candidate_id)

    def only_candidate(self, outcome: RetrievalOutcome) -> str:
        assert len(outcome.candidates) == 1, "this test expects exactly one candidate"
        return outcome.candidates[0].candidate_id


# --- 查询准备与召回宽度 -------------------------------------------------------


def test_the_agent_cannot_widen_the_recall_the_service_chose() -> None:
    """规格 11.1：Top-K 不在 Tool 输入里，因此它不是一个"传了会被忽略"的字段。"""
    with pytest.raises(ValidationError):
        RetrievalQuery(question=QUESTION, top_k=1000)


def test_the_index_is_asked_for_exactly_the_configured_widths() -> None:
    library = _Library(config=settings(dense_top_k=1, bm25_top_k=2, fusion_top_k=3))
    library.add(_Document(chunk_id="c_1", text=QUESTION))
    library.publish()

    library.search()

    query = library.index.queries[-1]
    assert (query.dense_top_k, query.bm25_top_k, query.fusion_top_k) == (1, 2, 3)
    assert query.rrf_k > 0
    assert query.filters.include_unverified_leads is False


def test_the_document_types_and_the_time_window_reach_the_index_as_filters() -> None:
    library = _Library()
    library.add(
        _Document(chunk_id="c_in", text=QUESTION),
        _Document(
            chunk_id="c_out",
            text=QUESTION,
            document_id="doc_0002",
            version_id="ver_0002",
            published=date(2024, 1, 1),
        ),
    )
    library.publish()

    outcome = library.search(
        document_types=(DocumentType.REPORT,),
        time_range=TimeRange(start=date(2026, 1, 1), end=date(2026, 12, 31)),
    )

    query = library.index.queries[-1]
    assert query.filters.document_types == (DocumentType.REPORT,)
    assert query.filters.published_from == date(2026, 1, 1)
    assert query.filters.published_to == date(2026, 12, 31)
    assert library.chunk_ids(outcome) == ["c_in"]


def test_a_full_width_question_and_a_half_width_one_share_a_fingerprint() -> None:
    """规范化不是装饰：同一个问题在两种输入法下必须是同一次检索。"""
    library = _Library()
    library.add(_Document(chunk_id="c_1", text=QUESTION))
    library.publish()

    wide = library.search("　储能海外需求　")
    narrow = library.search(QUESTION)

    assert wide.query_fingerprint == narrow.query_fingerprint
    assert library.audit(wide).query_fingerprint == wide.query_fingerprint


def test_a_different_question_gets_a_different_fingerprint() -> None:
    library = _Library()
    library.add(_Document(chunk_id="c_1", text=QUESTION))
    library.publish()

    assert (
        library.search(QUESTION).query_fingerprint
        != library.search("光伏组件价格").query_fingerprint
    )


def test_the_fingerprint_does_not_depend_on_the_filters() -> None:
    """规格 17 的缓存键把两类东西分开列：指纹是问句的，过滤条件是另一项。"""
    library = _Library()
    library.add(_Document(chunk_id="c_1", text=QUESTION))
    library.publish()

    unfiltered = library.search()
    filtered = library.search(document_types=(DocumentType.REPORT,))

    assert unfiltered.query_fingerprint == filtered.query_fingerprint
    assert library.audit(unfiltered).filters != library.audit(filtered).filters


def test_the_sector_and_the_companies_are_expanded_into_the_query_text() -> None:
    """规格 9.3 的索引里没有这两个标量字段，所以它们必须走查询文本（E45）。"""
    library = _Library()
    library.add(_Document(chunk_id="c_1", text=QUESTION))
    library.publish()

    library.search(sector="储能", companies=("宁德时代",))

    text = library.index.queries[-1].query_text
    assert QUESTION in text
    assert "宁德时代" in text


def test_a_recognised_abbreviation_is_expanded_within_the_cap() -> None:
    """规格 11.2 的受限同义词表：扩展数量有上限，否则一次查询会被一个词撑满。"""
    library = _Library(synonyms={"储能": ("储能系统", "储能电池", "储能电站", "储能逆变器")})
    library.add(_Document(chunk_id="c_1", text=QUESTION))
    library.publish()

    library.search()

    text = library.index.queries[-1].query_text
    assert "储能系统" in text
    assert "储能电池" in text
    assert "储能电站" in text
    assert "储能逆变器" not in text


def test_a_term_the_query_never_mentions_is_not_expanded() -> None:
    library = _Library(synonyms={"储能": ("储能系统",)})
    library.add(_Document(chunk_id="c_1", text=QUESTION))
    library.publish()

    library.search("光伏组件价格")

    assert "储能系统" not in library.index.queries[-1].query_text


# --- 融合与重排 ---------------------------------------------------------------


def test_a_chunk_reachable_only_by_keywords_still_reaches_the_result() -> None:
    """两路召回各取一段再融合：只在 BM25 那一路上榜的切片不该被稠密那一路抹掉。"""
    library = _Library(
        config=settings(dense_top_k=1, bm25_top_k=2, fusion_top_k=3, rerank_top_k=3)
    )
    library.add(
        _Document(chunk_id="c_both", text="储能海外需求增长", vector=QUERY_VECTOR),
        _Document(
            chunk_id="c_lexical",
            text="储能海外需求改善",
            document_id="doc_0002",
            version_id="ver_0002",
            vector=ORTHOGONAL_VECTOR,
        ),
        _Document(
            chunk_id="c_absent",
            text="光伏组件价格回落",
            document_id="doc_0003",
            version_id="ver_0003",
            vector=ORTHOGONAL_VECTOR,
        ),
    )
    library.publish()

    outcome = library.search()

    assert set(library.chunk_ids(outcome)) == {"c_both", "c_lexical"}
    fused = [entry["chunk_id"] for entry in library.audit(outcome).fused_candidates]
    assert fused == ["c_both", "c_lexical"]


def test_the_reranker_decides_the_order_of_what_survives_fusion() -> None:
    library = _Library(
        config=settings(rerank_top_k=2, max_candidates_per_document=1),
        reranker_scores={
            "储能海外需求增长": 0.20,
            "储能海外需求改善": 0.90,
            "储能海外需求回落": 0.55,
        },
    )
    library.add(
        _Document(chunk_id="c_a", text="储能海外需求增长", vector=QUERY_VECTOR),
        _Document(
            chunk_id="c_b",
            text="储能海外需求改善",
            document_id="doc_0002",
            version_id="ver_0002",
            vector=QUERY_VECTOR,
        ),
        _Document(
            chunk_id="c_c",
            text="储能海外需求回落",
            document_id="doc_0003",
            version_id="ver_0003",
            vector=QUERY_VECTOR,
        ),
    )
    library.publish()

    outcome = library.search()

    assert library.chunk_ids(outcome) == ["c_b", "c_c"]
    assert [candidate.rerank_score for candidate in outcome.candidates] == [0.90, 0.55]


def test_an_empty_corpus_returns_nothing_without_calling_the_reranker() -> None:
    """一个空的文档列表不是一次重排请求；那一步既没有用，也会被 Provider 拒绝。"""
    library = _Library()
    library.publish()

    outcome = library.search()

    assert outcome.candidates == ()
    assert library.audit(outcome).returned_evidence == ()
    assert library.audit(outcome).provider_calls == 1


# --- 去重与多样性 -------------------------------------------------------------


def test_a_chunk_that_repeats_another_in_the_same_section_is_dropped() -> None:
    library = _Library(
        config=settings(rerank_top_k=3, max_candidates_per_document=5),
        reranker_scores={
            "储能海外需求增长": 0.90,
            "储能海外需求增长，价格同步上行": 0.80,
        },
    )
    library.add(
        _Document(chunk_id="c_short", text="储能海外需求增长", vector=QUERY_VECTOR),
        _Document(chunk_id="c_long", text="储能海外需求增长，价格同步上行", vector=QUERY_VECTOR),
    )
    library.publish()

    outcome = library.search()

    assert library.chunk_ids(outcome) == ["c_short"]


def test_the_same_sentence_in_two_sections_is_kept_twice() -> None:
    """重叠只在同一章节内才算重复：两章里各写一遍的同一句话是两个出处。"""
    library = _Library(
        config=settings(rerank_top_k=3, max_candidates_per_document=5),
        reranker_scores={
            "储能海外需求增长": 0.90,
            "储能海外需求增长，价格同步上行": 0.80,
        },
    )
    library.add(
        _Document(chunk_id="c_short", text="储能海外需求增长", vector=QUERY_VECTOR),
        _Document(
            chunk_id="c_long",
            text="储能海外需求增长，价格同步上行",
            section=("政策影响",),
            vector=QUERY_VECTOR,
        ),
    )
    library.publish()

    outcome = library.search()

    assert set(library.chunk_ids(outcome)) == {"c_short", "c_long"}


def test_one_document_cannot_fill_the_whole_result() -> None:
    library = _Library(
        config=settings(rerank_top_k=4, max_candidates_per_document=1),
        reranker_scores={"储能海外需求增长一": 0.90, "储能海外需求增长二": 0.80},
    )
    library.add(
        _Document(chunk_id="c_1", text="储能海外需求增长一", vector=QUERY_VECTOR),
        _Document(
            chunk_id="c_2",
            text="储能海外需求增长二",
            section=("第二章",),
            vector=QUERY_VECTOR,
        ),
    )
    library.publish()

    outcome = library.search()

    assert library.chunk_ids(outcome) == ["c_1"]


def test_the_slot_freed_by_the_document_cap_goes_to_another_document() -> None:
    """限额不是"少返回一条"：省下来的名额要给到下一名，否则多样性只是变短。"""
    library = _Library(
        config=settings(rerank_top_k=2, max_candidates_per_document=1),
        reranker_scores={
            "储能海外需求增长一": 0.90,
            "储能海外需求增长二": 0.80,
            "储能海外需求改善": 0.70,
        },
    )
    library.add(
        _Document(chunk_id="c_1", text="储能海外需求增长一", vector=QUERY_VECTOR),
        _Document(
            chunk_id="c_2",
            text="储能海外需求增长二",
            section=("第二章",),
            vector=QUERY_VECTOR,
        ),
        _Document(
            chunk_id="c_3",
            text="储能海外需求改善",
            document_id="doc_0002",
            version_id="ver_0002",
            vector=QUERY_VECTOR,
        ),
    )
    library.publish()

    outcome = library.search()

    assert library.chunk_ids(outcome) == ["c_1", "c_3"]


def test_the_candidate_text_is_bounded() -> None:
    library = _Library(config=settings(max_candidate_text_chars=8))
    library.add(_Document(chunk_id="c_1", text="储能海外需求增长与价格同步上行"))
    library.publish()

    outcome = library.search()

    assert outcome.candidates[0].text == "储能海外需求增长"


# --- 权威状态复核 -------------------------------------------------------------


def test_a_superseded_version_is_dropped_even_though_the_index_still_returns_it() -> None:
    library = _Library()
    library.add(
        _Document(chunk_id="c_old", text=QUESTION, status=DocumentVersionStatus.SUPERSEDED),
        _Document(
            chunk_id="c_new",
            text=QUESTION,
            document_id="doc_0002",
            version_id="ver_0002",
        ),
    )
    library.publish()

    outcome = library.search()

    assert library.chunk_ids(outcome) == ["c_new"]


def test_a_deleted_version_is_dropped_too() -> None:
    library = _Library()
    library.add(_Document(chunk_id="c_gone", text=QUESTION, status=DocumentVersionStatus.DELETED))
    library.publish()

    assert library.search().candidates == ()


def test_the_index_is_told_whether_unverified_leads_are_wanted() -> None:
    library = _Library()
    library.add(_Document(chunk_id="c_1", text=QUESTION))
    library.publish()

    library.search(include_unverified_leads=True)

    assert library.index.queries[-1].filters.include_unverified_leads is True


def test_a_derived_lead_comes_back_flagged_when_it_was_asked_for() -> None:
    library = _Library()
    library.add(
        _Document(
            chunk_id="c_lead",
            text="储能海外需求增长（模型派生描述）",
            content_origin=ExtractionMethod.VISION_DERIVED,
            requires_verification=True,
        )
    )
    library.publish()

    outcome = library.search(include_unverified_leads=True)

    assert outcome.candidates[0].requires_verification is True
    assert outcome.candidates[0].content_origin is ExtractionMethod.VISION_DERIVED


def test_a_derived_lead_stays_out_when_it_was_not_asked_for() -> None:
    library = _Library()
    library.add(
        _Document(
            chunk_id="c_lead",
            text="储能海外需求增长（模型派生描述）",
            content_origin=ExtractionMethod.VISION_DERIVED,
            requires_verification=True,
        )
    )
    library.publish()

    assert library.search().candidates == ()


def test_the_service_rechecks_verification_against_postgresql_not_the_index() -> None:
    """索引里那一行的 `requires_verification` 只是副本；权威答案在切片上（规格 9.4）。"""
    library = _Library()
    library.add(
        _Document(
            chunk_id="c_lead",
            text="储能海外需求增长（模型派生描述）",
            requires_verification=True,
            index_claims_verified=False,
        )
    )
    library.publish()

    assert library.search().candidates == ()


# --- 审计 ---------------------------------------------------------------------


def test_a_search_is_recorded_with_its_inputs_and_its_ranking() -> None:
    library = _Library(
        config=settings(rerank_top_k=2, max_candidates_per_document=1),
        reranker_scores={"储能海外需求增长": 0.75},
    )
    library.add(_Document(chunk_id="c_1", text="储能海外需求增长", vector=QUERY_VECTOR))
    library.publish()

    outcome = library.search(document_types=(DocumentType.REPORT,))
    audit = library.audit(outcome)

    assert (audit.run_id, audit.task_id, audit.attempt_id, audit.role) == (
        CONTEXT.run_id,
        CONTEXT.task_id,
        CONTEXT.attempt_id,
        CONTEXT.role,
    )
    assert audit.question == QUESTION
    assert audit.corpus_generation == GENERATION
    assert audit.filters["document_types"] == ["report"]
    assert audit.fused_candidates[0]["chunk_id"] == "c_1"
    assert audit.fused_candidates[0]["fused_score"] is not None
    assert audit.reranked_candidates[0]["rerank_score"] == 0.75
    assert audit.returned_evidence[0]["chunk_id"] == "c_1"
    assert audit.provider_calls == 2
    assert audit.created_at == NOW


def test_the_audit_names_the_provider_versions_that_produced_the_ranking() -> None:
    """规格 17 的缓存键里，模型版本和语料世代是并列的两项。"""
    library = _Library()
    library.add(_Document(chunk_id="c_1", text=QUESTION))
    library.publish()

    versions = library.audit(library.search()).provider_versions

    assert versions["embedding_model_version"] == library.embedding.model_version
    assert versions["reranker_model_version"] == library.reranker.model_version


# --- 原文查看 -----------------------------------------------------------------


def test_inspecting_a_candidate_returns_bounded_text_and_its_source_locator() -> None:
    library = _Library(config=settings(max_inspected_chars=10))
    library.add(
        _Document(
            chunk_id="c_1",
            text="储能海外需求增长与价格同步上行，欧洲市场订单可见度提升。",
            page=18,
            section=("海外需求", "欧洲市场"),
        )
    )
    library.publish()
    outcome = library.search()

    inspection = library.inspect(outcome, library.only_candidate(outcome))

    assert inspection.chunk_id == "c_1"
    assert inspection.text == "储能海外需求增长与价"
    assert inspection.truncated is True
    assert (inspection.page_start, inspection.page_end) == (18, 18)
    assert inspection.section_path == ("海外需求", "欧洲市场")


def test_the_inspection_text_is_returned_whole_when_it_fits() -> None:
    library = _Library()
    library.add(_Document(chunk_id="c_1", text="储能海外需求增长"))
    library.publish()
    outcome = library.search()

    inspection = library.inspect(outcome, library.only_candidate(outcome))

    assert inspection.text == "储能海外需求增长"
    assert inspection.truncated is False


def test_a_parent_chunk_is_expanded_as_context_within_the_cap() -> None:
    library = _Library(config=settings(max_parent_expansion_chunks=1))
    library.add(
        _Document(chunk_id="c_grandparent", text="年度策略总述", indexed=False),
        _Document(
            chunk_id="c_parent",
            text="海外需求章节总述",
            indexed=False,
            parent_chunk_id="c_grandparent",
        ),
        _Document(chunk_id="c_child", text=QUESTION, parent_chunk_id="c_parent"),
    )
    library.publish()
    outcome = library.search()

    inspection = library.inspect(outcome, library.only_candidate(outcome))

    assert inspection.parent_texts == ("海外需求章节总述",)


def test_the_parent_walk_stops_at_the_configured_cap() -> None:
    library = _Library(config=settings(max_parent_expansion_chunks=2))
    library.add(
        _Document(chunk_id="c_grandparent", text="年度策略总述", indexed=False),
        _Document(
            chunk_id="c_parent",
            text="海外需求章节总述",
            indexed=False,
            parent_chunk_id="c_grandparent",
        ),
        _Document(chunk_id="c_child", text=QUESTION, parent_chunk_id="c_parent"),
    )
    library.publish()
    outcome = library.search()

    inspection = library.inspect(outcome, library.only_candidate(outcome))

    assert inspection.parent_texts == ("海外需求章节总述", "年度策略总述")


def test_inspection_never_reveals_the_object_key_or_a_download_url() -> None:
    """规格 15.2：查看原文不返回 MinIO 凭证、对象键或内部下载地址。"""
    library = _Library()
    library.add(_Document(chunk_id="c_1", text=QUESTION))
    library.publish()
    library.repository.register_original_asset("ver_0001", OBJECT_KEY)
    outcome = library.search()

    inspection = library.inspect(outcome, library.only_candidate(outcome))

    rendered = (inspection.model_dump_json() + outcome.model_dump_json()).casefold()
    assert "annual-report-2026q2.pdf" not in rendered
    assert "originals/" not in rendered
    assert "minio" not in rendered
    assert "http" not in rendered


def test_a_candidate_from_another_task_is_refused() -> None:
    library = _Library()
    library.add(_Document(chunk_id="c_1", text=QUESTION))
    library.publish()
    outcome = library.search()

    with pytest.raises(RetrievalAccessDenied):
        library.service.inspect(
            OTHER_TASK, outcome.retrieval_id, library.only_candidate(outcome)
        )


def test_a_candidate_from_a_later_attempt_is_refused() -> None:
    library = _Library()
    library.add(_Document(chunk_id="c_1", text=QUESTION))
    library.publish()
    outcome = library.search()

    with pytest.raises(RetrievalAccessDenied):
        library.service.inspect(
            LATER_ATTEMPT, outcome.retrieval_id, library.only_candidate(outcome)
        )


def test_an_unknown_retrieval_id_is_refused() -> None:
    library = _Library()
    library.add(_Document(chunk_id="c_1", text=QUESTION))
    library.publish()

    with pytest.raises(RetrievalNotFound):
        library.service.inspect(CONTEXT, "ret_never_issued", "cand_never_issued")


def test_a_chunk_id_may_not_be_used_as_a_candidate_id() -> None:
    """越权读取的入口就在这里：调用方只有不透明句柄，没有 load-any-chunk 这条路。"""
    library = _Library(config=settings(rerank_top_k=1, max_candidates_per_document=1))
    library.add(
        _Document(chunk_id="c_1", text=QUESTION),
        _Document(
            chunk_id="c_unreturned",
            text="光伏组件价格回落",
            document_id="doc_0002",
            version_id="ver_0002",
            vector=ORTHOGONAL_VECTOR,
        ),
    )
    library.publish()
    outcome = library.search()

    assert library.chunk_ids(outcome) == ["c_1"]
    with pytest.raises(UnknownCandidate):
        library.service.inspect(CONTEXT, outcome.retrieval_id, "c_unreturned")


def test_a_candidate_whose_version_stopped_being_active_is_refused() -> None:
    """删除立刻生效（规格 16.3）：一次已经发出的候选不能变成绕过删除的通道。"""
    library = _Library()
    library.add(
        _Document(chunk_id="c_1", text=QUESTION),
        _Document(
            chunk_id="c_v2",
            text=QUESTION,
            version_id="ver_0002",
            indexed=False,
            status=DocumentVersionStatus.PROCESSING,
        ),
    )
    library.publish()
    outcome = library.search()
    candidate_id = library.only_candidate(outcome)

    library.repository.activate_version(
        "ver_0002", expected_status=DocumentVersionStatus.PROCESSING
    )

    with pytest.raises(CandidateWithdrawn):
        library.service.inspect(CONTEXT, outcome.retrieval_id, candidate_id)
