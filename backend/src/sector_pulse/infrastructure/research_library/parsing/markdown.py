"""Markdown 解析：把已经存在的结构照搬过来，而不是重新推断一遍。

Markdown 是三种源格式里唯一自带大纲和边界的。规格 7.6 的要求核心只有一条——别把它弄丢：
标题层级要变成 `heading_path`，表格和代码块不能被从中间切开，源字符范围要能定位回原文。

因此这里用 `markdown-it-py` 的 token 流而不是先渲染成 HTML 再抽文本：token 流同时带着
嵌套结构、`map`（源行范围）和代码块的原样内容，渲染成 HTML 之后这三样都要重新猜。
"""

from dataclasses import dataclass
from typing import Any

from markdown_it import MarkdownIt

from sector_pulse.domain.research_library.models import (
    BlockType,
    DocumentBlock,
    ExtractionMethod,
    SourceSpan,
)
from sector_pulse.ports.research_models import ParsedDocument, ParseSource, TableData

PARSER_NAME = "markdown"
PARSER_VERSION = "markdown-it-v1"

MARKDOWN_MEDIA_TYPES = frozenset({"text/markdown", "text/x-markdown", "application/markdown"})

#: 表格单元格里的换行会破坏 Markdown 表格语法，用可见分隔符替掉。
CELL_SEPARATOR = " | "
ROW_SEPARATOR = "\n"


class MarkdownDocumentParser:
    """`DocumentParser` 的 Markdown 实现。"""

    name = PARSER_NAME
    media_types = MARKDOWN_MEDIA_TYPES

    def __init__(self) -> None:
        # `commonmark` 预设不含表格；表格是规格 7.6 明确要求的结构块。
        self._parser = MarkdownIt("commonmark").enable("table")

    def parse(self, source: ParseSource) -> ParsedDocument:
        text = _decode(source.content)
        tokens = self._parser.parse(text)
        positions = _SourceIndex(text)

        stack: list[tuple[int, str]] = []
        blocks: list[DocumentBlock] = []
        tables: list[TableData] = []
        index = 0
        warnings: list[str] = []

        while index < len(tokens):
            token = tokens[index]
            section = tuple(title for _, title in stack)
            span = positions.span_of(token)

            if token.type == "heading_open":
                level = int(token.tag[1:])
                title = _inline_text(tokens[index + 1])
                stack = [entry for entry in stack if entry[0] < level]
                stack.append((level, title))
                blocks.append(
                    _block(
                        order=len(blocks),
                        block_type=BlockType.HEADING,
                        text=title,
                        heading_path=tuple(text for _, text in stack),
                        source_span=span,
                    )
                )
                index += 3  # heading_open, inline, heading_close
                continue

            if token.type in {"fence", "code_block"}:
                # 代码块整体进入一个块：围栏里的内容不是散文，按句子切开等于改写了它。
                blocks.append(
                    _block(
                        order=len(blocks),
                        block_type=BlockType.CODE,
                        text=token.content.rstrip("\n"),
                        heading_path=section,
                        source_span=span,
                    )
                )
                index += 1
                continue

            if token.type == "table_open":
                table, index = _read_table(tokens, index, block_id=_block_id(len(blocks)))
                blocks.append(
                    _block(
                        order=len(blocks),
                        block_type=BlockType.TABLE,
                        # 规范化后的可检索文本由流水线写入（Task 6）；这里先留下这张表
                        # 在原文里的样子，避免块在规范化之前没有内容。
                        text=table.text,
                        heading_path=section,
                        source_span=span,
                    )
                )
                tables.append(
                    table.data.model_copy(
                        # 表名取最近的标题：切片之后数据行会离开表头，没有表名的行没有主语。
                        update={"title": table.data.title or (section[-1] if section else None)}
                    )
                )
                continue

            if token.type in {"bullet_list_open", "ordered_list_open"}:
                items, index = _read_list(tokens, index)
                for item in items:
                    blocks.append(
                        _block(
                            order=len(blocks),
                            block_type=BlockType.LIST,
                            text=item,
                            heading_path=section,
                            source_span=span,
                        )
                    )
                continue

            if token.type == "paragraph_open":
                caption = _standalone_image(tokens[index + 1])
                if caption is not None:
                    # 独占一段的图片是图片，不是插图在句子里的字。把它当图题交给流水线，
                    # 而不是把 alt 混进正文（规格 7.10）。
                    blocks.append(
                        _block(
                            order=len(blocks),
                            block_type=BlockType.IMAGE,
                            text=caption,
                            heading_path=section,
                            source_span=span,
                        )
                    )
                else:
                    paragraph = _inline_text(tokens[index + 1])
                    if paragraph:
                        blocks.append(
                            _block(
                                order=len(blocks),
                                block_type=BlockType.PARAGRAPH,
                                text=paragraph,
                                heading_path=section,
                                source_span=span,
                            )
                        )
                index += 3
                continue

            if token.type == "blockquote_open":
                quoted, index = _read_blockquote(tokens, index)
                for paragraph in quoted:
                    blocks.append(
                        _block(
                            order=len(blocks),
                            block_type=BlockType.PARAGRAPH,
                            text=paragraph,
                            heading_path=section,
                            source_span=span,
                        )
                    )
                continue

            if token.type == "html_block":
                # 裸 HTML 是内容，不是我们该解释的结构：按原文留成代码块，而不是让文档
                # 自己决定块类型。
                blocks.append(
                    _block(
                        order=len(blocks),
                        block_type=BlockType.CODE,
                        text=token.content.rstrip("\n"),
                        heading_path=section,
                        source_span=span,
                    )
                )

            index += 1

        if not blocks:
            warnings.append("the Markdown document produced no blocks")

        return ParsedDocument(
            blocks=tuple(blocks),
            tables=tuple(tables),
            page_count=0,
            parser_name=PARSER_NAME,
            parser_version=PARSER_VERSION,
            warnings=tuple(warnings),
        )


