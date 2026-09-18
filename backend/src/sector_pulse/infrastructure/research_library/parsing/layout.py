"""版面规则：从字符到块，以及判断一页到底读到没有。

这一层刻意不认识 PyMuPDF，也不认识配置：它拿到的是一页页的字符与坐标，产出的是块。
把“什么叫一页没读到”“什么算页眉页脚”做成纯函数，是因为它们是这套解析里最容易被
悄悄放宽的两条规矩——一旦放宽，扫描件会被当成空文件，页眉会被当成正文反复入库。

三条规则值得单独说明：

1. **页眉页脚靠“重复 + 位置”判定，两个条件都要满足。** 只按重复判定会吃掉正文里
   重复出现的免责声明；只按位置判定会吃掉首页顶端的标题。
2. **少于三页不做重复判定。** 两页上出现同一行不足以说明它是装饰，而误删标题的代价
   比留下一个页眉高得多。
3. **`NOT_SCANNED` 不是 `CLEAN`。** 一页没有可用文本层就是“没人读过这一页”，
   这件事必须作为结论往外传，而不是表达成“这一页没有内容”。
"""

from pydantic import Field, model_validator

from sector_pulse.domain.research_library.models import BlockType, BoundingBox, Record

#: 判定乱码用的替换字符。解码失败、字体缺字、复制保护都会产生它。
REPLACEMENT_CHARACTER = "�"

#: 中日韩字符与全角标点的范围。用于判断换行处该不该补一个空格。
_CJK_RANGES = (
    (0x2E80, 0x303F),
    (0x3040, 0x30FF),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0xFF00, 0xFF60),
    (0xFFE0, 0xFFE6),
    (0x20000, 0x2FA1F),
)


def is_cjk(character: str) -> bool:
    codepoint = ord(character)
    return any(low <= codepoint <= high for low, high in _CJK_RANGES)


def join_wrapped_lines(lines: list[str]) -> str:
    """把同一段里被硬换行拆开的行接回去。

    分隔符在拼接处决定，而不是先统一补空格再全局清理：后者无法区分“换行造成的空格”
    和“作者本来打的空格”，会把 `碳酸锂 价格` 里的空格也删掉。
    """
    joined = ""
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if not joined:
            joined = stripped
            continue
        if is_cjk(joined[-1]) and is_cjk(stripped[0]):
            joined += stripped
        else:
            joined += " " + stripped
    return joined


class ExtractedSpan(Record):
    """一个字符片段及其版面信息。字体名与字号是标题判定的依据。"""

    text: str = Field(min_length=1)
    bounding_box: BoundingBox
    font: str = ""
    font_size: float = Field(gt=0)

    @property
    def vertical_center(self) -> float:
        return (self.bounding_box[1] + self.bounding_box[3]) / 2

    @property
    def is_blank(self) -> bool:
        return not self.text.strip()


class ExtractedPage(Record):
    """一页的原始提取结果。

    `image_area_ratio` 是图片覆盖的页面比例：一整页扫描件往往带一两个字符（页码、
    水印），字符数不为零，但这一页的内容确实在图片里。
    """

    page_number: int = Field(ge=1)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    spans: tuple[ExtractedSpan, ...] = ()
    image_area_ratio: float = Field(default=0.0, ge=0, le=1)

    @property
    def text(self) -> str:
        return join_wrapped_lines([span.text for span in self.spans])


class LayoutPolicy(Record):
    #: 页眉/页脚所在的上下边缘比例。
    margin_ratio: float = Field(default=0.08, gt=0, lt=0.5)
    #: 一行要在多大比例的页面上出现才算装饰。
    repeated_line_ratio: float = Field(default=0.6, gt=0.5, le=1)
    #: 少于这么多页就不做重复判定。
    min_pages_for_margin_analysis: int = Field(default=3, ge=2)
    #: 行距超过字号这么多倍就被视为新的一段。
    line_gap_factor: float = Field(default=1.5, gt=0)
    #: 字号超过正文这么多倍才算标题。
    heading_size_factor: float = Field(default=1.15, gt=1)


class PageQualityPolicy(Record):
    """什么情况下值得为这一页付一次 OCR。"""

    min_native_characters: int = Field(default=40, ge=0)
    max_garbled_ratio: float = Field(default=0.3, ge=0, le=1)
    #: 图片覆盖超过这个比例时，即使有零星字符也按扫描页处理。
    min_image_area_ratio: float = Field(default=0.5, gt=0, le=1)


class PageQuality(Record):
    needs_ocr: bool
    reason: str = ""
    usable_characters: int = Field(ge=0)
    garbled_ratio: float = Field(ge=0, le=1)


class LayoutBlock(Record):
    """块级结构，但还没有文档级身份（block_id、block_order、章节路径）。"""

    block_type: BlockType
    text: str
    bounding_box: BoundingBox
    page_number: int = Field(ge=1)
    heading_level: int | None = Field(default=None, ge=1, le=6)
    confidence: float = Field(default=1.0, ge=0, le=1)
    font_size: float = Field(gt=0)

    @model_validator(mode="after")
    def _a_heading_names_its_level(self) -> "LayoutBlock":
        if (self.block_type is BlockType.HEADING) != (self.heading_level is not None):
            raise ValueError("only a heading carries a heading_level")
        return self


def _union(boxes: list[BoundingBox]) -> BoundingBox:
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def garbled_ratio(text: str) -> float:
    """不可用字符占非空白字符的比例。"""
    meaningful = [character for character in text if not character.isspace()]
    if not meaningful:
        return 0.0
    broken = sum(1 for character in meaningful if character == REPLACEMENT_CHARACTER)
    return broken / len(meaningful)


