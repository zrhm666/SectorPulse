"""结构化切片：子块用来检索，父块用来阅读（规格 8）。

切片里每一个决定都能在事后变成一条检索不到的答案，而当时看不出任何异常——切出来的
仍然是文本，仍然能嵌入。所以这里的规则都写死，不留给调用方即兴发挥：

- **确定性**。同样的文档、同样的口径，切出的块与 ID 每次都一样。块 ID 由文档版本、
  切片口径版本、分词器版本、源块 ID、块内区间与内容哈希共同决定，因此重试不会产生新行，
  重索引不会产生重复。这一条是硬要求：Outbox 会重试，Milvus 以 `chunk_id` 幂等。
- **切句不切词**。子块边界落在句子边界上，绝不落在句子中间。
- **结构自带上下文**。章节路径直接抄进每个子块正文，表格的数据行带上表名、单位和列名。
  切片之后块会离开它所在的章节，靠重叠"碰巧"带上标题并不可靠。
- **按自身结构切**。表格按行组切并重复表头，代码按行切，公式与图表整块保留——切开的
  公式会被检索到，然后被引用成一个并不存在的式子。
- **身份跟着块走**。Task 6 定下的来源（`content_origin`）、置信度与是否待核验在这里
  原样传递：一段视觉模型猜出来的描述不会因为被切过而变得可信。

`source.spans` 是**块内**字符区间，不是原文区间：块正文是重新拼起来的（带章节前缀、
带重叠），它在原文里本来就不是一段连续文本。回到原文件的链条是
`chunk → source.block_ids → 规范化文档 → 该块的页码/坐标或源字符范围`，段段可查。
"""

import hashlib
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator
from sector_pulse.application.research_library.non_text_blocks import normalize_table
from sector_pulse.domain.research_library.models import (
    BlockType,
    ChunkType,
    DocumentBlock,
    ExtractionMethod,
    Record,
    ResearchChunk,
    SourceLocator,
    SourceSpan,
    utc_now,
)
from sector_pulse.ports.research_models import (
    NonTextBlock,
    ParsedDocument,
    TableData,
    TokenCounter,
)

#: 整套切片口径的版本。预算、结构规则、分词器或 **chunk ID 的取法** 的任何改变都要提升它。
#: v2：ID 里加入父子角色（见 `_chunk_id`）。改了取法却不提升版本，会让"同一口径下重跑
#: 得到同一批 ID"这件事不成立——而那正是把 Milvus 当成可重建派生索引的前提。
CHUNKING_POLICY_VERSION = "chunking-policy-v2"

CHUNK_ID_PREFIX = "chunk_"
#: 128 位：长到不会撞，短到日志里读得下去。
CHUNK_ID_DIGEST_LENGTH = 32

BLOCK_SEPARATOR = "\n\n"
HEADING_SEPARATOR = " > "

#: 句末标点。刻意不含 `.`：这批文档里的小数、编号和小节号比英文句号更常见，
#: 按 `.` 切会把 `3.2 海外需求` 和 `120.5 亿` 切成两段。
SENTENCE_ENDINGS = frozenset("。！？!?；;")

#: 中日韩字符与全角标点。既用来近似计数，也用来判断句子之间该不该补空格。
CJK_CHARACTER = re.compile("[　-鿿豈-﫿＀-￯]")
NON_CJK_RUN = re.compile(r"[^\s]+")

#: 按自身结构成块的类型：不参与相邻散文的打包，也不会被切开（表格按行组除外）。
STRUCTURAL_BLOCK_TYPES = frozenset(
    {
        BlockType.TABLE,
        BlockType.CODE,
        BlockType.FORMULA,
        BlockType.CHART,
        BlockType.IMAGE,
    }
)

