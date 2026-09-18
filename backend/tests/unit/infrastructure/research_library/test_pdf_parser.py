"""PDF extraction: what the text layer gives, and what happens when it gives nothing.

The two claims worth holding this parser to are both about restraint. It must not call OCR
on a page that already has usable text — that is a paid, non-deterministic network call
whose result would silently replace the authoritative text layer. And it must not pretend
a page it could not read is empty: a scanned page with no OCR configured is a page nobody
has read, which belongs in `warnings`, not in a document that looks complete.
"""

import pytest
from sector_pulse.domain.research_library.models import (
    BlockType,
    DocumentBlock,
    ExtractionMethod,
)
from sector_pulse.infrastructure.research_library.parsing.layout import (
    ExtractedPage,
    ExtractedSpan,
    LayoutPolicy,
    PageQualityPolicy,
    assess_page_quality,
    group_spans_into_blocks,
    remove_repeated_margins,
)
from sector_pulse.infrastructure.research_library.parsing.pdf import PdfDocumentParser
from sector_pulse.ports.research_models import (
    DocumentTooLarge,
    PasswordProtectedDocument,
    TooManyPages,
    UnreadableDocument,
)

from backend.tests.research_library_parsing_support import (
    BODY_TEXT,
    FIXTURE_OCR_MODEL,
    FIXTURE_OCR_PROVIDER,
    FOOTER_TEXT,
    HEADER_TEXT,
    HEADING_TEXT,
    FakeOcrProvider,
    UnavailableOcrProvider,
    default_limits,
    encrypted_pdf_bytes,
    native_source,
    not_a_pdf_bytes,
    repeated_header_pdf_bytes,
    scanned_source,
    source,
)


@pytest.fixture
def parser() -> PdfDocumentParser:
    return PdfDocumentParser()


def block_containing(blocks: tuple[DocumentBlock, ...], needle: str) -> DocumentBlock:
    for block in blocks:
        if needle in block.text:
            return block
    raise AssertionError(f"no block contains {needle!r}")


def test_native_pdf_keeps_page_text_in_blocks(parser: PdfDocumentParser) -> None:
    parsed = parser.parse(native_source())
    page_blocks = parsed.blocks_for_page(1)

    assert page_blocks
    assert all(block.extraction_method is ExtractionMethod.NATIVE for block in page_blocks)
    assert any(HEADING_TEXT in block.text for block in page_blocks)
    assert any(BODY_TEXT in block.text for block in page_blocks)
    assert parsed.page_count == 1
    assert parsed.parser_name == "pdf"


def test_native_blocks_carry_the_geometry_a_citation_needs(parser: PdfDocumentParser) -> None:
    """A block that cannot be pointed back to a rectangle cannot be checked by a human."""
    parsed = parser.parse(native_source())
    block = block_containing(parsed.blocks, HEADING_TEXT)

    assert block.page_number == 1
    assert block.bounding_box is not None
    left, top, right, bottom = block.bounding_box
    assert 0 <= left < right <= 595.0
    assert 0 <= top < bottom <= 842.0
    assert block.block_order >= 0
    assert block.block_id


def test_the_larger_line_becomes_a_heading_and_sets_the_section_path(
    parser: PdfDocumentParser,
) -> None:
    parsed = parser.parse(native_source())
    headings = [b for b in parsed.blocks if b.block_type is BlockType.HEADING]
    assert [b.text for b in headings] == [HEADING_TEXT]
    assert headings[0].heading_path == (HEADING_TEXT,)

    paragraphs = [b for b in parsed.blocks if b.block_type is BlockType.PARAGRAPH]
    assert paragraphs
    assert all(b.heading_path == (HEADING_TEXT,) for b in paragraphs)


def test_block_order_is_document_wide(parser: PdfDocumentParser) -> None:
    """Order has to survive page boundaries or chunking cannot reassemble a section."""
    parsed = parser.parse(native_source(pages=3))
    orders = [block.block_order for block in parsed.blocks]
    assert orders == sorted(orders)
    assert len(set(orders)) == len(orders)
    assert set(orders) == set(range(len(orders)))


