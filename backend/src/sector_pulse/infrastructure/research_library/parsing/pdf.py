"""PDF 解析：原生文本优先，OCR 只补它读不到的那些页。

规格 7.3/7.4 把两件事分开：提取负责拿到字符、字体和坐标，版面规则（`layout`）负责把
它们变成块。这个类只做编排——什么时候该付一次 OCR、哪一页读不到时还继续读下一页、
以及把 provider 与模型版本记进结果。

安全上只做减法：不执行 JavaScript，不打开嵌入附件，不跟随外部链接，遇到加密直接报
“需要密码”（规格 18.1）。PyMuPDF 默认就不做这些，但“默认不做”和“我们选择不做”在
代码评审里不是同一件事，所以这里显式传参、显式拒绝。

一个刻意的取舍：文档在整个解析期间保持打开。OCR 需要把页面渲染成图片，而渲染必须在
判断出“这一页要不要 OCR”之后才能做——那个判断依赖跨页的页眉页脚分析。先关闭再重开
会让这一段多出一次解析整份文档的开销。
"""

from dataclasses import dataclass
from typing import Any

import pymupdf

from sector_pulse.domain.research_library.models import (
    BlockType,
    BoundingBox,
    DocumentBlock,
    ExtractionMethod,
)
from sector_pulse.infrastructure.research_library.parsing.layout import (
    ExtractedPage,
    ExtractedSpan,
    LayoutBlock,
    LayoutPolicy,
    PageQualityPolicy,
    assess_page_quality,
    group_spans_into_blocks,
    remove_repeated_margins,
)
from sector_pulse.ports.research_models import (
    DEFAULT_PARSE_LIMITS,
    DocumentTooLarge,
    OcrPage,
    OcrProvider,
    ParsedDocument,
    ParseLimits,
    ParseSource,
    PasswordProtectedDocument,
    TooManyPages,
    UnreadableDocument,
)

PARSER_NAME = "pdf"
PARSER_VERSION = "pdf-native-v1"

PDF_MEDIA_TYPE = "application/pdf"

#: 渲染页面交给 OCR 的分辨率。过高只是浪费带宽与费用，过低会把正文糊成噪声。
OCR_RENDER_DPI = 200

#: 只取文本层。图片字节另走 Task 6 的区域资产路径，解析阶段不把它们读进内存。
TEXT_FLAGS = pymupdf.TEXTFLAGS_TEXT

#: 与流水线共用同一份上限：单独使用这个解析器时也不会得到一套不同的规矩。
DEFAULT_LIMITS = DEFAULT_PARSE_LIMITS


@dataclass(frozen=True)
class _Draft:
    """一个待编号的块，连同它是怎么来的。

    定义在解析器之前：注解在类体执行时求值，放到后面会让导入直接抛 NameError。
    """

    layout: LayoutBlock
    method: ExtractionMethod


class PdfDocumentParser:
    """`DocumentParser` 的 PDF 实现。"""

    name = PARSER_NAME
    media_types = frozenset({PDF_MEDIA_TYPE})

    def __init__(
        self,
        *,
        ocr: OcrProvider | None = None,
        limits: ParseLimits | None = None,
        layout: LayoutPolicy | None = None,
        page_quality: PageQualityPolicy | None = None,
    ) -> None:
        self._ocr = ocr
        self._limits = limits or DEFAULT_LIMITS
        self._layout = layout or LayoutPolicy()
        self._page_quality = page_quality or PageQualityPolicy()

    def parse(self, source: ParseSource) -> ParsedDocument:
        if source.byte_size > self._limits.max_bytes:
            raise DocumentTooLarge(
                f"{source.decoded_hint()} exceeds the {self._limits.max_bytes} byte limit"
            )

        document = self._open(source)
        try:
            if document.page_count > self._limits.max_pages:
                raise TooManyPages(
                    f"{document.page_count} pages exceeds the {self._limits.max_pages} page limit"
                )
            pages = tuple(_extract_page(document, index) for index in range(document.page_count))
            pages = remove_repeated_margins(pages, self._layout)
            drafts, warnings, attribution = self._build_blocks(document, pages)
        finally:
            document.close()

        blocks = _assemble(drafts)

        return ParsedDocument(
            blocks=blocks,
            page_count=len(pages),
            parser_name=PARSER_NAME,
            parser_version=PARSER_VERSION,
            ocr_provider=attribution[0],
            ocr_model_version=attribution[1],
            warnings=warnings,
        )

    # --- 内部 ---

    def _build_blocks(
        self, document: Any, pages: tuple[ExtractedPage, ...]
    ) -> tuple[list[_Draft], tuple[str, ...], tuple[str | None, str | None]]:
        drafts: list[_Draft] = []
        warnings: list[str] = []
        providers: set[str] = set()
        models: set[str] = set()

        for page in pages:
            quality = assess_page_quality(page, self._page_quality)
            if not quality.needs_ocr:
                drafts.extend(
                    _Draft(layout=block, method=ExtractionMethod.NATIVE)
                    for block in group_spans_into_blocks(page, self._layout)
                )
                continue

            if self._ocr is None:
                warnings.append(
                    f"page {page.page_number} needs OCR ({quality.reason}) but no OCR provider "
                    "is configured; its content is missing from this parse"
                )
                continue

            blocks, provider, model = self._read_with_ocr(document, page)
            if not blocks:
                warnings.append(
                    f"page {page.page_number} needs OCR ({quality.reason}) but the OCR provider "
                    "returned no text; its content is missing from this parse"
                )
                continue
            providers.add(provider)
            models.add(model)
            drafts.extend(_Draft(layout=block, method=ExtractionMethod.OCR) for block in blocks)

        attribution = (
            (sorted(providers)[0], sorted(models)[0]) if len(providers) == 1 else (None, None)
        )
        if len(providers) > 1:
            warnings.append(
                "this document was read by more than one OCR provider "
                f"({', '.join(sorted(providers))}); the version is not attributed to a single one"
            )
        return drafts, tuple(warnings), attribution

    def _open(self, source: ParseSource) -> Any:
        try:
            # PyMuPDF 没有类型标注。经由一个 Any 别名调用，未标注调用就止步于此，
            # 不必写一个上游发版后就会失效的 `type: ignore`（`warn_unused_ignores`
            # 会把它变成错误）。
            opener: Any = pymupdf.open
            document = opener(stream=source.content, filetype="pdf")
        except Exception as error:  # PyMuPDF 对损坏输入抛出多种异常类型
            raise UnreadableDocument(
                f"{source.decoded_hint()} could not be opened as a PDF: {error}"
            ) from error

        if document.needs_pass:
            document.close()
            # 规格 18.1：告知需要密码，不尝试破解——猜密码既不可靠，也会把一次失败的
            # 上传变成一串昂贵的尝试。
            raise PasswordProtectedDocument(
                f"{source.decoded_hint()} is encrypted and requires a password"
            )
        return document

    def _read_with_ocr(
        self, document: Any, page: ExtractedPage
    ) -> tuple[tuple[LayoutBlock, ...], str, str]:
        assert self._ocr is not None  # 调用点已经判过
        image, width, height = _render_page(document, page.page_number)
        ocr_page = self._ocr.recognize_page(
            page_number=page.page_number, page_image=image, width=width, height=height
        )
        # OCR 的词交给同一套版面规则：行距、合并与标题判定对扫描页和原生页应当一致，
        # 否则同一份文档的两类页面会产出不同粒度的块。
        rendered = page.model_copy(
            update={"spans": _spans_from_ocr(ocr_page), "image_area_ratio": 0.0}
        )
        blocks = tuple(
            block.model_copy(update={"confidence": ocr_page.confidence})
            for block in group_spans_into_blocks(rendered, self._layout)
        )
        return blocks, ocr_page.provider, ocr_page.model_version