BLOCK_CHUNK_TYPES: dict[BlockType, ChunkType] = {
    BlockType.HEADING: ChunkType.TEXT,
    BlockType.PARAGRAPH: ChunkType.TEXT,
    BlockType.LIST: ChunkType.TEXT,
    BlockType.FIGURE_CAPTION: ChunkType.TEXT,
    BlockType.TABLE: ChunkType.TABLE,
    BlockType.CODE: ChunkType.CODE,
    BlockType.FORMULA: ChunkType.FORMULA,
    BlockType.CHART: ChunkType.CHART,
    BlockType.IMAGE: ChunkType.IMAGE_CAPTION,
}

#: 来源的可疑程度：一块内容里只要有一处来自 OCR 或视觉模型，整块就按那个身份记账。
ORIGIN_SUSPICION: dict[ExtractionMethod, int] = {
    ExtractionMethod.NATIVE: 0,
    ExtractionMethod.PARSER_DERIVED: 1,
    ExtractionMethod.OCR: 2,
    ExtractionMethod.VISION_DERIVED: 3,
}


class ChunkRole(StrEnum):
    """块在父子结构里的位置。它是块身份的一部分（见 `_chunk_id`）。"""

    PARENT = "parent"
    CHILD = "child"


class ChunkingPolicy(Record):
    """切片预算。默认值即规格 8 的数字：子块 300–500、软上限 700、重叠 50–80、
    父块 800–1500。"""

    version: str = Field(default=CHUNKING_POLICY_VERSION, min_length=1)

    child_min_tokens: int = Field(default=300, gt=0)
    child_target_tokens: int = Field(default=400, gt=0)
    child_soft_cap_tokens: int = Field(default=700, gt=0)
    child_overlap_tokens: int = Field(default=65, ge=0)

    parent_target_tokens: int = Field(default=1200, gt=0)
    parent_max_tokens: int = Field(default=1500, gt=0)

    @model_validator(mode="after")
    def _child_budget_is_ordered(self) -> "ChunkingPolicy":
        if self.child_min_tokens > self.child_target_tokens:
            raise ValueError("child_min_tokens must not exceed child_target_tokens")
        if self.child_target_tokens > self.child_soft_cap_tokens:
            raise ValueError("child_target_tokens must not exceed child_soft_cap_tokens")
        if self.child_overlap_tokens >= self.child_min_tokens:
            raise ValueError(
                "child_overlap_tokens must stay below child_min_tokens, otherwise a chunk "
                "can be nothing but the previous chunk's tail"
            )
        return self

    @model_validator(mode="after")
    def _parent_budget_is_ordered(self) -> "ChunkingPolicy":
        if self.parent_target_tokens > self.parent_max_tokens:
            raise ValueError("parent_target_tokens must not exceed parent_max_tokens")
        return self


class ApproximateTokenCounter:
    """不依赖模型的确定性近似计数：CJK 字符一个算一个，其余按空白切段。

    真词表要下载、还要随模型版本变化，而这个数字决定块的边界和块 ID。用可解释的近似
    换来的是：任何环境、任何时间切出来的块都一样。中日韩文本里一个汉字大致就是一个
    token，西文按词切也接近；误差落在预算的余量里，而预算本身是区间而不是点。
    """

    version = "cjk-approx-v1"

    def count(self, text: str) -> int:
        without_cjk = CJK_CHARACTER.sub(" ", text)
        return len(CJK_CHARACTER.findall(text)) + len(NON_CJK_RUN.findall(without_cjk))


@dataclass(frozen=True)
class _Piece:
    """句子、代码行或整张表切片，连同它来自哪个块。

    `separator` 是它在同一个块内紧跟前一段时的连接符：散文按两侧字符决定要不要空格，
    代码永远是换行。跨块时由装配逻辑改用 `BLOCK_SEPARATOR`，因此这里不必知道边界在哪。
    """

    text: str
    block_id: str
    page_number: int | None = None
    separator: str = ""


@dataclass(frozen=True)
class _Rendered:
    content: str
    block_ids: tuple[str, ...]
    spans: tuple[SourceSpan, ...]
    page_start: int | None
    page_end: int | None


