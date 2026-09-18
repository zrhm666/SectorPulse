"""Deterministic structural chunking (spec 8): children to retrieve, parents to read.

Half of this file is about determinism. The same document, parsed the same way, must produce
the same chunks with the same ids on every run, because indexing retries are keyed by
`chunk_id`: an id derived from a counter, a timestamp or `uuid4()` turns every retry into a
new row and every re-index into a duplicate. The tests below therefore run the chunker twice
and compare, then vary exactly one input at a time to show which inputs the id depends on.

The other half is about the asymmetries the spec cares about. An oversized chunk is a recall
problem; a chunk cut through the middle of a sentence is a correctness problem. A table split
across chunks without its header leaves numbers with no subject, and a heading left behind in
the previous chunk leaves a paragraph that reads as if it were about something else. None of
these failures announce themselves — the chunk is still text and it still embeds — which is
why each one is pinned by its own test.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sector_pulse.application.research_library.chunking import (
    ApproximateTokenCounter,
    ChunkingPolicy,
    StructuralChunker,
    split_sentences,
)
from sector_pulse.application.research_library.non_text_blocks import (
    NOTES_PREFIX,
    TABLE_TITLE_PREFIX,
    UNIT_PREFIX,
    normalize_table,
)
from sector_pulse.domain.research_library.models import (
    BlockType,
    ChunkType,
    DocumentBlock,
    ExtractionMethod,
    ResearchChunk,
)
from sector_pulse.ports.research_models import (
    NonTextBlock,
    ParsedDocument,
    TableData,
)

DOCUMENT_ID = "doc_0001"
VERSION_ID = "ver_0001"
NOW = datetime(2026, 9, 18, 9, 0, tzinfo=UTC)

SECTION = ("海外需求", "欧洲市场")
SECTION_LINE = "海外需求 > 欧洲市场"
SECTION_PREFIX = f"{SECTION_LINE}\n\n"


@dataclass(frozen=True)
class CharacterCounter:
    """一个字符一个 token：测试于是可以把预算写成字数，而不是去猜分词器。"""

    version: str = "character-counter-v1"

    def count(self, text: str) -> int:
        return len(text)


COUNTER = CharacterCounter()

#: 预算刻意取小，只为把边界暴露出来；规格给的默认值另有测试钉住。
POLICY = ChunkingPolicy(
    child_target_tokens=24,
    child_min_tokens=12,
    child_soft_cap_tokens=32,
    child_overlap_tokens=6,
    parent_target_tokens=60,
    parent_max_tokens=90,
)

#: 每句恰好 7 个字符，于是"几句"就是"几个 7"。
SENTENCE_LENGTH = 7


def sentence(index: int) -> str:
    return f"第{index:02d}句内容。"


def sentences(count: int, *, start: int = 1) -> str:
    return "".join(sentence(index) for index in range(start, start + count))


def block(
    block_id: str,
    text: str,
    *,
    order: int,
    kind: BlockType = BlockType.PARAGRAPH,
    section: tuple[str, ...] = (),
    page_number: int | None = None,
) -> DocumentBlock:
    return DocumentBlock(
        block_id=block_id,
        block_type=kind,
        text=text,
        heading_path=section,
        page_number=page_number,
        block_order=order,
        extraction_method=ExtractionMethod.NATIVE,
    )


def paragraph(
    block_id: str,
    text: str,
    *,
    order: int,
    section: tuple[str, ...] = (),
    page_number: int | None = None,
) -> DocumentBlock:
    return block(block_id, text, order=order, section=section, page_number=page_number)


def document(
    *blocks: DocumentBlock, non_text: tuple[NonTextBlock, ...] = ()
) -> ParsedDocument:
    return ParsedDocument(
        blocks=blocks,
        non_text_blocks=non_text,
        page_count=1,
        parser_name="test",
        parser_version="test-v1",
    )


@pytest.fixture
def chunker() -> StructuralChunker:
    return StructuralChunker(tokenizer=COUNTER)


def chunk_all(
    chunker: StructuralChunker,
    parsed: ParsedDocument,
    policy: ChunkingPolicy = POLICY,
    *,
    document_version_id: str = VERSION_ID,
) -> tuple[ResearchChunk, ...]:
    return chunker.chunk(
        parsed,
        policy,
        document_id=DOCUMENT_ID,
        document_version_id=document_version_id,
        created_at=NOW,
    )


def children(chunks: tuple[ResearchChunk, ...]) -> tuple[ResearchChunk, ...]:
    return tuple(chunk for chunk in chunks if chunk.parent_chunk_id is not None)


def parents(chunks: tuple[ResearchChunk, ...]) -> tuple[ResearchChunk, ...]:
    return tuple(chunk for chunk in chunks if chunk.parent_chunk_id is None)


def body(chunk: ResearchChunk) -> str:
    """去掉拼进正文的章节上下文，只留这一块真正的内容。"""
    if chunk.content.startswith(SECTION_PREFIX):
        return chunk.content[len(SECTION_PREFIX) :]
    return chunk.content


def shared_boundary(previous: str, following: str) -> int:
    """前一块的结尾有多少字符同时是后一块的开头，即重叠量。"""
    for size in range(min(len(previous), len(following)), 0, -1):
        if previous.endswith(following[:size]):
            return size
    return 0


def hash_of(text: str) -> str:
    parsed = document(paragraph("blk_00001", text, order=0))
    return children(chunk_all(StructuralChunker(tokenizer=COUNTER), parsed))[0].content_hash


# --- the policy numbers are the spec's numbers ---


def test_the_default_policy_is_the_range_the_spec_states() -> None:
    policy = ChunkingPolicy()

    assert (policy.child_min_tokens, policy.child_target_tokens) == (300, 400)
    assert policy.child_soft_cap_tokens == 700
    assert policy.child_overlap_tokens == 65
    assert (policy.parent_target_tokens, policy.parent_max_tokens) == (1200, 1500)


def test_a_cap_below_the_target_is_not_a_policy() -> None:
    with pytest.raises(ValidationError):
        ChunkingPolicy(child_target_tokens=700, child_soft_cap_tokens=400)


def test_an_overlap_that_reaches_the_floor_is_not_a_policy() -> None:
    """重叠接近下限时，一个块可以整块都是上一块的尾巴：块数在涨，内容没有涨。"""
    with pytest.raises(ValidationError):
        ChunkingPolicy(child_min_tokens=300, child_overlap_tokens=300)


# --- determinism ---


def test_chunk_ids_are_stable_for_same_version_and_policy(chunker: StructuralChunker) -> None:
    parsed = document(paragraph("blk_00001", sentences(6), order=0, section=SECTION))

    first = chunk_all(chunker, parsed)
    second = chunk_all(chunker, parsed)

    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]
    assert [chunk.content_hash for chunk in first] == [chunk.content_hash for chunk in second]


def test_the_same_content_in_a_new_version_is_a_new_chunk(chunker: StructuralChunker) -> None:
    """同一段文字在新版本里是新的 chunk：旧版本的 chunk 不能代替新版本的内容。"""
    parsed = document(paragraph("blk_00001", sentences(4), order=0, section=SECTION))

    old = chunk_all(chunker, parsed, document_version_id="ver_0001")
    new = chunk_all(chunker, parsed, document_version_id="ver_0002")

    assert {chunk.chunk_id for chunk in old}.isdisjoint({chunk.chunk_id for chunk in new})


def test_a_new_policy_version_is_a_new_chunk(chunker: StructuralChunker) -> None:
    """切片口径变了，块就变了：沿用旧 ID 会让 Milvus 里留着按旧规则切出来的实体。"""
    parsed = document(paragraph("blk_00001", sentences(4), order=0, section=SECTION))
    other = POLICY.model_copy(update={"version": f"{POLICY.version}-next"})

    first = chunk_all(chunker, parsed, POLICY)
    second = chunk_all(chunker, parsed, other)

    assert {chunk.chunk_id for chunk in first}.isdisjoint({chunk.chunk_id for chunk in second})


def test_no_two_chunks_of_one_document_share_an_id(chunker: StructuralChunker) -> None:
    """父块和它唯一的子块渲染出同一段文字时，两者仍然必须是两行。

    没有小节标题的片段里，父块和子块拿到的是同一串上下文、同一批正文，`_render` 因而
    给出完全相同的文本。只切标题的那份文档不会暴露这一点：那里父子两块的上下文不同。

    `chunk_id` 是 PostgreSQL 的主键、也是 Milvus 的主键（规格 9.3、19），撞上就意味着
    这份文档既写不进权威库也写不进索引。
    """
    parsed = document(
        paragraph("blk_00001", sentences(4), order=0, section=SECTION),
        paragraph("blk_00002", sentences(4), order=1, section=()),
    )

    chunks = chunk_all(chunker, parsed)
    ids = [chunk.chunk_id for chunk in chunks]

    assert parents(chunks) and children(chunks)
    assert len(set(ids)) == len(ids)


def test_the_content_hash_ignores_whitespace_and_moves_with_the_text() -> None:
    assert hash_of("订单同比翻倍。") == hash_of("  订单同比翻倍。  ")
    assert hash_of("订单同比翻倍。") != hash_of("订单同比回落。")


# --- parents are what gets read; children are what gets retrieved ---


def test_every_child_points_at_a_parent_that_was_also_emitted(chunker: StructuralChunker) -> None:
    parsed = document(paragraph("blk_00001", sentences(12), order=0, section=SECTION))

    chunks = chunk_all(chunker, parsed)
    emitted = {chunk.chunk_id for chunk in parents(chunks)}

    assert children(chunks)
    assert {chunk.parent_chunk_id for chunk in children(chunks)} == emitted


def test_a_parent_reads_the_whole_section_and_a_child_only_part_of_it(
    chunker: StructuralChunker,
) -> None:
    parsed = document(paragraph("blk_00001", sentences(12), order=0, section=SECTION))

    chunks = chunk_all(chunker, parsed)
    parent = parents(chunks)[0]

    assert parent.content.endswith(sentences(12))
    assert body(children(chunks)[0]) != parent.content
    assert parent.source.section_path == SECTION


def test_a_section_is_split_into_several_parents_when_it_is_too_long(
    chunker: StructuralChunker,
) -> None:
    """父块也有上限：一个两百页的章节不该变成一次读不完的上下文。"""
    # 每段 4 句 = 28 字符，加 13 字符的章节前缀共 41；两段 70，放不下第三段（上限 90）。
    parsed = document(
        *(
            paragraph(f"blk_{index:05d}", sentences(4), order=index, section=SECTION)
            for index in range(5)
        )
    )

    parents_of = parents(chunk_all(chunker, parsed))

    assert len(parents_of) == 3
    assert all(COUNTER.count(parent.content) <= POLICY.parent_max_tokens for parent in parents_of)


def test_a_section_that_is_only_a_heading_produces_nothing_to_read(
    chunker: StructuralChunker,
) -> None:
    """只有标题的章节没有可断言的内容：为它建块只会让索引里多一条空话。"""
    parsed = document(
        block("blk_00000", "海外需求", order=0, kind=BlockType.HEADING, section=("海外需求",))
    )

    assert chunk_all(chunker, parsed) == ()


def test_no_chunk_is_empty(chunker: StructuralChunker) -> None:
    parsed = document(
        block("blk_00000", "欧洲市场", order=0, kind=BlockType.HEADING, section=SECTION),
        paragraph("blk_00001", sentences(9), order=1, section=SECTION),
        # 没有图题的图片块允许没有文本，但它绝不能变成一个空 chunk。
        block("blk_00002", "", order=2, kind=BlockType.IMAGE, section=SECTION),
    )

    chunks = chunk_all(chunker, parsed)

    assert chunks
    assert all(chunk.content.strip() for chunk in chunks)


# --- sentence-aware packing ---


def test_a_child_stops_at_the_target_and_never_passes_the_cap(
    chunker: StructuralChunker,
) -> None:
    parsed = document(paragraph("blk_00001", sentences(30), order=0, section=SECTION))

    chunks = children(chunk_all(chunker, parsed))

    assert len(chunks) > 3
    assert all(COUNTER.count(chunk.content) <= POLICY.child_soft_cap_tokens for chunk in chunks)


def test_no_sentence_is_lost_between_children(chunker: StructuralChunker) -> None:
    parsed = document(paragraph("blk_00001", sentences(30), order=0, section=SECTION))

    joined = "".join(body(chunk) for chunk in children(chunk_all(chunker, parsed)))

    assert all(sentence(index) in joined for index in range(1, 31))


def test_no_chunk_is_cut_through_the_middle_of_a_sentence(chunker: StructuralChunker) -> None:
    parsed = document(paragraph("blk_00001", sentences(30), order=0, section=SECTION))

    chunks = children(chunk_all(chunker, parsed))

    assert all(body(chunk).endswith("。") for chunk in chunks)


def test_consecutive_children_overlap_by_the_configured_amount(
    chunker: StructuralChunker,
) -> None:
    parsed = document(paragraph("blk_00001", sentences(30), order=0, section=SECTION))

    chunks = children(chunk_all(chunker, parsed))
    overlaps = [
        shared_boundary(body(earlier), body(later))
        for earlier, later in zip(chunks, chunks[1:], strict=False)
    ]

    assert overlaps
    assert all(
        POLICY.child_overlap_tokens <= overlap <= POLICY.child_target_tokens
        for overlap in overlaps
    )


def test_a_trailing_fragment_below_the_floor_is_absorbed(chunker: StructuralChunker) -> None:
    """收尾只剩一句时并进上一块：单独成块只会多一次检索和一条几乎重复的向量。"""
    parsed = document(paragraph("blk_00001", sentences(3) + "收尾", order=0, section=SECTION))
    # 下限抬到收尾那块够不着的位置：这一条测的就是下限有没有生效。
    strict = POLICY.model_copy(update={"child_min_tokens": 23})

    merged = children(chunk_all(chunker, parsed, strict))
    loose = children(chunk_all(chunker, parsed, POLICY))

    assert len(merged) == 2
    assert body(merged[-1]).endswith("收尾")
    assert len(loose) == 3


def test_the_heading_path_is_copied_into_every_child(chunker: StructuralChunker) -> None:
    """切片之后块会离开章节，标题必须跟着块走，而不是靠重叠碰巧带上。"""
    parsed = document(paragraph("blk_00001", sentences(12), order=0, section=SECTION))

    chunks = children(chunk_all(chunker, parsed))

    assert chunks
    assert all(chunk.content.startswith(SECTION_PREFIX) for chunk in chunks)
    assert all(chunk.source.section_path == SECTION for chunk in chunks)


def test_a_block_without_a_heading_gets_no_invented_context(chunker: StructuralChunker) -> None:
    parsed = document(paragraph("blk_00001", sentences(4), order=0))

    chunk = children(chunk_all(chunker, parsed))[0]

    assert chunk.content == sentences(4)
    assert chunk.source.section_path == ()


# --- structure-aware: tables, code, formulas ---


SALES = TableData(
    block_id="blk_00010",
    title="公司营收情况",
    columns=("年份", "营收", "同比"),
    rows=(
        ("2025", "120 亿", "15%"),
        ("2026", "138 亿", "15%"),
        ("2027", "160 亿", "16%"),
    ),
    unit="亿元",
    notes="口径为合并报表。",
)


def table_document(table: TableData = SALES) -> ParsedDocument:
    text = normalize_table(table).indexable_text
    assert text is not None
    return document(
        block(table.block_id, text, order=0, kind=BlockType.TABLE, section=SECTION),
        non_text=(
            NonTextBlock(
                block_id=table.block_id,
                block_type=BlockType.TABLE,
                content_origin=ExtractionMethod.PARSER_DERIVED,
                indexable_text=text,
                table=table,
            ),
        ),
    )


def test_a_long_table_splits_on_row_boundaries_and_repeats_its_header(
    chunker: StructuralChunker,
) -> None:
    """行列是表格自身的结构；切在中间会让数字失去主语和量纲。"""
    chunks = children(chunk_all(chunker, table_document()))

    assert len(chunks) == 3
    assert all(chunk.chunk_type is ChunkType.TABLE for chunk in chunks)
    assert all(f"{TABLE_TITLE_PREFIX}公司营收情况" in chunk.content for chunk in chunks)
    assert all(f"{UNIT_PREFIX}亿元" in chunk.content for chunk in chunks)


def test_a_table_row_is_never_cut_in_half(chunker: StructuralChunker) -> None:
    chunks = children(chunk_all(chunker, table_document()))

    assert "2025 年：营收 120 亿，同比 15%。" in body(chunks[0])
    assert all(body(chunk).endswith("。") for chunk in chunks)


def test_the_table_notes_travel_with_the_last_piece_of_the_table(
    chunker: StructuralChunker,
) -> None:
    """注释说的是整张表的口径：重复三遍没有意义，跟丢一次就再也没有了。"""
    chunks = children(chunk_all(chunker, table_document()))

    assert [NOTES_PREFIX in chunk.content for chunk in chunks] == [False, False, True]


CODE_TEXT = "\n".join(f"line_{index:02d} = {index}" for index in range(1, 12))
#: 放得进一块的两行代码：用来测"不与散文混在一起"，长度本身不是重点。
SHORT_CODE = "total = sum(values)\nreturn total / len(values)"


def test_a_code_block_is_never_merged_into_the_surrounding_prose(
    chunker: StructuralChunker,
) -> None:
    # 这一条测的是原子性，不是预算，因此给足空间让整块代码放得下。
    roomy = POLICY.model_copy(update={"child_target_tokens": 60, "child_soft_cap_tokens": 80})
    parsed = document(
        paragraph("blk_00001", sentences(2), order=0, section=SECTION),
        block("blk_00002", SHORT_CODE, order=1, kind=BlockType.CODE, section=SECTION),
        paragraph("blk_00003", sentences(2, start=3), order=2, section=SECTION),
    )

    chunks = children(chunk_all(chunker, parsed, roomy))
    code_chunks = [chunk for chunk in chunks if chunk.chunk_type is ChunkType.CODE]

    assert len(code_chunks) == 1
    assert body(code_chunks[0]) == SHORT_CODE


def test_an_oversized_code_block_splits_on_line_boundaries(chunker: StructuralChunker) -> None:
    parsed = document(
        block("blk_00002", CODE_TEXT, order=0, kind=BlockType.CODE, section=SECTION)
    )

    chunks = children(chunk_all(chunker, parsed))
    original = CODE_TEXT.splitlines()

    assert len(chunks) > 1
    for chunk in chunks:
        indexes = [original.index(line) for line in body(chunk).splitlines()]
        assert indexes == list(range(indexes[0], indexes[0] + len(indexes)))


def test_a_formula_is_kept_whole_even_when_it_exceeds_the_cap(
    chunker: StructuralChunker,
) -> None:
    """公式的前一半不是公式：切开的表达式会被检索到，然后被引用成一个不存在的式子。"""
    text = "公式：产能利用率\nU = Q / C\n" + "".join(
        f"说明第{index:02d}句。" for index in range(1, 8)
    )
    parsed = document(block("blk_00020", text, order=0, kind=BlockType.FORMULA, section=SECTION))

    chunks = children(chunk_all(chunker, parsed))

    assert len(chunks) == 1
    assert body(chunks[0]) == text
    assert chunks[0].chunk_type is ChunkType.FORMULA


# --- the identity decided upstream survives into the chunk ---


def test_a_vision_derived_region_stays_unverified_after_chunking(
    chunker: StructuralChunker,
) -> None:
    """块的来源不会因为被切过就变得可信，这个判断要在块上继续成立。"""
    text = "（模型派生描述）欧洲户储月度装机连续三个月回升"
    parsed = document(
        block(
            "blk_00011",
            text,
            order=0,
            kind=BlockType.CHART,
            section=SECTION,
            page_number=21,
        ),
        non_text=(
            NonTextBlock(
                block_id="blk_00011",
                block_type=BlockType.CHART,
                content_origin=ExtractionMethod.VISION_DERIVED,
                indexable_text=text,
                confidence=0.42,
                requires_verification=True,
                page_number=21,
            ),
        ),
    )

    chunk = children(chunk_all(chunker, parsed))[0]

    assert chunk.content_origin is ExtractionMethod.VISION_DERIVED
    assert chunk.requires_verification is True
    assert chunk.confidence == pytest.approx(0.42)
    assert chunk.chunk_type is ChunkType.CHART


def test_a_parsed_table_does_not_ask_for_verification(chunker: StructuralChunker) -> None:
    chunk = children(chunk_all(chunker, table_document()))[0]

    assert chunk.content_origin is ExtractionMethod.PARSER_DERIVED
    assert chunk.requires_verification is False


def test_chunk_types_follow_the_blocks_they_came_from(chunker: StructuralChunker) -> None:
    cases = {
        BlockType.PARAGRAPH: ChunkType.TEXT,
        BlockType.LIST: ChunkType.TEXT,
        BlockType.CODE: ChunkType.CODE,
        BlockType.FORMULA: ChunkType.FORMULA,
        BlockType.CHART: ChunkType.CHART,
        BlockType.IMAGE: ChunkType.IMAGE_CAPTION,
    }

    for kind, expected in cases.items():
        parsed = document(block("blk_00001", "一句话内容。", order=0, kind=kind, section=SECTION))
        assert children(chunk_all(chunker, parsed))[0].chunk_type is expected


# --- locality ---


def test_a_chunk_keeps_the_page_and_the_block_it_came_from(chunker: StructuralChunker) -> None:
    parsed = document(
        paragraph("blk_00001", sentences(2), order=0, section=SECTION, page_number=5),
        block(
            "blk_00002",
            sentences(2, start=3),
            order=1,
            kind=BlockType.CODE,
            section=SECTION,
            page_number=7,
        ),
    )

    chunks = children(chunk_all(chunker, parsed))

    assert chunks[0].source.page_start == 5
    assert chunks[1].source.block_ids == ("blk_00002",)
    assert chunks[1].source.page_start == 7


def test_every_span_stays_inside_its_own_chunk_and_covers_real_text(
    chunker: StructuralChunker,
) -> None:
    """块内偏移必须指回这一块自己的文字：指到别处的高亮比没有高亮更糟。"""
    parsed = document(paragraph("blk_00001", sentences(12), order=0, section=SECTION))

    chunks = children(chunk_all(chunker, parsed))

    for chunk in chunks:
        assert chunk.source.spans
        for span in chunk.source.spans:
            assert 0 <= span.start < span.end <= len(chunk.content)
            assert chunk.content[span.start : span.end].strip()
        assert chunk.source.block_ids == ("blk_00001",)


def test_the_bytes_of_a_region_never_reach_the_chunk(chunker: StructuralChunker) -> None:
    """原图留在对象存储：chunk 会进检索结果与 Agent 上下文，字节不会（规格 7.9）。"""
    text = "图 5 储能电站分布"
    parsed = document(
        block(
            "blk_00012",
            text,
            order=0,
            kind=BlockType.IMAGE,
            section=SECTION,
            page_number=9,
        ),
    )

    chunk = children(chunk_all(chunker, parsed))[0]

    assert chunk.content == f"{SECTION_PREFIX}{text}"
    assert chunk.chunk_type is ChunkType.IMAGE_CAPTION


# --- the offline token counter ---


def test_the_default_counter_is_deterministic_and_needs_no_model() -> None:
    counter = ApproximateTokenCounter()

    assert counter.count("") == 0
    assert counter.count("储能") == 2
    assert counter.count("energy storage") == 2
    assert counter.count("储能 storage") == 3
    assert counter.version


def test_the_default_policy_holds_the_spec_budget_on_real_prose() -> None:
    counter = ApproximateTokenCounter()
    text = "海外储能订单在 2026 年第二季度明显增长，二季度新增订单同比翻倍。" * 40
    parsed = document(paragraph("blk_00001", text, order=0, section=SECTION))

    chunks = children(chunk_all(StructuralChunker(tokenizer=counter), parsed, ChunkingPolicy()))

    assert len(chunks) > 1
    assert all(
        counter.count(chunk.content) <= ChunkingPolicy().child_soft_cap_tokens
        for chunk in chunks
    )


# --- the sentence splitter on its own ---


def test_the_splitter_keeps_terminators_and_drops_blank_segments() -> None:
    assert split_sentences("第一句。第二句！\n\n第三句？") == ("第一句。", "第二句！", "第三句？")
    assert split_sentences("   ") == ()
    assert split_sentences("没有终止符的一句话") == ("没有终止符的一句话",)
