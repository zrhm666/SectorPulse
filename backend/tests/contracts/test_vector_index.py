"""One contract, two adapters — the vector index of Task 9.

Spec 9.4 makes the index derived and rebuildable, and spec 10 makes publication the only
thing that grants visibility. Those two rules are what the assertions below are about:

- a staged record is not retrievable, and a published one is;
- records of a generation that has not been published never appear, even when their
  neighbours in the same collection have been;
- the same record staged twice is one record, and the same `chunk_id` with different
  content is an error rather than an overwrite;
- verification names what is missing and what is extra, because "3 records short" is not
  actionable and "these 3 ids are missing" is;
- a query matched only by keyword and a query matched only by meaning are both reached,
  which is the whole reason for fusing two recall paths;
- scalar filters and the published window are applied by the index, not left to the caller.

What is deliberately *not* asserted is any score value. The memory adapter scores with
cosine and its own BM25, and Milvus scores with its own; the two will not agree
numerically, and a contract that pretended otherwise would fail on the first real server
for a reason that is not a defect.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import pytest
from sector_pulse.domain.research_library.models import (
    ChunkType,
    DocumentType,
    ExtractionMethod,
)
from sector_pulse.ports.vector_index import (
    HybridQuery,
    IndexGenerationUnknown,
    IndexRecordConflict,
    SearchFilters,
    VectorRecord,
)

#: 契约里所有向量都是 8 维、互相正交的方向：余弦相似度由方向决定，因此"哪一条更近"
#: 是算得出来的，而不是猜出来的。
DIMENSION = 8
GENERATION = "gen_0001"
OTHER_GENERATION = "gen_0002"

#: 查询向量落在 EAST 方向上，与它最接近。
EAST = (1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
NORTH = (0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
WEST = (0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0)
OPPOSITE = (-1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
QUERY_VECTOR = (1.0, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

#: 一个任何分词器都不会拆散的词：它决定词面命中，因此换到 Milvus 上也一样成立。
TOKEN = "HITHIUM-2026"
PUBLISHED_AT = datetime(2026, 5, 20, 9, 0, tzinfo=UTC)


def record(
    chunk_id: str,
    *,
    content: str = "欧洲市场库存与需求变化",
    dense_vector: tuple[float, ...] = EAST,
    document_id: str = "doc_1",
    document_version_id: str = "docv_1",
    parent_chunk_id: str | None = None,
    chunk_type: ChunkType = ChunkType.TEXT,
    document_type: DocumentType = DocumentType.REPORT,
    institution: str | None = "中金公司",
    published_at: datetime | None = PUBLISHED_AT,
    content_origin: ExtractionMethod = ExtractionMethod.NATIVE,
    requires_verification: bool = False,
) -> VectorRecord:
    return VectorRecord(
        chunk_id=chunk_id,
        document_id=document_id,
        document_version_id=document_version_id,
        parent_chunk_id=parent_chunk_id,
        chunk_type=chunk_type,
        document_type=document_type,
        institution=institution,
        published_at=published_at,
        source_weight=0.7,
        content_origin=content_origin,
        requires_verification=requires_verification,
        content=content,
        dense_vector=dense_vector,
    )


def query(
    text: str = "欧洲市场库存",
    *,
    vector: tuple[float, ...] = QUERY_VECTOR,
    filters: SearchFilters | None = None,
    dense_top_k: int = 40,
    bm25_top_k: int = 40,
    fusion_top_k: int = 50,
) -> HybridQuery:
    return HybridQuery(
        query_text=text,
        dense_vector=vector,
        dense_top_k=dense_top_k,
        bm25_top_k=bm25_top_k,
        fusion_top_k=fusion_top_k,
        filters=filters if filters is not None else SearchFilters(),
    )


def chunk_ids(hits) -> list[str]:
    return [hit.chunk_id for hit in hits]


# --- 可见性 ---


def assert_staged_records_are_not_retrievable(index) -> None:
    index.stage(
        generation=GENERATION,
        records=[record("chunk_a", content=f"{TOKEN} 中标公告")],
    )
    assert index.hybrid_search(query=query(TOKEN)) == ()


def assert_published_records_are_retrievable(index) -> None:
    index.stage(
        generation=GENERATION,
        records=[record("chunk_a", content=f"{TOKEN} 中标公告")],
    )
    index.publish(generation=GENERATION)

    assert chunk_ids(index.hybrid_search(query=query(TOKEN))) == ["chunk_a"]


def assert_an_unpublished_generation_stays_invisible_beside_a_published_one(index) -> None:
    index.stage(generation=GENERATION, records=[record("chunk_a", content=f"{TOKEN} 第一版")])
    index.publish(generation=GENERATION)
    index.stage(generation=OTHER_GENERATION, records=[record("chunk_b", content=f"{TOKEN} 第二版")])

    assert chunk_ids(index.hybrid_search(query=query(TOKEN))) == ["chunk_a"]

    index.publish(generation=OTHER_GENERATION)
    assert sorted(chunk_ids(index.hybrid_search(query=query(TOKEN)))) == ["chunk_a", "chunk_b"]


def assert_deleting_a_generation_leaves_the_others(index) -> None:
    index.stage(generation=GENERATION, records=[record("chunk_a", content=f"{TOKEN} 第一版")])
    index.publish(generation=GENERATION)
    index.stage(generation=OTHER_GENERATION, records=[record("chunk_b", content=f"{TOKEN} 第二版")])
    index.publish(generation=OTHER_GENERATION)

    index.delete_generation(generation=GENERATION)
    assert chunk_ids(index.hybrid_search(query=query(TOKEN))) == ["chunk_b"]

    # 删除是幂等的：重试一次不该把别的东西带走，也不该报错。
    index.delete_generation(generation=GENERATION)
    assert chunk_ids(index.hybrid_search(query=query(TOKEN))) == ["chunk_b"]


def assert_publishing_a_generation_that_was_never_staged_fails(index) -> None:
    with pytest.raises(IndexGenerationUnknown):
        index.publish(generation="gen_never_staged")


def assert_the_next_stage_does_not_publish_the_previous_records(index) -> None:
    """发布的是这个 generation，不是"目前 stage 过的一切"。"""
    index.stage(generation=GENERATION, records=[record("chunk_a", content=f"{TOKEN} 第一版")])
    index.stage(generation=OTHER_GENERATION, records=[record("chunk_b", content=f"{TOKEN} 第二版")])
    index.publish(generation=OTHER_GENERATION)

    assert chunk_ids(index.hybrid_search(query=query(TOKEN))) == ["chunk_b"]


# --- 写入的幂等与冲突 ---


def assert_staging_the_same_record_twice_keeps_one(index) -> None:
    records = [record("chunk_a", content=f"{TOKEN} 中标公告")]
    index.stage(generation=GENERATION, records=records)
    index.stage(generation=GENERATION, records=records)
    index.publish(generation=GENERATION)

    assert chunk_ids(index.hybrid_search(query=query(TOKEN))) == ["chunk_a"]


def assert_changing_a_staged_record_is_refused(index) -> None:
    index.stage(generation=GENERATION, records=[record("chunk_a", content="原来的内容")])
    with pytest.raises(IndexRecordConflict):
        index.stage(generation=GENERATION, records=[record("chunk_a", content="换过的内容")])


def assert_a_batch_conflicting_with_itself_is_refused(index) -> None:
    """同一批里出现两条同 ID 不同内容，说明上游的 ID 生成坏了，不该等到写入之后才发现。"""
    with pytest.raises(IndexRecordConflict):
        index.stage(
            generation=GENERATION,
            records=[record("chunk_a", content="第一份"), record("chunk_a", content="第二份")],
        )


# --- 校验 ---


def assert_verification_reports_a_complete_generation(index) -> None:
    records = [
        record(f"chunk_{position}", content=f"{TOKEN} 第 {position} 段") for position in range(3)
    ]
    index.stage(generation=GENERATION, records=records)
    expected = {entry.chunk_id for entry in records}

    report = index.verify(generation=GENERATION, expected_ids=expected)
    assert report.is_complete
    assert report.expected_count == 3
    assert report.present_count == 3
    assert report.dimension == DIMENSION
    assert not report.published

    index.publish(generation=GENERATION)
    after = index.verify(generation=GENERATION, expected_ids=expected)
    assert after.published
    assert after.is_complete


def assert_verification_names_what_is_missing_and_what_is_extra(index) -> None:
    index.stage(
        generation=GENERATION,
        records=[record("chunk_a", content="第一段"), record("chunk_b", content="第二段")],
    )

    short = index.verify(generation=GENERATION, expected_ids={"chunk_a", "chunk_b", "chunk_c"})
    assert short.missing_ids == ("chunk_c",)
    assert not short.is_complete

    extra = index.verify(generation=GENERATION, expected_ids={"chunk_a"})
    assert extra.unexpected_ids == ("chunk_b",)
    assert not extra.is_complete


def assert_verifying_an_unknown_generation_is_empty_rather_than_an_error(index) -> None:
    """没有记录是一份可以读的结果：它说的正是"这一批还一条都没进"。

    报错会迫使调用方用异常来做控制流，而"少了哪些"这个问题仍然没有答案。
    """
    report = index.verify(generation="gen_missing", expected_ids={"chunk_a"})
    assert report.present_count == 0
    assert report.missing_ids == ("chunk_a",)
    assert not report.is_complete


# --- 混合召回 ---


def assert_keyword_and_meaning_both_reach_the_result(index) -> None:
    """词面命中的一条排在语义最近的一条之前。

    只跑稠密时它排最后，只跑 BM25 时另外两条根本不该出现——因此这一条断言同时钉住了
    两条召回路径都在工作。
    """
    index.stage(
        generation=GENERATION,
        records=[
            record("chunk_semantic", content="需求与产能的季度变化", dense_vector=EAST),
            record("chunk_middling", content="欧洲库存变化", dense_vector=NORTH),
            record("chunk_token_absent", content="汇率的季度变化", dense_vector=WEST),
            record("chunk_token_match", content=f"{TOKEN} 中标公告", dense_vector=OPPOSITE),
        ],
    )
    index.publish(generation=GENERATION)

    hits = index.hybrid_search(query=query(f"{TOKEN} 中标公告"))
    assert chunk_ids(hits)[0] == "chunk_token_match"
    assert hits[0].fused_score is not None
    assert chunk_ids(hits).index("chunk_semantic") < chunk_ids(hits).index("chunk_middling")


def assert_hits_are_ordered_by_their_fused_score(index) -> None:
    index.stage(
        generation=GENERATION,
        records=[
            record("chunk_a", content="需求与产能的季度变化", dense_vector=EAST),
            record("chunk_b", content=f"{TOKEN} 中标公告", dense_vector=NORTH),
            record("chunk_c", content="汇率的季度变化", dense_vector=WEST),
        ],
    )
    index.publish(generation=GENERATION)

    hits = index.hybrid_search(query=query(f"{TOKEN} 中标公告"))
    scores = [hit.fused_score for hit in hits]
    assert all(score is not None for score in scores)
    assert scores == sorted(scores, reverse=True)


def assert_the_fusion_window_is_respected(index) -> None:
    index.stage(
        generation=GENERATION,
        records=[
            record(f"chunk_{position}", content=f"{TOKEN} 第 {position} 段")
            for position in range(5)
        ],
    )
    index.publish(generation=GENERATION)

    assert len(index.hybrid_search(query=query(TOKEN, fusion_top_k=2))) == 2


def assert_the_hit_carries_the_lineage_the_caller_needs(index) -> None:
    index.stage(
        generation=GENERATION,
        records=[
            record(
                "chunk_child",
                content=f"{TOKEN} 中标公告",
                parent_chunk_id="chunk_parent",
                chunk_type=ChunkType.TABLE,
                document_version_id="docv_9",
                content_origin=ExtractionMethod.OCR,
                requires_verification=True,
            )
        ],
    )
    index.publish(generation=GENERATION)

    # 这条是待核验线索，默认被过滤掉；本契约问的是它被召回后带出来的字段，所以显式放行。
    hit = index.hybrid_search(
        query=query(TOKEN, filters=SearchFilters(include_unverified_leads=True))
    )[0]
    assert hit.parent_chunk_id == "chunk_parent"
    assert hit.chunk_type is ChunkType.TABLE
    assert hit.document_id == "doc_1"
    assert hit.document_version_id == "docv_9"
    assert hit.document_type is DocumentType.REPORT
    assert hit.content_origin is ExtractionMethod.OCR
    assert hit.requires_verification


# --- 标量过滤 ---


def assert_document_types_are_filtered_by_the_index(index) -> None:
    index.stage(
        generation=GENERATION,
        records=[
            record("chunk_report", content=f"{TOKEN} 报告", document_type=DocumentType.REPORT),
            record(
                "chunk_article",
                content=f"{TOKEN} 历史文章",
                document_type=DocumentType.HISTORICAL_ARTICLE,
            ),
        ],
    )
    index.publish(generation=GENERATION)

    hits = index.hybrid_search(
        query=query(TOKEN, filters=SearchFilters(document_types=(DocumentType.REPORT,)))
    )
    assert chunk_ids(hits) == ["chunk_report"]


def assert_unverified_leads_are_excluded_unless_asked_for(index) -> None:
    """规格 7.9：低置信度的结论只能作为待核验线索，默认不进结论。"""
    index.stage(
        generation=GENERATION,
        records=[record("chunk_lead", content=f"{TOKEN} 视觉推断", requires_verification=True)],
    )
    index.publish(generation=GENERATION)

    assert index.hybrid_search(query=query(TOKEN)) == ()
    allowed = index.hybrid_search(
        query=query(TOKEN, filters=SearchFilters(include_unverified_leads=True))
    )
    assert chunk_ids(allowed) == ["chunk_lead"]


def assert_the_published_window_is_respected(index) -> None:
    index.stage(
        generation=GENERATION,
        records=[
            record(
                "chunk_2024",
                content=f"{TOKEN} 旧报告",
                published_at=datetime(2024, 6, 1, tzinfo=UTC),
            ),
            record(
                "chunk_2026",
                content=f"{TOKEN} 新报告",
                published_at=datetime(2026, 6, 1, tzinfo=UTC),
            ),
            record("chunk_undated", content=f"{TOKEN} 没有日期", published_at=None),
        ],
    )
    index.publish(generation=GENERATION)

    hits = index.hybrid_search(
        query=query(
            TOKEN,
            filters=SearchFilters(published_from=date(2026, 1, 1), published_to=date(2026, 12, 31)),
        )
    )
    # 没有发布日期的记录不满足任何一个时间窗：把它当成"永远符合"会让时间过滤变成摆设。
    assert chunk_ids(hits) == ["chunk_2026"]


def assert_filters_apply_to_the_lexical_half_too(index) -> None:
    """过滤由索引执行，不是召回之后再筛。

    两者在结果上看起来一样，直到窗口被无关候选占满：先召回再筛会让 Top-K 里全是会被
    丢掉的东西，而"为什么这个问题召回不到"就变得无从解释。
    """
    index.stage(
        generation=GENERATION,
        records=[
            record(
                "chunk_article",
                content=f"{TOKEN} 历史文章",
                document_type=DocumentType.HISTORICAL_ARTICLE,
            ),
            record("chunk_report", content=f"{TOKEN} 报告", document_type=DocumentType.REPORT),
        ],
    )
    index.publish(generation=GENERATION)

    hits = index.hybrid_search(
        query=query(
            TOKEN,
            filters=SearchFilters(document_types=(DocumentType.HISTORICAL_ARTICLE,)),
            fusion_top_k=5,
            dense_top_k=1,
            bm25_top_k=1,
        )
    )
    assert chunk_ids(hits) == ["chunk_article"]


#: 两个适配器跑的同一份清单。放在这里而不是各自的测试文件里：漏掉一条就等于某个后端
#: 少验了一个性质，而那种缺失在两边各自的文件里看不出来。
CONTRACT_BODIES: tuple[tuple[str, Callable[[Any], None]], ...] = (
    ("staged records are not retrievable", assert_staged_records_are_not_retrievable),
    ("published records are retrievable", assert_published_records_are_retrievable),
    (
        "an unpublished generation stays invisible beside a published one",
        assert_an_unpublished_generation_stays_invisible_beside_a_published_one,
    ),
    ("deleting a generation leaves the others", assert_deleting_a_generation_leaves_the_others),
    (
        "publishing a generation that was never staged fails",
        assert_publishing_a_generation_that_was_never_staged_fails,
    ),
    (
        "the next stage does not publish the previous records",
        assert_the_next_stage_does_not_publish_the_previous_records,
    ),
    ("staging the same record twice keeps one", assert_staging_the_same_record_twice_keeps_one),
    ("changing a staged record is refused", assert_changing_a_staged_record_is_refused),
    (
        "a batch conflicting with itself is refused",
        assert_a_batch_conflicting_with_itself_is_refused,
    ),
    (
        "verification reports a complete generation",
        assert_verification_reports_a_complete_generation,
    ),
    (
        "verification names what is missing and what is extra",
        assert_verification_names_what_is_missing_and_what_is_extra,
    ),
    (
        "verifying an unknown generation is empty rather than an error",
        assert_verifying_an_unknown_generation_is_empty_rather_than_an_error,
    ),
    (
        "keyword and meaning both reach the result",
        assert_keyword_and_meaning_both_reach_the_result,
    ),
    ("hits are ordered by their fused score", assert_hits_are_ordered_by_their_fused_score),
    ("the fusion window is respected", assert_the_fusion_window_is_respected),
    (
        "the hit carries the lineage the caller needs",
        assert_the_hit_carries_the_lineage_the_caller_needs,
    ),
    ("document types are filtered by the index", assert_document_types_are_filtered_by_the_index),
    (
        "unverified leads are excluded unless asked for",
        assert_unverified_leads_are_excluded_unless_asked_for,
    ),
    ("the published window is respected", assert_the_published_window_is_respected),
    ("filters apply to the lexical half too", assert_filters_apply_to_the_lexical_half_too),
)