def split_sentences(text: str) -> tuple[str, ...]:
    """按句末标点与换行切句，保留终止符，丢弃空白段。

    终止符留在句子里：`2025 年。` 与 `2025 年` 检索起来不是一件事，去掉句号拼回去的
    正文也不再是原文。
    """
    segments: list[str] = []
    start = 0
    for index, character in enumerate(text):
        if character in SENTENCE_ENDINGS:
            # 终止符属于这一句：去掉句号拼回去的正文不再是原文。
            segments.append(text[start : index + 1])
            start = index + 1
        elif character == "\n":
            segments.append(text[start:index])
            start = index + 1
    segments.append(text[start:])
    return tuple(segment.strip() for segment in segments if segment.strip())


class StructuralChunker:
    """把一次解析的结果切成父块与子块。"""

    def __init__(self, *, tokenizer: TokenCounter | None = None) -> None:
        self._counter: TokenCounter = (
            tokenizer if tokenizer is not None else ApproximateTokenCounter()
        )

    @property
    def tokenizer(self) -> TokenCounter:
        return self._counter

    def chunk(
        self,
        parsed: ParsedDocument,
        policy: ChunkingPolicy,
        *,
        document_id: str,
        document_version_id: str,
        created_at: datetime | None = None,
    ) -> tuple[ResearchChunk, ...]:
        """返回父块与其子块，按文档顺序排列：每个父块紧跟它自己的子块。

        父子在一次调用里一起返回，调用方不必再拼一次；两者的区别只是 `parent_chunk_id`。
        Milvus 只装子块——父块用来展开上下文，不参与向量召回。
        """
        blocks_by_id = {block.block_id: block for block in parsed.blocks}
        non_text = {entry.block_id: entry for entry in parsed.non_text_blocks}
        stamp = created_at if created_at is not None else utc_now()
        chunks: list[ResearchChunk] = []

        for fragment in self._fragments(parsed.blocks, policy):
            if not any(_is_readable(block) for block in fragment):
                continue
            parent = self._build(
                pieces=_parent_pieces(fragment),
                context=_parent_context(fragment),
                chunk_type=_dominant_chunk_type(fragment),
                parent_chunk_id=None,
                policy=policy,
                blocks_by_id=blocks_by_id,
                non_text=non_text,
                document_id=document_id,
                document_version_id=document_version_id,
                created_at=stamp,
            )
            chunks.append(parent)
            for group in self._groups(fragment, non_text, policy):
                chunks.append(
                    self._build(
                        pieces=group,
                        context=_child_context(fragment),
                        chunk_type=_dominant_chunk_type(
                            [blocks_by_id[block_id] for block_id in _distinct_block_ids(group)]
                        ),
                        parent_chunk_id=parent.chunk_id,
                        policy=policy,
                        blocks_by_id=blocks_by_id,
                        non_text=non_text,
                        document_id=document_id,
                        document_version_id=document_version_id,
                        created_at=stamp,
                    )
                )
        return tuple(chunks)

    # --- 分段 ---

    def _fragments(
        self, blocks: Sequence[DocumentBlock], policy: ChunkingPolicy
    ) -> Iterator[tuple[DocumentBlock, ...]]:
        """连续的、同属一个章节的块构成父块的候选；过长时在块边界上断开。

        父块的边界只落在块上：把一个段落劈成两个父块，读起来比一个长父块更糟。
        """
        current: list[DocumentBlock] = []
        section: tuple[str, ...] | None = None
        tokens = 0

        for block in blocks:
            if current:
                weight = self._fragment_cost(block, opening=False)
                if block.heading_path != section or tokens + weight > policy.parent_max_tokens:
                    yield tuple(current)
                    current = []
                    tokens = 0
                    weight = self._fragment_cost(block, opening=True)
            else:
                weight = self._fragment_cost(block, opening=True)
            current.append(block)
            section = block.heading_path
            tokens += weight

        if current:
            yield tuple(current)

    def _fragment_cost(self, block: DocumentBlock, *, opening: bool) -> int:
        """一个块给父块正文增添的开销。

        算的是父块正文而不是块文本之和：正文还要带上章节前缀和块间分隔符，不把它们算进
        去，父块就会在"没有超"的情况下超过上限。
        """
        cost = self._counter.count(block.text)
        if not opening:
            return cost + self._counter.count(BLOCK_SEPARATOR)
        if block.block_type is BlockType.HEADING:
            # 以标题开头的父块不再重复标题，也就没有前缀开销。
            return cost
        return cost + self._counter.count(_prefix_of(block.heading_path))

    # --- 子块 ---

    def _groups(
        self,
        fragment: Sequence[DocumentBlock],
        non_text: dict[str, NonTextBlock],
        policy: ChunkingPolicy,
    ) -> list[list[_Piece]]:
        """把一段章节拆成若干子块。

        散文块先攒在一起再打包：切片目标是 300–500 token，逐块成块会让每个短段落各占
        一块，于是"目标长度"从来没有起过作用。结构块是边界，不参与打包——把代码块和它
        前后的散文拌在一起，两边都读不出来。
        """
        context = _child_context(fragment)
        groups: list[list[_Piece]] = []
        pending: list[_Piece] = []

        for block in fragment:
            if not _is_readable(block):
                continue
            if block.block_type in STRUCTURAL_BLOCK_TYPES:
                groups.extend(self._pack(pending, context, policy))
                pending = []
                groups.extend(self._structural_groups(block, context, non_text, policy))
            else:
                pending.extend(_text_pieces(block))

        groups.extend(self._pack(pending, context, policy))
        return [group for group in groups if group]

    def _structural_groups(
        self,
        block: DocumentBlock,
        context: tuple[str, ...],
        non_text: dict[str, NonTextBlock],
        policy: ChunkingPolicy,
    ) -> list[list[_Piece]]:
        """结构块按自身结构切：表格按行组，代码按行，公式与图表整块保留。"""
        entry = non_text.get(block.block_id)
        if block.block_type is BlockType.TABLE and entry is not None and entry.table is not None:
            return self._table_groups(block, entry.table, context, policy)
        if block.block_type is BlockType.CODE:
            return self._pack(_line_pieces(block), context, policy)
        # 公式和图表不切：切开之后的一半会被检索到，然后被引用成一个不存在的式子或
        # 一张不存在的图。超上限也整块保留，这是唯一不会伪造内容的选择。
        return [[_Piece(text=block.text, block_id=block.block_id, page_number=block.page_number)]]

    def _table_groups(
        self,
        block: DocumentBlock,
        table: TableData,
        context: tuple[str, ...],
        policy: ChunkingPolicy,
    ) -> list[list[_Piece]]:
        """按行组切表，每一块都带上表名、单位和列名。

        数据行离开表头就没有主语，离开单位就没有量纲，所以结构上下文是被复制的，
        而不是靠重叠碰巧带上。一行都放不下时，那一行自己成块：行不能切。
        """
        rows = list(table.rows)
        if not rows:
            return self._pack(_text_pieces(block), context, policy)

        bounds: list[tuple[int, int]] = []
        start = 0
        while start < len(rows):
            end = start + 1
            while end < len(rows) and _fits(
                _table_slice(table, rows[start : end + 1], notes=None),
                context,
                self._counter,
                policy,
            ):
                end += 1
            bounds.append((start, end))
            start = end

        groups: list[list[_Piece]] = []
        for position, (first, last) in enumerate(bounds):
            # 注释说的是整张表的口径：复制到每一块只是噪音，留在一块里才不会被丢掉。
            notes = table.notes if position == len(bounds) - 1 else None
            text = _table_slice(table, rows[first:last], notes=notes) or block.text
            groups.append(
                [
                    _Piece(
                        text=text,
                        block_id=block.block_id,
                        page_number=block.page_number,
                    )
                ]
            )
        return groups

    def _pack(
        self,
        pieces: Sequence[_Piece],
        context: tuple[str, ...],
        policy: ChunkingPolicy,
    ) -> list[list[_Piece]]:
        """贪心打包：填到目标为止，越过上限之前收口，下一块带上配置的重叠。"""
        groups: list[list[_Piece]] = []
        current: list[_Piece] = []
        #: `current` 末尾有多少段是这一块新增的（前几段是上一块带过来的重叠）。
        fresh = 0

        for piece in pieces:
            if current and not _fits(_text_of([*current, piece]), context, self._counter, policy):
                if fresh:
                    groups.append(current)
                current = self._overlap(current, context, policy)
                fresh = 0
                if current and not _fits(
                    _text_of([*current, piece]), context, self._counter, policy
                ):
                    # 带上重叠就放不下：重叠让位。宁可少一点上下文，也不越过上限——
                    # 上限是给模型和向量库的，跨过去一次就再也回不来。
                    current = []
            current.append(piece)
            fresh += 1
            if self._count(current, context) >= policy.child_target_tokens:
                groups.append(current)
                current = self._overlap(current, context, policy)
                fresh = 0

        if fresh:
            # 收尾的碎块并回上一块：单独成块只会多一次检索和一条几乎重复的向量。
            # 只有低于下限才并——够长的收尾块是自己的一个语义单元，并进去反而稀释了它。
            merged = _merge_target(groups, current, fresh)
            if (
                self._count(current, context) < policy.child_min_tokens
                and merged is not None
                and _fits(_text_of(merged), context, self._counter, policy)
            ):
                groups[-1] = merged
            else:
                groups.append(current)

        return groups

    def _overlap(
        self, pieces: Sequence[_Piece], context: tuple[str, ...], policy: ChunkingPolicy
    ) -> list[_Piece]:
        """下一块开头的重叠：从尾部往前攒够配置的 token 数。"""
        if policy.child_overlap_tokens == 0:
            return []
        overlap: list[_Piece] = []
        total = 0
        for piece in reversed(pieces):
            overlap.insert(0, piece)
            total += self._counter.count(piece.text)
            if total >= policy.child_overlap_tokens:
                break
        return overlap

    def _count(self, pieces: Sequence[_Piece], context: tuple[str, ...]) -> int:
        return self._counter.count(_prefix_of(context) + _text_of(pieces))

    # --- 组装 ---

    def _build(
        self,
        *,
        pieces: Sequence[_Piece],
        context: tuple[str, ...],
        chunk_type: ChunkType,
        parent_chunk_id: str | None,
        policy: ChunkingPolicy,
        blocks_by_id: dict[str, DocumentBlock],
        non_text: dict[str, NonTextBlock],
        document_id: str,
        document_version_id: str,
        created_at: datetime,
    ) -> ResearchChunk:
        rendered = _render(context, pieces)
        origin, confidence, requires_verification = _identity(
            rendered.block_ids, blocks_by_id, non_text
        )

        return ResearchChunk(
            chunk_id=_chunk_id(
                document_version_id=document_version_id,
                policy=policy,
                counter_version=self._counter.version,
                role=ChunkRole.PARENT if parent_chunk_id is None else ChunkRole.CHILD,
                rendered=rendered,
            ),
            document_id=document_id,
            document_version_id=document_version_id,
            parent_chunk_id=parent_chunk_id,
            chunk_type=chunk_type,
            content=rendered.content,
            content_hash=content_hash(rendered.content),
            source=SourceLocator(
                page_start=rendered.page_start,
                page_end=rendered.page_end,
                section_path=tuple(context),
                block_ids=rendered.block_ids,
                spans=rendered.spans,
            ),
            content_origin=origin,
            confidence=confidence,
            requires_verification=requires_verification,
            created_at=created_at,
        )