def _assemble(drafts: list[_Draft]) -> tuple[DocumentBlock, ...]:
    """编号、建立章节路径、产出最终块序列。

    层级只在构建期存在：规格 7.5 的 `DocumentBlock` 字段表里没有标题层级，而章节路径
    必须有它，因此在这里一次算完，不把它塞进模型或模块级状态。
    """
    stack: list[tuple[int, str]] = []
    blocks: list[DocumentBlock] = []

    for order, draft in enumerate(drafts):
        block = draft.layout
        if block.block_type is BlockType.HEADING:
            level = block.heading_level or 1
            stack = [entry for entry in stack if entry[0] < level]
            stack.append((level, block.text))

        blocks.append(
            DocumentBlock(
                block_id=f"blk_{order:05d}",
                block_type=block.block_type,
                text=block.text,
                heading_path=tuple(text for _, text in stack),
                page_number=block.page_number,
                block_order=order,
                bounding_box=block.bounding_box,
                extraction_method=draft.method,
                extraction_confidence=block.confidence,
            )
        )
    return tuple(blocks)


def _extract_page(document: Any, index: int) -> ExtractedPage:
    page = document[index]
    raw = page.get_text("dict", flags=TEXT_FLAGS)
    spans = tuple(
        ExtractedSpan(
            text=span["text"],
            bounding_box=_box(span["bbox"]),
            font=str(span.get("font", "")),
            # 字号 0 在真实 PDF 里存在（缩放写在变换矩阵里），按 1 处理以免除零。
            font_size=float(span.get("size") or 1.0),
        )
        for block in raw.get("blocks", ())
        if block.get("type") == 0
        for line in block.get("lines", ())
        for span in line.get("spans", ())
        if span.get("text", "").strip()
    )
    rectangle = page.rect
    return ExtractedPage(
        page_number=index + 1,
        width=float(rectangle.width) or 1.0,
        height=float(rectangle.height) or 1.0,
        spans=spans,
        image_area_ratio=_image_area_ratio(page),
    )


def _render_page(document: Any, page_number: int) -> tuple[bytes, int, int]:
    pixmap = document[page_number - 1].get_pixmap(dpi=OCR_RENDER_DPI)
    return pixmap.tobytes("png"), int(pixmap.width), int(pixmap.height)


def _spans_from_ocr(ocr_page: OcrPage) -> tuple[ExtractedSpan, ...]:
    return tuple(
        ExtractedSpan(
            text=word.text,
            bounding_box=word.bounding_box,
            font="ocr",
            # OCR 只给坐标，不给字号；用行高当字号，版面规则就能照常算行距。
            font_size=max(1.0, word.bounding_box[3] - word.bounding_box[1]),
        )
        for word in ocr_page.words
    )


def _box(raw: Any) -> BoundingBox:
    left, top, right, bottom = (float(value) for value in raw)
    return (left, top, right, bottom)


def _image_area_ratio(page: Any) -> float:
    """图片覆盖的页面比例。扫描页往往是“一张几乎铺满的图 + 一个页码”。

    只看字符数会把这类页面判成正常页：它确实有两个字符。
    """
    try:
        images = page.get_image_info()
    except Exception:  # pragma: no cover - 取决于 PyMuPDF 版本
        return 0.0
    area = float(page.rect.width) * float(page.rect.height)
    if area <= 0:
        return 0.0
    covered = 0.0
    for image in images:
        box = _box(image["bbox"])
        covered += max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])
    return min(1.0, covered / area)
