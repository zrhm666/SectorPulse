"""有界混合检索，以及只能看到自己那次检索的原文查看（规格 11、15.2）。

索引已经会做混合召回与融合，所以这一层要回答的是索引结构上答不了的四个问题：

1. **哪些候选还允许被看见。** Milvus 里的 `index_state` 只是让候选少一点；一个被取代、
   被删除的版本在索引里和一条正常记录长得一模一样（规格 9.4）。因此每一次检索的最后
   都用 PostgreSQL 复核一遍版本状态，再复核一遍切片本身——`requires_verification` 与
   正文都取自权威库，不取自索引里的那一份副本。
2. **哪几条其实是同一段话。** 融合与重排都是打分，打分不会知道两条候选来自同一小节里
   被切了两次的同一句话。去重放在重排之后，因为"留哪一条"必须是排名较高的那条。
3. **一份文档能占多少名额。** 一份文档只要开头足够像问题，就能用相近的段落占满整个
   Top-N。限额省下的名额给下一名，不是让结果变短。
4. **谁可以看哪一段原文。** 调用方拿到的是不透明句柄，不是一个可以拿去读全库的
   chunk ID；`inspect` 只认这次检索已经交出去过的候选，并且把对象键挡在返回结构之外。

`corpus_generation` 由调用方提供，本模块不发明它：语料世代在发布、删除、恢复时推进
（规格 17），那是 Task 14 的职责。这里要求一个可调用对象而不是一个字符串，是因为它必须
在**每一次检索的那一刻**取值——构造服务时取一次会把"服务活着"和"语料没变"混为一谈。

审计记录在这里写下检索的输入与排名。`dense_candidates` 与 `bm25_candidates` 保持为空
不是遗漏：`VectorIndex.hybrid_search` 除了融合分之外不回传任何一侧的分数，写一个恒为空
的列表至少是诚实的，编一份分路排名则不是（规格 9.3 的端口注释）。
"""

from __future__ import annotations

import hashlib
import time
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import Field
from sector_pulse.application.research_library.audit import candidate_reference
from sector_pulse.application.research_library.indexing import filter_active_hits
from sector_pulse.config.rag_settings import RagSettings
from sector_pulse.domain.research_library.models import (
    DocumentVersionStatus,
    ExtractionMethod,
    Record,
    ResearchChunk,
)
from sector_pulse.domain.research_library.retrieval import (
    RetrievalAuditRecord,
    RetrievalQuery,
    RetrievedCandidate,
)
from sector_pulse.ports.research_models import EmbeddingProvider, RerankerProvider, RerankResult
from sector_pulse.ports.vector_index import HybridQuery, SearchFilters, VectorHit, VectorIndex
from sector_pulse.storage.ports.research_library import ResearchLibraryRepositoryPort

__all__ = [
    "MAX_SYNONYM_EXPANSIONS",
    "CandidateWithdrawn",
    "ResearchRetrievalService",
    "RetrievalAccessDenied",
    "RetrievalContext",
    "RetrievalNotFound",
    "RetrievalOutcome",
    "RetrievalProviderMismatch",
    "SourceInspection",
    "UnknownCandidate",
]

#: 规格 11.2 "限制扩展数量"：一个词最多带进几个同义说法。没有这个上限，一次查询会被
#: 同义词表里最长的那一串撑满，而问题本身在查询文本里的比重越来越小。
MAX_SYNONYM_EXPANSIONS = 3


class RetrievalNotFound(RuntimeError):
    """这个 `retrieval_id` 没有对应的检索。"""


class RetrievalAccessDenied(RuntimeError):
    """这次检索属于另一个任务或另一次尝试。"""


class UnknownCandidate(RuntimeError):
    """这个候选句柄不是这次检索交出去过的候选之一。"""


class CandidateWithdrawn(RuntimeError):
    """候选还在句柄里，但它所属的版本已经不再 ACTIVE。

    与"查不到"分开：删除要立刻生效（规格 16.3），一次已经发出的候选不能变成绕过删除的
    通道；而那是一次可以如实报告的拒绝，不是一次未知错误。
    """


class RetrievalProviderMismatch(RuntimeError):
    """Reranker 返回的分数与送进去的文档数不一致。"""


class RetrievalContext(Record):
    """谁在问：这次检索属于哪个 run、哪个任务、哪一次尝试。

    任务与尝试都在里面，是因为重试会重新检索：上一次尝试的候选不该被这一次拿来当证据，
    它们的提取前提（问题、预算、语料）可能已经不同。
    """

    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    attempt_id: int = Field(ge=0)
    role: str = Field(min_length=1)