def test_ocr_runs_only_for_the_page_that_has_no_text_layer() -> None:
    ocr = FakeOcrProvider()
    parser = PdfDocumentParser(ocr=ocr)

    parsed = parser.parse(scanned_source())

    assert ocr.requested_pages == [2]
    assert all(
        block.extraction_method is ExtractionMethod.NATIVE
        for block in parsed.blocks_for_page(1)
    )
    ocr_blocks = parsed.blocks_for_page(2)
    assert ocr_blocks
    assert all(block.extraction_method is ExtractionMethod.OCR for block in ocr_blocks)
    assert parsed.ocr_provider == FIXTURE_OCR_PROVIDER
    assert parsed.ocr_model_version == FIXTURE_OCR_MODEL


def test_ocr_blocks_keep_the_provider_confidence_and_geometry() -> None:
    ocr = FakeOcrProvider(confidence=0.61)
    parser = PdfDocumentParser(ocr=ocr)
    parsed = parser.parse(scanned_source())

    block = parsed.blocks_for_page(2)[0]
    assert block.extraction_confidence == pytest.approx(0.61)
    assert block.bounding_box is not None


def test_a_page_with_a_text_layer_never_reaches_ocr() -> None:
    """The expensive path must stay closed when nothing is wrong with the page."""
    parser = PdfDocumentParser(ocr=UnavailableOcrProvider())
    parsed = parser.parse(native_source(pages=2))
    assert parsed.blocks_for_page(2)


def test_a_scanned_page_without_ocr_is_reported_rather_than_left_empty(
    parser: PdfDocumentParser,
) -> None:
    parsed = parser.parse(scanned_source())

    assert parsed.blocks_for_page(2) == ()
    assert any("2" in warning for warning in parsed.warnings)
    assert parsed.ocr_provider is None
    # Page 1 must still be usable: one unreadable page does not forfeit the document.
    assert parsed.blocks_for_page(1)


def test_an_ocr_provider_that_returns_nothing_is_not_a_crash() -> None:
    parser = PdfDocumentParser(ocr=FakeOcrProvider(pages={}))
    parsed = parser.parse(scanned_source())
    assert parsed.blocks_for_page(1)
    assert parsed.blocks_for_page(2) == ()


def test_repeated_headers_and_footers_are_removed(parser: PdfDocumentParser) -> None:
    parsed = parser.parse(source(repeated_header_pdf_bytes(pages=3)))
    texts = [block.text for block in parsed.blocks]
    assert texts
    assert not any(HEADER_TEXT in text for text in texts)
    assert not any(FOOTER_TEXT in text for text in texts)
    # The bodies differ per page and must all survive.
    assert sum(1 for text in texts if "第 1 页" in text) == 1
    assert sum(1 for text in texts if "第 3 页" in text) == 1


def test_an_encrypted_pdf_asks_for_a_password_instead_of_being_cracked(
    parser: PdfDocumentParser,
) -> None:
    with pytest.raises(PasswordProtectedDocument):
        parser.parse(source(encrypted_pdf_bytes()))


def test_a_page_limit_is_enforced(parser: PdfDocumentParser) -> None:
    payload = native_source(pages=4)
    parser.parse(payload)  # four pages are fine under the default limit

    with pytest.raises(TooManyPages):
        PdfDocumentParser(limits=default_limits(max_pages=3)).parse(payload)


def test_a_size_limit_is_enforced(parser: PdfDocumentParser) -> None:
    with pytest.raises(DocumentTooLarge):
        PdfDocumentParser(limits=default_limits(max_bytes=64)).parse(native_source())


def test_a_truncated_pdf_is_reported_as_unreadable(parser: PdfDocumentParser) -> None:
    with pytest.raises(UnreadableDocument):
        parser.parse(source(not_a_pdf_bytes()))


def test_pdf_blocks_locate_themselves_by_page_and_rectangle_not_by_index(
    parser: PdfDocumentParser,
) -> None:
    """The two locator mechanisms are kept apart: a PDF has coordinates, so it must not
    also claim a text range that nothing computed."""
    parsed = parser.parse(native_source())
    assert all(block.source_span is None for block in parsed.blocks)
    assert all(block.bounding_box is not None for block in parsed.blocks)


# --- the layout rules, tested directly, without a PDF in the way ---


def span(text: str, *, top: float, size: float = 10.0) -> ExtractedSpan:
    return ExtractedSpan(
        text=text,
        bounding_box=(72.0, top, 500.0, top + size),
        font="Heiti",
        font_size=size,
    )


def page(
    number: int, spans: tuple[ExtractedSpan, ...], *, image_area_ratio: float = 0.0
) -> ExtractedPage:
    return ExtractedPage(
        page_number=number,
        width=595.0,
        height=842.0,
        spans=spans,
        image_area_ratio=image_area_ratio,
    )