# --- 块与切片 ---


def _is_readable(block: DocumentBlock) -> bool:
    """标题不是可读内容：它给下面的块提供上下文，本身不构成一条可检索的断言。"""
    return block.block_type is not BlockType.HEADING and bool(block.text.strip())


def _parent_context(fragment: Sequence[DocumentBlock]) -> tuple[str, ...]:
    """父块以标题开头时不再重复一遍标题。"""
    first = fragment[0] if fragment else None
    if first is None or first.block_type is BlockType.HEADING:
        return ()
    return tuple(first.heading_path)


def _child_context(fragment: Sequence[DocumentBlock]) -> tuple[str, ...]:
    """子块永远没有标题块（标题不可读），所以章节路径一律抄进正文。"""
    return tuple(fragment[0].heading_path) if fragment else ()


def _parent_pieces(fragment: Sequence[DocumentBlock]) -> list[_Piece]:
    """父块是整个章节：每个块原样进入，块内结构（表格、代码）保持原样。"""
    return [
        _Piece(text=block.text, block_id=block.block_id, page_number=block.page_number)
        for block in fragment
        if block.text.strip()
    ]


def _text_pieces(block: DocumentBlock) -> list[_Piece]:
    pieces: list[_Piece] = []
    previous: str | None = None
    for text in split_sentences(block.text):
        pieces.append(
            _Piece(
                text=text,
                block_id=block.block_id,
                page_number=block.page_number,
                separator="" if previous is None else _joiner(previous),
            )
        )
        previous = text
    return pieces