class _SourceIndex:
    """把 markdown-it 的 0 基行号翻回解码后文本的字符区间。

    token 只给行号，而规格 7.6 要的是“引用可以定位回原文”。行号到字符偏移的换算是
    确定的，因此这里一次建好索引，之后每次查询都是常数时间。
    """

    def __init__(self, text: str) -> None:
        self._text = text
        starts = [0]
        for line in text.splitlines(keepends=True):
            starts.append(starts[-1] + len(line))
        self._starts = starts
        self._line_count = len(starts) - 1

    def span_of(self, token: Any) -> SourceSpan | None:
        mapping = getattr(token, "map", None)
        if not mapping:
            return None
        start_line = int(mapping[0])
        end_line = min(int(mapping[1]), self._line_count)
        if start_line >= self._line_count or end_line <= start_line:
            return None
        start = self._starts[start_line]
        # 区间不含块尾的换行：那是分隔符，不属于块的文本。
        raw = self._text[start : self._starts[end_line]]
        end = start + len(raw.rstrip("\r\n"))
        if end <= start:
            return None
        return SourceSpan(start=start, end=end)


def _decode(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="replace")


def _inline_text(token: Any) -> str:
    """把行内 token 展平成文本，丢弃标记本身。

    `heading_open` 的 `#`、强调的 `**` 都是标记，不是文档内容；把它们留在正文里会让
    标题在索引里变成 `## 海外需求`，检索时“海外需求”反而不匹配。
    """
    if token is None or not getattr(token, "children", None):
        return (token.content if token is not None else "").strip()
    parts: list[str] = []
    for child in token.children:
        if child.type in {"text", "code_inline", "math_inline"}:
            parts.append(child.content)
        elif child.type in {"softbreak", "hardbreak"}:
            # 软换行是排版折行，用一个空格还原词与词的分隔。
            parts.append(" ")
        elif child.type == "image":
            # 图片的 alt 是作者写的说明，属于正文；图片本身另走 Task 6。
            parts.append(child.content)
        elif child.type == "html_inline":
            continue
    return "".join(parts).strip()


@dataclass(frozen=True)
class _Table:
    """一张表的两面：结构化数据，以及它在原文里的样子。"""

    data: TableData
    text: str