def test_quality_flags_a_page_with_no_text_layer() -> None:
    verdict = assess_page_quality(page(1, ()), PageQualityPolicy())
    assert verdict.needs_ocr is True
    assert "no text layer" in verdict.reason


def test_quality_flags_a_page_that_is_mostly_a_scan() -> None:
    """A stray page number over a full-page scan is still a scan."""
    thin = page(1, (span("12", top=800.0),), image_area_ratio=0.85)
    verdict = assess_page_quality(thin, PageQualityPolicy())
    assert verdict.needs_ocr is True
    assert "image" in verdict.reason


def test_quality_flags_a_page_below_the_character_floor() -> None:
    thin = page(1, (span("12", top=800.0),))
    verdict = assess_page_quality(thin, PageQualityPolicy())
    assert verdict.needs_ocr is True
    assert "characters" in verdict.reason


def test_quality_flags_a_page_of_replacement_characters() -> None:
    garbled = page(1, (span("�" * 200, top=100.0),))
    verdict = assess_page_quality(garbled, PageQualityPolicy())
    assert verdict.needs_ocr is True
    assert "garbled" in verdict.reason


def test_a_healthy_page_is_not_flagged() -> None:
    healthy = page(1, (span(BODY_TEXT * 3, top=100.0),))
    verdict = assess_page_quality(healthy, PageQualityPolicy())
    assert verdict.needs_ocr is False
    assert verdict.reason == ""


def test_the_quality_floor_is_configurable() -> None:
    """A page under the default floor must clear a lowered one — otherwise the setting
    does nothing and the test would pass for the wrong reason."""
    short = page(1, (span("碳酸锂价格明显回落，电芯成本压力缓解。", top=300.0),))
    assert assess_page_quality(short, PageQualityPolicy()).needs_ocr is True
    lenient = PageQualityPolicy(min_native_characters=10)
    assert assess_page_quality(short, lenient).needs_ocr is False


def test_repeated_margins_are_dropped_and_unique_body_lines_are_kept() -> None:
    pages = tuple(
        page(
            number,
            (
                span(HEADER_TEXT, top=30.0),
                span(f"正文第 {number} 段的内容足够长，可以被当成正文。", top=300.0),
                span(FOOTER_TEXT, top=810.0),
            ),
        )
        for number in (1, 2, 3)
    )
    cleaned = remove_repeated_margins(pages, LayoutPolicy())
    texts = [s.text for p in cleaned for s in p.spans]
    assert HEADER_TEXT not in texts
    assert FOOTER_TEXT not in texts
    assert sum(1 for t in texts if "第 1 段" in t) == 1


def test_a_line_that_repeats_but_sits_in_the_body_is_kept() -> None:
    """Only the margins are suspect; a repeated body line is content, not furniture."""
    repeated = "本报告仅供内部使用，不构成任何投资建议。"
    pages = tuple(page(number, (span(repeated, top=400.0),)) for number in (1, 2, 3))
    cleaned = remove_repeated_margins(pages, LayoutPolicy())
    assert [s.text for p in cleaned for s in p.spans] == [repeated] * 3


def test_a_header_on_one_page_only_is_not_treated_as_furniture() -> None:
    """With a single page there is no evidence of repetition, so nothing is dropped."""
    pages = (page(1, (span(HEADER_TEXT, top=30.0), span(BODY_TEXT, top=300.0))),)
    cleaned = remove_repeated_margins(pages, LayoutPolicy())
    assert [s.text for p in cleaned for s in p.spans] == [HEADER_TEXT, BODY_TEXT]


def test_grouping_merges_nearby_lines_into_one_block() -> None:
    lines = tuple(
        span(text, top=100.0 + 14.0 * index)
        for index, text in enumerate(("第一行文字。", "第二行文字。", "第三行文字。"))
    )
    blocks = group_spans_into_blocks(page(1, lines), LayoutPolicy())
    assert len(blocks) == 1
    assert blocks[0].block_type is BlockType.PARAGRAPH
    assert "第一行文字。" in blocks[0].text
    assert "第三行文字。" in blocks[0].text


def test_grouping_splits_a_paragraph_from_a_distant_line() -> None:
    lines = (span("第一段文字。", top=100.0), span("很远的一段文字。", top=500.0))
    blocks = group_spans_into_blocks(page(1, lines), LayoutPolicy())
    assert len(blocks) == 2