def _line_pieces(block: DocumentBlock) -> list[_Piece]:
    """代码按行切。空行不携带内容，只留在父块里。"""
    return [
        _Piece(
            text=line.rstrip(),
            block_id=block.block_id,
            page_number=block.page_number,
            separator="" if index == 0 else "\n",
        )
        for index, line in enumerate(block.text.splitlines())
        if line.strip()
    ]


def _joiner(previous: str) -> str:
    """句子之间的连接符。

    中日韩文本用标点断句，句子之间本来没有空格；西文句子之间必须有。判断依据是前一句的
    最后一个字符——这与解析层的折行拼接是同一条规则，理由也一样：补错一个空格，检索会
    把 `增长。二季度` 和一个不存在的词 `增长。 二季度` 当成两回事。
    """
    if previous and CJK_CHARACTER.match(previous[-1]):
        return ""
    return " "


def _table_slice(table: TableData, rows: Sequence[tuple[str, ...]], *, notes: str | None) -> str:
    """用同一个规范化器切出部分行，保证切片与整表说的是同一句话。"""
    text = normalize_table(
        table.model_copy(update={"rows": tuple(rows), "notes": notes})
    ).indexable_text
    return text or ""


def _fits(
    text: str, context: tuple[str, ...], counter: TokenCounter, policy: ChunkingPolicy
) -> bool:
    return counter.count(_prefix_of(context) + text) <= policy.child_soft_cap_tokens


