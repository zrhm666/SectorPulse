"""Deterministic document fixtures for the parsing tests.

The PDFs are generated here rather than committed as binaries. A checked-in PDF cannot be
read in a diff, cannot be edited when the assertion changes, and carries whatever licence
it was downloaded under into this repository. Generating one keeps the text that the test
asserts on visible in the test that asserts it — and makes a "scanned page" a structural
fact (a page with an image and no text layer) instead of an opaque blob.

CJK text is inserted with PyMuPDF's built-in `china-s` font, which round-trips through
`get_text()` correctly. Note that printing it to a Windows console can look like mojibake
while the extraction is in fact correct — the console's code page, not the document, is
what mangles it; compare codepoints rather than trusting the terminal.
"""

import pymupdf
from sector_pulse.ports.research_models import (
    OcrPage,
    OcrWord,
    ParseLimits,
    ParseSource,
)

PDF_MEDIA_TYPE = "application/pdf"
MARKDOWN_MEDIA_TYPE = "text/markdown"
TEXT_MEDIA_TYPE = "text/plain"

CJK_FONT = "china-s"

PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0

BODY_FONT_SIZE = 10.0
HEADING_FONT_SIZE = 16.0

HEADING_TEXT = "第三章 行业跟踪"
SUBHEADING_TEXT = "3.2 海外需求"
BODY_TEXT = "海外储能订单在 2026 年第二季度明显增长，二季度新增订单同比翻倍。"
SECOND_BODY_TEXT = "碳酸锂价格在同期明显回落。"

HEADER_TEXT = "SectorPulse 研究部"
FOOTER_TEXT = "机密 · 仅供内部使用"

OCR_PAGE_TEXT = "第二章 产能投放"
OCR_BODY_TEXT = "报告期内新增产线六条，产能利用率环比提升。"

FIXTURE_OCR_PROVIDER = "fixture-ocr"
FIXTURE_OCR_MODEL = "fixture-ocr-v1"


def _write_line(
    page: pymupdf.Page,
    *,
    x: float,
    y: float,
    text: str,
    size: float = BODY_FONT_SIZE,
) -> None:
    page.insert_text((x, y), text, fontname=CJK_FONT, fontsize=size)


def native_pdf_bytes(
    *,
    pages: int = 1,
    header: str | None = None,
    footer: str | None = None,
) -> bytes:
    """A PDF whose text layer is real, so nothing should reach for OCR."""
    document = pymupdf.open()
    for index in range(pages):
        page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        if header is not None:
            _write_line(page, x=72, y=40, text=header)
        _write_line(
            page,
            x=72,
            y=100,
            text=HEADING_TEXT if index == 0 else f"{HEADING_TEXT}（续 {index + 1}）",
            size=HEADING_FONT_SIZE,
        )
        _write_line(page, x=72, y=140, text=BODY_TEXT)
        # 14pt apart for 10pt type: one paragraph, not two. Two blocks here would make the
        # layout rules untestable through the fixture.
        _write_line(page, x=72, y=154, text=f"{SECOND_BODY_TEXT}（第 {index + 1} 页）")
        if footer is not None:
            _write_line(page, x=72, y=800, text=footer)
    payload = document.tobytes()
    document.close()
    return payload


def partial_scan_pdf_bytes() -> bytes:
    """Page 1 has a text layer; page 2 is a scan, so only page 2 may reach OCR.

    Page 2 carries the *rendered* page 1 as an image. That is what a scanned appendix
    looks like to a parser: pixels and no characters.
    """
    document = pymupdf.open()
    native = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    _write_line(native, x=72, y=100, text=HEADING_TEXT, size=HEADING_FONT_SIZE)
    _write_line(native, x=72, y=140, text=BODY_TEXT)
    pixmap = native.get_pixmap(dpi=72)

    scanned = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    scanned.insert_image(pymupdf.Rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT), pixmap=pixmap)

    payload = document.tobytes()
    document.close()
    return payload


def repeated_header_pdf_bytes(*, pages: int = 3) -> bytes:
    """Every page repeats a header and a footer; only the body differs."""
    return native_pdf_bytes(pages=pages, header=HEADER_TEXT, footer=FOOTER_TEXT)


def encrypted_pdf_bytes(*, password: str = "s3cret") -> bytes:
    document = pymupdf.open()
    page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    _write_line(page, x=72, y=100, text=BODY_TEXT)
    payload = document.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw=password,
        user_pw=password,
    )
    document.close()
    return payload


def not_a_pdf_bytes() -> bytes:
    return b"%PDF-1.7\nthis file is truncated on purpose\n"


def source(
    payload: bytes,
    *,
    media_type: str = PDF_MEDIA_TYPE,
    filename: str | None = "report.pdf",
) -> ParseSource:
    return ParseSource(media_type=media_type, content=payload, filename=filename)


def scanned_source() -> ParseSource:
    return source(partial_scan_pdf_bytes(), filename="partial-scan.pdf")


def native_source(**kwargs: object) -> ParseSource:
    return source(native_pdf_bytes(**kwargs))  # type: ignore[arg-type]


def default_limits(**overrides: object) -> ParseLimits:
    limits: dict[str, object] = {"max_bytes": 32 * 1024 * 1024, "max_pages": 200, **overrides}
    return ParseLimits(**limits)  # type: ignore[arg-type]


class FakeOcrProvider:
    """Deterministic OCR: returns fixed words per page and records what it was asked.

    A real provider is a paid, non-deterministic network call. The parser's job is to
    decide *which* pages need OCR and how to fold the answer back in, and that decision is
    exactly what this records.
    """

    def __init__(
        self,
        *,
        pages: dict[int, str] | None = None,
        provider: str = FIXTURE_OCR_PROVIDER,
        model_version: str = FIXTURE_OCR_MODEL,
        confidence: float = 0.93,
    ) -> None:
        self._pages = pages if pages is not None else {2: f"{OCR_PAGE_TEXT}\n{OCR_BODY_TEXT}"}
        self._provider = provider
        self._model_version = model_version
        self._confidence = confidence
        self.requested_pages: list[int] = []
        self.image_sizes: list[int] = []

    def recognize_page(
        self, *, page_number: int, page_image: bytes, width: int, height: int
    ) -> OcrPage:
        self.requested_pages.append(page_number)
        self.image_sizes.append(len(page_image))
        text = self._pages.get(page_number, "")
        return OcrPage(
            page_number=page_number,
            provider=self._provider,
            model_version=self._model_version,
            confidence=self._confidence,
            words=tuple(
                OcrWord(
                    text=line,
                    bounding_box=(72.0, 100.0 + 20.0 * index, 500.0, 118.0 + 20.0 * index),
                    confidence=self._confidence,
                )
                for index, line in enumerate(text.splitlines())
                if line.strip()
            ),
        )


class UnavailableOcrProvider:
    """A provider that must never be called; used to prove no page reaches it."""

    def recognize_page(
        self, *, page_number: int, page_image: bytes, width: int, height: int
    ) -> OcrPage:
        raise AssertionError(f"OCR must not be called for page {page_number}")
