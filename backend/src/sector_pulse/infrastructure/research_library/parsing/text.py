"""TXT 解析：一个没有结构的文件，唯一能做对的事是确定性地解码它。

规格 7.7 要三件事：检测编码、规范化换行与空白、按段落边界分块。三件都不涉及推断。
TXT 里没有任何标记可以告诉我们哪一行是标题，因此这里刻意不猜——把短行当标题会让
一份中文周报凭空长出章节结构，而这些假结构会进入 `heading_path` 并被引用。

编码阶梯是确定性的而非启发式的：先看 BOM，再依次尝试 UTF-8、GB18030，最后落到
latin-1。GB18030 放在 latin-1 之前是这套阶梯唯一真正的判断——latin-1 能解码任何字节
序列，永远“成功”，把中文报告交给它只会得到一页看似正常的乱码文本，而这份乱码会被
当作正文索引起来，比解析失败更难发现。
"""

import codecs
import re

from sector_pulse.domain.research_library.models import (
    BlockType,
    DocumentBlock,
    ExtractionMethod,
    SourceSpan,
)
from sector_pulse.infrastructure.research_library.parsing.layout import join_wrapped_lines
from sector_pulse.ports.research_models import ParsedDocument, ParseSource

PARSER_NAME = "text"
PARSER_VERSION = "text-normalized-v1"

TEXT_MEDIA_TYPES = frozenset({"text/plain", "text/x-plain", "application/text"})

#: 按顺序尝试的编码。BOM 优先于这张表。
ENCODING_LADDER = ("utf-8", "gb18030")

#: 最后一个候选：它能解码任何字节，因此必须最后用，而且用了要说出来。
FALLBACK_ENCODING = "latin-1"

#: BOM → 编码。`utf-16`/`utf-32` 会自己消化 BOM。
BOM_ENCODINGS: tuple[tuple[bytes, str], ...] = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)

#: 段落之间：一个换行，后面跟着（空格/制表符和）另一个换行。空行本身可以是空文件里
#: 的全部内容，所以 `\n+` 而不是 `\n`。
PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n+")


class TextDocumentParser:
    """`DocumentParser` 的纯文本实现。"""

    name = PARSER_NAME
    media_types = TEXT_MEDIA_TYPES

    def parse(self, source: ParseSource) -> ParsedDocument:
        text, warnings = decode(source.content)
        blocks = tuple(
            DocumentBlock(
                block_id=f"blk_{order:05d}",
                block_type=BlockType.PARAGRAPH,
                text=join_wrapped_lines(text[start:end].splitlines()),
                heading_path=(),
                page_number=None,
                block_order=order,
                bounding_box=None,
                source_span=SourceSpan(start=start, end=end),
                extraction_method=ExtractionMethod.PARSER_DERIVED,
                extraction_confidence=1.0,
            )
            for order, (start, end) in enumerate(paragraph_spans(text))
        )
        return ParsedDocument(
            blocks=blocks,
            page_count=0,
            parser_name=PARSER_NAME,
            parser_version=PARSER_VERSION,
            warnings=warnings,
        )


def decode(payload: bytes) -> tuple[str, tuple[str, ...]]:
    """解码并规范化换行，返回文本与需要告诉调用方的警告。"""
    for bom, encoding in BOM_ENCODINGS:
        if payload.startswith(bom):
            return _normalise(payload.decode(encoding)), ()

    for encoding in ENCODING_LADDER:
        try:
            return _normalise(payload.decode(encoding)), ()
        except UnicodeDecodeError:
            continue

    return (
        _normalise(payload.decode(FALLBACK_ENCODING)),
        (
            "this file is not valid "
            f"{' or '.join(ENCODING_LADDER)}; it was decoded as {FALLBACK_ENCODING}, so its "
            "text may be wrong",
        ),
    )


def _normalise(text: str) -> str:
    """换行统一成 `\\n`。

    `\\r\\n` 不统一的话，一次 Windows 折行会变成一个空行，于是每个段落都被从中间切开，
    而切出来的两半各自看起来都像完整的段落。
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def paragraph_spans(text: str) -> tuple[tuple[int, int], ...]:
    """每个段落的半开字符区间 `[start, end)`，指向规范化后的文本。"""
    spans: list[tuple[int, int]] = []
    cursor = 0
    for match in PARAGRAPH_BREAK.finditer(text):
        span = _trim(text, cursor, match.start())
        if span is not None:
            spans.append(span)
        cursor = match.end()
    span = _trim(text, cursor, len(text))
    if span is not None:
        spans.append(span)
    return tuple(spans)


def _trim(text: str, start: int, end: int) -> tuple[int, int] | None:
    """去掉区间两端的空白；全是空白的区间不是段落。"""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return None if end <= start else (start, end)