def _merge_target(
    groups: Sequence[list[_Piece]], current: Sequence[_Piece], fresh: int
) -> list[_Piece] | None:
    """碎块的归并目标：上一块 + 这一块的**新**内容。

    重叠部分不再抄一遍，否则拼出来的正文里同一句话会出现两次。
    """
    if not groups:
        return None
    return [*groups[-1], *current[len(current) - fresh :]]


# --- 拼装 ---


def _prefix_of(context: Sequence[str]) -> str:
    return f"{HEADING_SEPARATOR.join(context)}{BLOCK_SEPARATOR}" if context else ""


def _text_of(pieces: Sequence[_Piece]) -> str:
    return "".join(piece.text for piece in pieces)


def _render(context: Sequence[str], pieces: Sequence[_Piece]) -> _Rendered:
    """拼出块正文，同时记下每个源块在正文里的位置。"""
    content = _prefix_of(context)
    bounds: dict[str, list[int]] = {}
    order: list[str] = []
    pages: list[int] = []
    previous: str | None = None

    for piece in pieces:
        if previous is not None:
            content += piece.separator if previous == piece.block_id else BLOCK_SEPARATOR
        start = len(content)
        content += piece.text
        end = len(content)
        if piece.block_id in bounds:
            bounds[piece.block_id][0] = min(bounds[piece.block_id][0], start)
            bounds[piece.block_id][1] = max(bounds[piece.block_id][1], end)
        else:
            bounds[piece.block_id] = [start, end]
            order.append(piece.block_id)
        if piece.page_number is not None:
            pages.append(piece.page_number)
        previous = piece.block_id

    return _Rendered(
        content=content,
        block_ids=tuple(order),
        spans=tuple(
            SourceSpan(start=bounds[block_id][0], end=bounds[block_id][1]) for block_id in order
        ),
        page_start=min(pages) if pages else None,
        page_end=max(pages) if pages else None,
    )