def _read_table(tokens: list[Any], start: int, *, block_id: str) -> tuple[_Table, int]:
    """读出一张表的列与行。

    规格 7.8 要求表格同时保存结构化数据和检索文本表示，因此这里两样都产出：结构化数据
    交给流水线规范化（Task 6），原文样子作为规范化之前块的内容。切在表格中间会同时毁掉
    表头和单位，所以整张表作为一个块，由 Task 7 的切片器决定如何在行组边界拆分。
    """
    index = start + 1
    header: list[str] = []
    rows: list[list[str]] = []
    current: list[str] = []

    while index < len(tokens) and tokens[index].type != "table_close":
        token = tokens[index]
        if token.type == "tr_open":
            current = []
        elif token.type in {"th_open", "td_open"}:
            current.append(_inline_text(tokens[index + 1]))
        elif token.type == "tr_close":
            if header:
                rows.append(current)
            else:
                header = current
        index += 1

    columns = tuple(header)
    # 缺格子的行补空、多出来的格子丢弃：错位的行会被索引成"值属于别的列"，比缺值更糟。
    aligned = tuple(
        tuple(list(row)[: len(columns)] + [""] * max(0, len(columns) - len(row))) for row in rows
    )
    data = TableData(block_id=block_id, columns=columns, rows=aligned)
    return _Table(data=data, text=_raw_table_text(columns, aligned)), index + 1


def _raw_table_text(columns: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> str:
    lines = [CELL_SEPARATOR.join(columns)]
    lines.extend(CELL_SEPARATOR.join(row) for row in rows)
    return ROW_SEPARATOR.join(lines)


def _read_list(tokens: list[Any], start: int) -> tuple[list[str], int]:
    """每个列表项一个块。列表项是独立的断言单元，合并成一段会让它们无法被单独引用。"""
    depth = 0
    index = start
    items: list[str] = []
    current: list[str] = []

    while index < len(tokens):
        token = tokens[index]
        if token.type in {"bullet_list_open", "ordered_list_open"}:
            depth += 1
        elif token.type in {"bullet_list_close", "ordered_list_close"}:
            depth -= 1
            if depth == 0:
                if current:
                    items.append(" ".join(current).strip())
                return items, index + 1
        elif token.type == "inline" and depth == 1:
            text = _inline_text(token)
            if text:
                current.append(text)
        elif token.type == "list_item_close" and depth == 1:
            if current:
                items.append(" ".join(current).strip())
            current = []
        index += 1
    return items, index


def _read_blockquote(tokens: list[Any], start: int) -> tuple[list[str], int]:
    depth = 0
    index = start
    paragraphs: list[str] = []
    while index < len(tokens):
        token = tokens[index]
        if token.type == "blockquote_open":
            depth += 1
        elif token.type == "blockquote_close":
            depth -= 1
            if depth == 0:
                return paragraphs, index + 1
        elif token.type == "inline" and depth == 1:
            text = _inline_text(token)
            if text:
                paragraphs.append(text)
        index += 1
    return paragraphs, index


def _block_id(order: int) -> str:
    """块编号由位置决定，因此同一份文档每次解析得到同一批编号。"""
    return f"blk_{order:05d}"


def _standalone_image(token: Any) -> str | None:
    """独占一段的图片返回它的 alt（没有 alt 返回空串），否则返回 None。

    判断看的是行内结构而不是文本内容：`![图](a.png)` 与 "见 ![图](a.png)" 都是图片，
    但只有一个的 alt 是这张图的图题。
    """
    children = getattr(token, "children", None) or []
    meaningful = [child for child in children if child.type != "text" or child.content.strip()]
    if len(meaningful) != 1 or meaningful[0].type != "image":
        return None
    alt: str = meaningful[0].content
    return alt.strip()


def _block(
    *,
    order: int,
    block_type: BlockType,
    text: str,
    heading_path: tuple[str, ...],
    source_span: SourceSpan | None,
) -> DocumentBlock:
    return DocumentBlock(
        block_id=_block_id(order),
        block_type=block_type,
        text=text,
        heading_path=heading_path,
        page_number=None,
        block_order=order,
        bounding_box=None,
        source_span=source_span,
        # Markdown 的结构是作者写下的，不是我们推断的——这是唯一一种不靠猜的来源。
        extraction_method=ExtractionMethod.PARSER_DERIVED,
        extraction_confidence=1.0,
    )
