"""内存向量索引：离线门禁里的参照实现。

它同时是"索引是派生的"这条要求的可执行证明（规格 9.4）：全部状态就是一个字典，删掉
generation 再按同样的记录 stage 一遍就回到原处。

**这里的分数与 Milvus 不会相同，也不假装相同。** 稠密用余弦，稀疏用标准 BM25
（k1=1.2、b=0.75），分词是"空白切开、含中日韩的片段取二元组"。Milvus 用它自己的分词器
和它自己的 BM25 实现，两者的分数不会逐个对齐。契约断言因此只写在两边都必须成立的性质
上：谁能被召回、谁排在谁前面。这条边界是刻意的——一个要求两边分数相等的契约，会在第一次
连上真实服务器时报出一个并非缺陷的失败。

写入键是 `chunk_id + index_generation`（规格 19）。这不是把主键改复杂，而是让重建能成立：
16.2 要求重建期间新旧 generation 并存，而 `chunk_id` 由内容与切片口径决定、与嵌入模型
无关，因此换了嵌入模型之后同一个 `chunk_id` 会带着不同的向量进新 generation。把 `chunk_id`
当唯一键会让这次重建被当成"同一个 ID 送来了不同内容"而拒绝。
"""

import math
from collections import Counter
from collections.abc import Sequence, Set
from dataclasses import dataclass, replace

from sector_pulse.domain.research_library.models import IndexState
from sector_pulse.ports.vector_index import (
    HybridQuery,
    IndexGenerationUnknown,
    IndexRecordConflict,
    IndexVerification,
    SearchFilters,
    VectorHit,
    VectorRecord,
)

#: BM25 的标准常数：k1 控制词频饱和，b 控制长度归一化的强度。
BM25_K1 = 1.2
BM25_B = 0.75

_CJK_START = "一"
_CJK_END = "鿿"