def assess_page_quality(page: ExtractedPage, policy: PageQualityPolicy) -> PageQuality:
    """判断这一页是否需要用 OCR 重读。顺序即优先级，先命中的理由优先报出。"""
    content = [span for span in page.spans if not span.is_blank]
    text = join_wrapped_lines([span.text for span in content])
    characters = sum(1 for character in text if not character.isspace())
    ratio = garbled_ratio(text)

    def verdict(needs_ocr: bool, reason: str) -> PageQuality:
        return PageQuality(
            needs_ocr=needs_ocr,
            reason=reason,
            usable_characters=characters,
            garbled_ratio=ratio,
        )

    if not content:
        return verdict(True, "the page has no text layer")
    if page.image_area_ratio >= policy.min_image_area_ratio:
        return verdict(
            True,
            f"images cover {page.image_area_ratio:.0%} of the page; it is a scan",
        )
    if characters < policy.min_native_characters:
        return verdict(
            True,
            f"the page yielded {characters} characters, below the "
            f"{policy.min_native_characters} needed to trust it",
        )
    if ratio > policy.max_garbled_ratio:
        return verdict(
            True,
            f"{ratio:.0%} of the page is garbled text, above the "
            f"{policy.max_garbled_ratio:.0%} limit",
        )
    return verdict(False, "")


def _in_margin(span: ExtractedSpan, page: ExtractedPage, policy: LayoutPolicy) -> bool:
    band = page.height * policy.margin_ratio
    center = span.vertical_center
    return center <= band or center >= page.height - band


def _normalised(text: str) -> str:
    return " ".join(text.split())


def remove_repeated_margins(
    pages: tuple[ExtractedPage, ...], policy: LayoutPolicy
) -> tuple[ExtractedPage, ...]:
    """删掉在多页边缘重复出现的行。

    重排后的页码、章节名和免责声明属于版面装饰，不属于正文：把它们留在块里，索引会把
    同一个句子在每一页重复计一次，检索时会挤掉真正的内容。
    """
    if len(pages) < policy.min_pages_for_margin_analysis:
        return pages

    occurrences: dict[str, int] = {}
    for page in pages:
        for line in {_normalised(span.text) for span in page.spans if not span.is_blank}:
            occurrences[line] = occurrences.get(line, 0) + 1

    threshold = policy.repeated_line_ratio * len(pages)
    repeated = {line for line, count in occurrences.items() if count >= threshold}
    if not repeated:
        return pages

    return tuple(
        page.model_copy(
            update={
                "spans": tuple(
                    span
                    for span in page.spans
                    if _normalised(span.text) not in repeated or not _in_margin(span, page, policy)
                )
            }
        )
        for page in pages
    )


def body_font_size(spans: tuple[ExtractedSpan, ...]) -> float:
    """正文的字号：按字符数加权的众数，而不是简单平均。

    标题少、正文多，平均值会被标题拉高，于是标题自己就不再“显著大于正文”了。
    """
    weights: dict[float, int] = {}
    for span in spans:
        if span.is_blank:
            continue
        key = round(span.font_size, 1)
        weights[key] = weights.get(key, 0) + len(span.text.strip())
    if not weights:
        return 0.0
    return max(weights.items(), key=lambda item: (item[1], -item[0]))[0]


def heading_level(font_size: float, body_size: float, policy: LayoutPolicy) -> int | None:
    if body_size <= 0:
        return None
    ratio = font_size / body_size
    if ratio < policy.heading_size_factor:
        return None
    if ratio >= 1.6:
        return 1
    if ratio >= 1.3:
        return 2
    return 3


def group_spans_into_blocks(page: ExtractedPage, policy: LayoutPolicy) -> tuple[LayoutBlock, ...]:
    """按阅读顺序把行合成块。

    先按纵向位置排序（阅读顺序），再把行距接近的行并入同一块。标题独立成块：它自己不
    是正文，而且后面每个块的章节路径都要引用它。
    """
    lines = sorted(
        (span for span in page.spans if not span.is_blank),
        key=lambda span: (round(span.vertical_center, 1), span.bounding_box[0]),
    )
    if not lines:
        return ()

    body_size = body_font_size(tuple(lines))
    blocks: list[LayoutBlock] = []
    group: list[ExtractedSpan] = []

    def flush() -> None:
        if not group:
            return
        blocks.append(
            LayoutBlock(
                block_type=BlockType.PARAGRAPH,
                text=join_wrapped_lines([span.text for span in group]),
                bounding_box=_union([span.bounding_box for span in group]),
                page_number=page.page_number,
                font_size=body_size or group[0].font_size,
            )
        )
        group.clear()

    for span in lines:
        level = heading_level(span.font_size, body_size, policy)
        if level is not None:
            # 标题自成一块，也切断上一段：段落的边界就是标题所在的位置。
            flush()
            blocks.append(
                LayoutBlock(
                    block_type=BlockType.HEADING,
                    text=span.text.strip(),
                    bounding_box=span.bounding_box,
                    page_number=page.page_number,
                    heading_level=level,
                    font_size=span.font_size,
                )
            )
            continue
        if group:
            previous = group[-1]
            gap = span.bounding_box[1] - previous.bounding_box[3]
            if gap > policy.line_gap_factor * max(previous.font_size, span.font_size):
                flush()
        group.append(span)
    flush()
    return tuple(blocks)