def _distinct_block_ids(pieces: Sequence[_Piece]) -> list[str]:
    seen: list[str] = []
    for piece in pieces:
        if piece.block_id not in seen:
            seen.append(piece.block_id)
    return seen


def _dominant_chunk_type(blocks: Sequence[DocumentBlock]) -> ChunkType:
    """多数块的类型即这一块的类型；数量相同时取文档里先出现的那个。"""
    counts: dict[ChunkType, int] = {}
    for block in blocks:
        kind = BLOCK_CHUNK_TYPES[block.block_type]
        counts[kind] = counts.get(kind, 0) + 1
    best = ChunkType.TEXT
    for kind, count in counts.items():
        if count > counts.get(best, 0):
            best = kind
    return best


def _identity(
    block_ids: Sequence[str],
    blocks_by_id: dict[str, DocumentBlock],
    non_text: dict[str, NonTextBlock],
) -> tuple[ExtractionMethod, float, bool]:
    """取块身份里最可疑的那一份：混合内容不能比它最不可靠的部分更可信。"""
    origins: list[ExtractionMethod] = []
    confidence = 1.0
    requires_verification = False

    for block_id in block_ids:
        block = blocks_by_id[block_id]
        entry = non_text.get(block_id)
        origins.append(entry.content_origin if entry is not None else block.extraction_method)
        confidence = min(
            confidence,
            entry.confidence if entry is not None else block.extraction_confidence,
        )
        if entry is not None and entry.requires_verification:
            requires_verification = True

    if not origins:
        return ExtractionMethod.PARSER_DERIVED, confidence, False
    suspicion = max(ORIGIN_SUSPICION[origin] for origin in origins)
    origin = next(origin for origin in origins if ORIGIN_SUSPICION[origin] == suspicion)
    return origin, confidence, requires_verification


def content_hash(content: str) -> str:
    """内容哈希：忽略空白差异，只对真正的文字变化敏感。

    同一个块连跑两次不该得到两个哈希，而重试路径上白白多出来的换行并不是内容变化。
    """
    normalized = re.sub(r"\s+", " ", content).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _chunk_id(
    *,
    document_version_id: str,
    policy: ChunkingPolicy,
    counter_version: str,
    role: ChunkRole,
    rendered: _Rendered,
) -> str:
    """幂等 ID：与版本绑定、与切法绑定、与角色绑定、与内容绑定。

    `role` 不是冗余：没有小节标题的片段里，父块和子块渲染出的是同一段文字，只按内容
    取 ID 会让两者撞成同一个主键——那样这份文档既写不进 PostgreSQL 也写不进 Milvus。

    刻意不含时间戳或随机数——Outbox 会重试，而重试必须落在同一行上。
    """
    material = "|".join(
        [
            document_version_id,
            policy.version,
            counter_version,
            role.value,
            ",".join(rendered.block_ids),
            ",".join(f"{span.start}-{span.end}" for span in rendered.spans),
            content_hash(rendered.content),
        ]
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"{CHUNK_ID_PREFIX}{digest[:CHUNK_ID_DIGEST_LENGTH]}"