def _tokens(text: str) -> tuple[str, ...]:
    """空白切开；含中日韩字符的片段取二元组，其余片段原样小写。

    二元组是一种粗糙的分词，但对契约要断言的东西足够：它让拉丁专有名词（如
    `HITHIUM-2026`）保持完整，也让中文片段在没有词典的情况下产生可用的词面匹配。真实
    的检索质量由 Milvus 侧的分词器负责，这里只需要一个确定性的、可解释的参照。
    """
    tokens: list[str] = []
    for fragment in text.split():
        if not any(_CJK_START <= character <= _CJK_END for character in fragment):
            tokens.append(fragment.lower())
        elif len(fragment) == 1:
            tokens.append(fragment)
        else:
            tokens.extend(
                fragment[position : position + 2] for position in range(len(fragment) - 1)
            )
    return tuple(tokens)


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    left_norm = math.sqrt(sum(component * component for component in left))
    right_norm = math.sqrt(sum(component * component for component in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)


def _bm25(query_tokens: tuple[str, ...], documents: Sequence[tuple[str, ...]]) -> dict[int, float]:
    """按文档在 `documents` 里的下标返回得分，只有得分大于 0 的文档在内。

    零分文档不进结果不是优化而是语义：一段和查询一个词都不共享的文本，在词面这一侧没有
    名次可言。把它按"最后一名"塞进结果，等于假装它被 BM25 找到过。
    """
    total = len(documents)
    if total == 0:
        return {}
    lengths = [len(document) for document in documents]
    average_length = sum(lengths) / total or 1.0
    document_frequency: Counter[str] = Counter()
    for document in documents:
        document_frequency.update(set(document))

    scores: dict[int, float] = {}
    for position, document in enumerate(documents):
        counts = Counter(document)
        score = 0.0
        for term in query_tokens:
            frequency = counts.get(term, 0)
            if frequency == 0:
                continue
            matches = document_frequency[term]
            inverse_frequency = math.log(1 + (total - matches + 0.5) / (matches + 0.5))
            length_ratio = lengths[position] / average_length
            denominator = frequency + BM25_K1 * (1 - BM25_B + BM25_B * length_ratio)
            score += inverse_frequency * frequency * (BM25_K1 + 1) / denominator
        if score > 0.0:
            scores[position] = score
    return scores


def _matches(record: VectorRecord, filters: SearchFilters) -> bool:
    if filters.document_types and record.document_type not in filters.document_types:
        return False
    if record.requires_verification and not filters.include_unverified_leads:
        return False
    if filters.published_from is None and filters.published_to is None:
        return True
    if record.published_at is None:
        # 没有发布日期的记录不满足任何一个时间窗。把"不知道"当成"永远符合"会让时间过滤
        # 静静地失效：窗口越窄，结果里剩下的越可能正是最不该出现的那批。
        return False
    published = record.published_at.date()
    if filters.published_from is not None and published < filters.published_from:
        return False
    return not (filters.published_to is not None and published > filters.published_to)


@dataclass(frozen=True, slots=True)
class _Entry:
    generation: str
    state: IndexState
    record: VectorRecord


def _hit(record: VectorRecord, fused_score: float) -> VectorHit:
    return VectorHit(
        chunk_id=record.chunk_id,
        document_id=record.document_id,
        document_version_id=record.document_version_id,
        parent_chunk_id=record.parent_chunk_id,
        chunk_type=record.chunk_type,
        document_type=record.document_type,
        content=record.content,
        content_origin=record.content_origin,
        requires_verification=record.requires_verification,
        fused_score=fused_score,
    )


class InMemoryVectorIndex:
    """一个进程内的向量索引。"""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], _Entry] = {}

    # --- 写入 ---

    def stage(self, *, generation: str, records: Sequence[VectorRecord]) -> None:
        batch: dict[str, VectorRecord] = {}
        for record in records:
            duplicate = batch.get(record.chunk_id)
            if duplicate is not None and duplicate != record:
                raise IndexRecordConflict(
                    f"chunk {record.chunk_id!r} appears twice in one batch with different "
                    f"content; the id is derived from the content, so this means the id "
                    f"generation upstream is broken"
                )
            batch[record.chunk_id] = record

        # 先把整批验完再写：一半成功的批次会把"哪些进了"变成一个需要额外记录才能回答的
        # 问题，而调用方拿到的只有一个异常。
        for chunk_id, record in batch.items():
            existing = self._entries.get((chunk_id, generation))
            if existing is not None and existing.record != record:
                raise IndexRecordConflict(
                    f"chunk {chunk_id!r} is already staged in generation {generation!r} with "
                    f"different content"
                )

        for chunk_id, record in batch.items():
            existing = self._entries.get((chunk_id, generation))
            # 已发布的记录再 stage 一次是重试，不是回退：把它打回 STAGED 会让一次重放的
            # 写入把已经可见的数据从检索里拿走。
            state = existing.state if existing is not None else IndexState.STAGED
            self._entries[(chunk_id, generation)] = _Entry(
                generation=generation, state=state, record=record
            )

    def publish(self, *, generation: str) -> None:
        held = [key for key, entry in self._entries.items() if entry.generation == generation]
        if not held:
            raise IndexGenerationUnknown(
                f"generation {generation!r} has no staged records to publish; if the staging "
                f"happened in another process, stage them again here"
            )
        for key in held:
            self._entries[key] = replace(self._entries[key], state=IndexState.PUBLISHED)

    def delete_generation(self, *, generation: str) -> None:
        for key in [key for key, entry in self._entries.items() if entry.generation == generation]:
            del self._entries[key]

    def delete_records(self, *, generation: str, chunk_ids: Sequence[str]) -> int:
        """删掉一代里指定的那几条（规格 16.4 的孤立向量）。"""
        wanted = set(chunk_ids)
        doomed = [
            key
            for key, entry in self._entries.items()
            if key[1] == generation and key[0] in wanted
        ]
        for key in doomed:
            del self._entries[key]
        return len(doomed)

    # --- 校验 ---

    def verify(self, *, generation: str, expected_ids: Set[str]) -> IndexVerification:
        present = {
            entry.record.chunk_id: entry
            for entry in self._entries.values()
            if entry.generation == generation
        }
        dimensions = {len(entry.record.dense_vector) for entry in present.values()}
        return IndexVerification(
            generation=generation,
            expected_count=len(expected_ids),
            present_count=len(present),
            missing_ids=tuple(sorted(set(expected_ids) - set(present))),
            unexpected_ids=tuple(sorted(set(present) - set(expected_ids))),
            # 一个 generation 里混着两种维度时没有"那个维度"可言。报出一个具体数字就是在
            # 编一个恰好来自某一条记录的答案。
            dimension=dimensions.pop() if len(dimensions) == 1 else None,
            published=bool(present)
            and all(entry.state is IndexState.PUBLISHED for entry in present.values()),
        )

    # --- 检索 ---

    def hybrid_search(self, query: HybridQuery) -> tuple[VectorHit, ...]:
        candidates = [
            entry.record
            for entry in self._entries.values()
            if entry.state is IndexState.PUBLISHED and _matches(entry.record, query.filters)
        ]
        if not candidates:
            return ()

        dense_order = self._dense_order(candidates, query.dense_vector)[: query.dense_top_k]
        lexical_order = self._lexical_order(candidates, query.query_text)[: query.bm25_top_k]

        fused: dict[int, float] = {}
        for ranking in (dense_order, lexical_order):
            for rank, position in enumerate(ranking, start=1):
                fused[position] = fused.get(position, 0.0) + 1.0 / (query.rrf_k + rank)

        hits: list[VectorHit] = []
        seen: set[str] = set()
        for position, score in sorted(fused.items(), key=lambda item: (-item[1], item[0])):
            record = candidates[position]
            # 重建期间同一个 chunk 会同时存在于新旧两个 generation。两行内容相同，都返回
            # 只会占掉一个 Top-K 名额，并让同一段文本在证据里出现两次。
            if record.chunk_id in seen:
                continue
            seen.add(record.chunk_id)
            hits.append(_hit(record, score))
            if len(hits) == query.fusion_top_k:
                break
        return tuple(hits)

    def _dense_order(
        self, candidates: Sequence[VectorRecord], vector: tuple[float, ...]
    ) -> list[int]:
        scored: list[tuple[float, int]] = []
        for position, record in enumerate(candidates):
            # 维度不同说明这条记录来自另一个嵌入模型，两个向量不可比。按前缀算出一个
            # 看起来合理的余弦，比直接跳过危险得多。
            if len(record.dense_vector) != len(vector):
                continue
            scored.append((_cosine(vector, record.dense_vector), position))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [position for _, position in scored]

    def _lexical_order(self, candidates: Sequence[VectorRecord], text: str) -> list[int]:
        scores = _bm25(_tokens(text), [_tokens(record.content) for record in candidates])
        return [
            position for position, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        ]