class RetrievalOutcome(Record):
    """一次检索交出去的东西。"""

    retrieval_id: str = Field(min_length=1)
    query_fingerprint: str = Field(min_length=1)
    candidates: tuple[RetrievedCandidate, ...] = ()


class SourceInspection(Record):
    """规格 15.2 的 `inspect_research_source` 返回值。

    只有回到原文件的逻辑定位：页码、章节、切片 ID。对象键、下载地址与存储凭证不在
    这张表里，也不在任何一条回到这里的路径上。
    """

    retrieval_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_version_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    truncated: bool
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    section_path: tuple[str, ...] = ()
    parent_texts: tuple[str, ...] = ()
    content_origin: ExtractionMethod
    requires_verification: bool = False


def _normalise(text: str) -> str:
    """NFKC 加空白折叠。

    全角与半角在中文输入里是同一句话的两种打法，而它们对 BM25 是两串不同的字节：不折叠
    的话，同一个问题用两种输入法问出来会命中两批不同的切片。
    """
    return " ".join(unicodedata.normalize("NFKC", text).split())


def _prepare_query_text(query: RetrievalQuery, synonyms: Mapping[str, Sequence[str]]) -> str:
    """规格 11.2 的查询准备。

    原问题始终保留：改写只能扩大召回，不能改变问题方向，而"原话还在不在"是唯一能事后
    核对这件事的东西。板块与公司名展开进查询文本而不是过滤条件，是因为索引的 schema
    里没有这两个标量字段（规格 9.3，见 E45）。
    """
    text = _normalise(query.question)
    parts = [_normalise(query.sector)] if query.sector else []
    parts.extend(_normalise(company) for company in query.companies)
    for part in parts:
        if part and part not in text:
            text = f"{text} {part}"
    return _expand(text, synonyms)


def _expand(text: str, synonyms: Mapping[str, Sequence[str]]) -> str:
    expansions: list[str] = []
    for term, replacements in synonyms.items():
        if _normalise(term) not in text:
            continue
        for replacement in tuple(replacements)[:MAX_SYNONYM_EXPANSIONS]:
            if replacement not in text and replacement not in expansions:
                expansions.append(replacement)
    return text if not expansions else " ".join([text, *expansions])


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _candidate_id(retrieval_id: str, chunk_id: str) -> str:
    """不透明句柄。

    由检索与切片共同决定，因此同一次检索里同一条候选始终是同一个句柄；不带语料库的
    任何信息，因此拿到一个句柄并不能反推出别的切片。唯一性由同一次检索内切片不重复保证。
    """
    digest = hashlib.sha256(f"{retrieval_id}\x00{chunk_id}".encode()).hexdigest()
    return f"cand_{digest[:32]}"


def _bigrams(text: str) -> frozenset[str]:
    compact = "".join(text.split())
    if len(compact) < 2:
        return frozenset({compact}) if compact else frozenset()
    return frozenset(compact[index : index + 2] for index in range(len(compact) - 1))


def _covers(shorter: str, longer: str, ratio: float) -> bool:
    """较短的一段有多大比例被较长的一段覆盖。

    用覆盖率而不是 Jaccard，是因为要抓的是"同一句话被切了两次"：那是包含关系。Jaccard
    会把一段包含关系判成低相似（长的那段多出来的部分拉低分母），恰好放过要抓的情形。
    """
    inner = _bigrams(shorter)
    if not inner:
        return False
    return len(inner & _bigrams(longer)) / len(inner) >= ratio


class ResearchRetrievalService:
    """规格 11 的受控检索。"""

    def __init__(
        self,
        *,
        repository: ResearchLibraryRepositoryPort,
        vector_index: VectorIndex,
        embedding_provider: EmbeddingProvider,
        reranker: RerankerProvider,
        settings: RagSettings,
        corpus_generation: Callable[[], str],
        synonyms: Mapping[str, Sequence[str]] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._vector_index = vector_index
        self._embedding = embedding_provider
        self._reranker = reranker
        self._settings = settings
        self._corpus_generation = corpus_generation
        self._synonyms = dict(synonyms or {})
        self._clock = clock or (lambda: datetime.now(UTC))

    # --- 检索 ---

    def search(self, context: RetrievalContext, query: RetrievalQuery) -> RetrievalOutcome:
        started = time.monotonic()
        text = _prepare_query_text(query, self._synonyms)
        fingerprint = _fingerprint(text)
        filters = SearchFilters(
            document_types=query.document_types,
            published_from=query.time_range.start if query.time_range else None,
            published_to=query.time_range.end if query.time_range else None,
            include_unverified_leads=query.include_unverified_leads,
        )

        batch = self._embedding.embed([text])
        provider_calls = 1
        hits = self._vector_index.hybrid_search(
            HybridQuery(
                query_text=text,
                dense_vector=batch.vectors[0],
                dense_top_k=self._settings.dense_top_k,
                bm25_top_k=self._settings.bm25_top_k,
                fusion_top_k=self._settings.fusion_top_k,
                filters=filters,
            )
        )
        hits = filter_active_hits(hits, repository=self._repository)
        chunks = self._repository.load_chunks([hit.chunk_id for hit in hits])
        admissible = [
            hit
            for hit in hits
            # 权威库里查不到的切片正在被清理，把"查不到"当成"没问题"会让最该丢弃的那一条
            # 穿过去——与 `filter_active_hits` 同一条理由。
            if hit.chunk_id in chunks
            and (query.include_unverified_leads or not chunks[hit.chunk_id].requires_verification)
        ]

        ranked: tuple[tuple[VectorHit, float], ...] = ()
        reranked: RerankResult | None = None
        if admissible:
            ranked, reranked = self._rerank(text, admissible, chunks)
            provider_calls += 1

        # 版本取自**结果**而不是 Provider 对象：排名的来源要以那一次调用自报的为准，
        # 一个被换了模型却没换实例的 Provider 不会在这里被漏掉。
        provider_versions = {
            "embedding_provider": batch.provider,
            "embedding_model_version": batch.model_version,
        }
        if reranked is not None:
            provider_versions["reranker_provider"] = reranked.provider
            provider_versions["reranker_model_version"] = reranked.model_version

        retrieval_id = f"ret_{uuid4().hex}"
        candidates = self._select(retrieval_id, ranked, chunks)
        self._repository.record_retrieval_audit(
            RetrievalAuditRecord(
                retrieval_id=retrieval_id,
                run_id=context.run_id,
                task_id=context.task_id,
                attempt_id=context.attempt_id,
                role=context.role,
                question=query.question,
                query_fingerprint=fingerprint,
                filters=filters.model_dump(mode="json"),
                corpus_generation=self._corpus_generation(),
                provider_versions=provider_versions,
                fused_candidates=tuple(
                    {"chunk_id": hit.chunk_id, "fused_score": hit.fused_score} for hit in hits
                ),
                reranked_candidates=tuple(
                    {"chunk_id": hit.chunk_id, "rerank_score": score} for hit, score in ranked
                ),
                # 这里记的是交到调用方手里的那一份，它同时是 `inspect` 的授权名单：
                # "这次检索发出过这个句柄"与"这个句柄现在还能看"必须是同一件事。
                # 记的是句柄与定位，不是正文（规格 20.1）：审计要比文档活得久，而正文只留
                # 在权威库里，由 `chunk_id` 指回去——`inspect` 要的就是这个键。
                returned_evidence=tuple(candidate_reference(candidate) for candidate in candidates),
                duration_ms=int((time.monotonic() - started) * 1000),
                provider_calls=provider_calls,
                created_at=self._clock(),
            )
        )
        return RetrievalOutcome(
            retrieval_id=retrieval_id, query_fingerprint=fingerprint, candidates=candidates
        )

    def _rerank(
        self,
        question: str,
        hits: Sequence[VectorHit],
        chunks: Mapping[str, ResearchChunk],
    ) -> tuple[tuple[tuple[VectorHit, float], ...], RerankResult]:
        """对**权威库里的正文**重排，而不是索引里那一份。

        两者通常是同一段文字；不同的时候，应该被拿来判断相关性的是切片的那一份——索引
        是派生的（规格 9.4），拿它来重排等于让一个可重建的副本决定答案。
        """
        documents = [chunks[hit.chunk_id].content for hit in hits]
        result = self._reranker.rerank(query=question, documents=documents)
        if len(result.scores) != len(documents):
            raise RetrievalProviderMismatch(
                f"the reranker returned {len(result.scores)} scores for "
                f"{len(documents)} documents; the scores no longer say which document "
                f"they are about"
            )
        ranking = tuple((hits[index], result.scores[index]) for index in result.best_order())
        return ranking, result

    def _select(
        self,
        retrieval_id: str,
        ranked: Sequence[tuple[VectorHit, float]],
        chunks: Mapping[str, ResearchChunk],
    ) -> tuple[RetrievedCandidate, ...]:
        """按重排名次收候选，边走边丢重复与超额文档。"""
        chosen: list[tuple[VectorHit, float, ResearchChunk]] = []
        per_document: dict[str, int] = {}
        for hit, score in ranked:
            chunk = chunks[hit.chunk_id]
            if per_document.get(chunk.document_id, 0) >= (
                self._settings.max_candidates_per_document
            ):
                continue
            if any(self._is_repeat(chunk, kept) for _, _, kept in chosen):
                continue
            chosen.append((hit, score, chunk))
            per_document[chunk.document_id] = per_document.get(chunk.document_id, 0) + 1
            if len(chosen) == self._settings.rerank_top_k:
                break

        limit = self._settings.max_candidate_text_chars
        return tuple(
            RetrievedCandidate(
                candidate_id=_candidate_id(retrieval_id, chunk.chunk_id),
                retrieval_id=retrieval_id,
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                document_version_id=chunk.document_version_id,
                text=chunk.content[:limit],
                page_start=chunk.source.page_start,
                page_end=chunk.source.page_end,
                section_path=chunk.source.section_path,
                content_origin=chunk.content_origin,
                requires_verification=chunk.requires_verification,
                # 分路得分为空：索引除了融合分之外什么都不回传（见端口注释）。
                fused_score=hit.fused_score,
                rerank_score=score,
            )
            for hit, score, chunk in chosen
        )

    def _is_repeat(self, chunk: ResearchChunk, kept: ResearchChunk) -> bool:
        """同一版本、同一章节内的包含关系才算重复。

        跨章节不算：同一句话在两章里各写一遍是两个出处，合并它们会凭空删掉一个来源。
        """
        if chunk.document_version_id != kept.document_version_id:
            return False
        if chunk.source.section_path != kept.source.section_path:
            return False
        ratio = self._settings.duplicate_overlap_ratio
        shorter, longer = (
            (chunk.content, kept.content)
            if len(chunk.content) <= len(kept.content)
            else (kept.content, chunk.content)
        )
        return _covers(shorter, longer, ratio)

    # --- 原文查看 ---

    def inspect(
        self, context: RetrievalContext, retrieval_id: str, candidate_id: str
    ) -> SourceInspection:
        audit = self._repository.get_retrieval_audit(retrieval_id)
        if audit is None:
            raise RetrievalNotFound(f"no retrieval is recorded under {retrieval_id!r}")
        if (audit.run_id, audit.task_id, audit.attempt_id) != (
            context.run_id,
            context.task_id,
            context.attempt_id,
        ):
            raise RetrievalAccessDenied(
                f"retrieval {retrieval_id!r} belongs to task {audit.task_id!r} "
                f"attempt {audit.attempt_id}, not to task {context.task_id!r} "
                f"attempt {context.attempt_id}"
            )
        returned = {str(entry.get("candidate_id")): entry for entry in audit.returned_evidence}
        entry = returned.get(candidate_id)
        if entry is None:
            raise UnknownCandidate(
                f"{candidate_id!r} was not returned by retrieval {retrieval_id!r}; "
                f"a chunk id from elsewhere in the corpus is not a candidate"
            )
        chunk = self._repository.get_chunk(str(entry["chunk_id"]))
        if chunk is None:
            raise CandidateWithdrawn(f"chunk {entry['chunk_id']!r} is no longer stored")
        statuses = self._repository.load_version_statuses([chunk.document_version_id])
        if statuses.get(chunk.document_version_id) is not DocumentVersionStatus.ACTIVE:
            raise CandidateWithdrawn(f"version {chunk.document_version_id!r} is no longer ACTIVE")

        limit = self._settings.max_inspected_chars
        return SourceInspection(
            retrieval_id=retrieval_id,
            candidate_id=candidate_id,
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            document_version_id=chunk.document_version_id,
            text=chunk.content[:limit],
            truncated=len(chunk.content) > limit,
            page_start=chunk.source.page_start,
            page_end=chunk.source.page_end,
            section_path=chunk.source.section_path,
            parent_texts=self._parent_texts(chunk, limit),
            content_origin=chunk.content_origin,
            requires_verification=chunk.requires_verification,
        )

    def _parent_texts(self, chunk: ResearchChunk, limit: int) -> tuple[str, ...]:
        """沿父链上溯，取回读整段所需的上下文。

        父块只从同一版本里取：切片器在同一次调用里产出父与子（规格 8），因此跨版本的
        父引用只可能来自一份被改写过的行，那种行不该被当作上下文交给调用方。
        """
        texts: list[str] = []
        current = chunk
        while (
            current.parent_chunk_id is not None
            and len(texts) < self._settings.max_parent_expansion_chunks
        ):
            parent = self._repository.get_chunk(current.parent_chunk_id)
            if parent is None or parent.document_version_id != chunk.document_version_id:
                break
            texts.append(parent.content[:limit])
            current = parent
        return tuple(texts)
