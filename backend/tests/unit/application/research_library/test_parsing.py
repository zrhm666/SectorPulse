"""The parse pipeline: dispatch, limits, and what Markdown and TXT must preserve.

The two source formats without a page model are where structure is easiest to lose.
Markdown carries the outline and the table/code boundaries explicitly, and the parser's
job is to keep them rather than reflow everything into paragraphs. TXT carries nothing
except bytes and an unknown encoding, and the parser's job is to decode it deterministically
— guessing wrong turns a Chinese report into a page of replacement characters that then
indexes as if it were content.
"""

from pathlib import Path

import pytest
from sector_pulse.application.research_library.parsing import (
    PARSE_PIPELINE_VERSION,
    ResearchParsePipeline,
)
from sector_pulse.domain.research_library.models import (
    BlockType,
    DocumentBlock,
    ExtractionMethod,
)
from sector_pulse.infrastructure.research_library.parsing import build_parse_pipeline
from sector_pulse.infrastructure.research_library.parsing.layout import join_wrapped_lines
from sector_pulse.ports.research_models import (
    ParseError,
    ParseSource,
    UnsupportedMediaType,
)

from backend.tests.research_library_parsing_support import (
    FIXTURE_OCR_PROVIDER,
    MARKDOWN_MEDIA_TYPE,
    TEXT_MEDIA_TYPE,
    FakeOcrProvider,
    default_limits,
    native_source,
    scanned_source,
    source,
)

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "research_library"
MARKDOWN = (FIXTURES / "industry_note.md").read_bytes()
PLAIN_TEXT = (FIXTURES / "industry_note.txt").read_bytes()


@pytest.fixture
def pipeline() -> ResearchParsePipeline:
    return build_parse_pipeline()


def blocks_of_type(pipeline: ResearchParsePipeline, src: ParseSource, kind: BlockType):
    return [b for b in pipeline.parse(src).blocks if b.block_type is kind]


# --- dispatch ---


def test_each_media_type_reaches_its_own_parser(pipeline: ResearchParsePipeline) -> None:
    cases = (
        (native_source(), "pdf"),
        (source(MARKDOWN, media_type=MARKDOWN_MEDIA_TYPE, filename="n.md"), "markdown"),
        (source(PLAIN_TEXT, media_type=TEXT_MEDIA_TYPE, filename="n.txt"), "text"),
    )
    for src, expected in cases:
        assert pipeline.parse(src).parser_name == expected


def test_an_unknown_media_type_is_refused(pipeline: ResearchParsePipeline) -> None:
    with pytest.raises(UnsupportedMediaType):
        pipeline.parse(source(b"PK\x03\x04", media_type="application/zip", filename="a.zip"))


def test_the_pipeline_version_is_recorded_on_every_document(
    pipeline: ResearchParsePipeline,
) -> None:
    """The version is what makes a re-parse decision auditable later."""
    for src in (
        native_source(),
        source(MARKDOWN, media_type=MARKDOWN_MEDIA_TYPE),
        source(PLAIN_TEXT, media_type=TEXT_MEDIA_TYPE),
    ):
        assert pipeline.parse(src).parser_version == PARSE_PIPELINE_VERSION


def test_limits_are_enforced_once_for_the_whole_pipeline() -> None:
    strict = ResearchParsePipeline(
        parsers=build_parse_pipeline().parsers, limits=default_limits(max_bytes=1024)
    )
    with pytest.raises(ParseError):
        strict.parse(native_source())


def test_the_pipeline_passes_its_ocr_provider_to_the_pdf_parser() -> None:
    ocr = FakeOcrProvider()
    pipeline = build_parse_pipeline(ocr=ocr)
    parsed = pipeline.parse(scanned_source())
    assert ocr.requested_pages == [2]
    assert parsed.ocr_provider == FIXTURE_OCR_PROVIDER


def test_a_document_without_pages_still_reports_its_blocks(
    pipeline: ResearchParsePipeline,
) -> None:
    parsed = pipeline.parse(source(PLAIN_TEXT, media_type=TEXT_MEDIA_TYPE))
    assert parsed.blocks
    assert parsed.page_count == 0
    assert all(block.page_number is None for block in parsed.blocks)


# --- Markdown ---


def test_markdown_headings_build_a_nested_section_path(
    pipeline: ResearchParsePipeline,
) -> None:
    parsed = pipeline.parse(source(MARKDOWN, media_type=MARKDOWN_MEDIA_TYPE))
    headings = [b for b in parsed.blocks if b.block_type is BlockType.HEADING]
    assert [b.text for b in headings] == [
        "储能行业跟踪周报",
        "海外需求",
        "欧洲市场",
        "美国市场",
    ]

    european = next(b for b in parsed.blocks if "欧洲户储库存" in b.text)
    assert european.heading_path == ("储能行业跟踪周报", "海外需求", "欧洲市场")

    american = next(b for b in parsed.blocks if "关税政策" in b.text)
    assert american.heading_path == ("储能行业跟踪周报", "海外需求", "美国市场")


def test_markdown_keeps_the_table_in_one_block(pipeline: ResearchParsePipeline) -> None:
    """切在表格中间会同时毁掉表头和单位，因此表格块必须整体存在。"""
    tables = blocks_of_type(
        pipeline, source(MARKDOWN, media_type=MARKDOWN_MEDIA_TYPE), BlockType.TABLE
    )
    assert len(tables) == 1
    text = tables[0].text
    assert "2025" in text
    assert "2026" in text
    assert "营收" in text
    assert "同比" in text


def test_markdown_keeps_a_fenced_block_as_code(pipeline: ResearchParsePipeline) -> None:
    code = blocks_of_type(
        pipeline, source(MARKDOWN, media_type=MARKDOWN_MEDIA_TYPE), BlockType.CODE
    )
    assert len(code) == 1
    assert "def revenue" in code[0].text
    assert code[0].heading_path[-1] == "欧洲市场"


def test_markdown_lists_stay_lists(pipeline: ResearchParsePipeline) -> None:
    items = blocks_of_type(
        pipeline, source(MARKDOWN, media_type=MARKDOWN_MEDIA_TYPE), BlockType.LIST
    )
    assert items
    joined = "\n".join(item.text for item in items)
    assert "大储项目排期推迟" in joined
    assert "户储渠道库存偏高" in joined


def test_markdown_blocks_are_marked_parser_derived(pipeline: ResearchParsePipeline) -> None:
    parsed = pipeline.parse(source(MARKDOWN, media_type=MARKDOWN_MEDIA_TYPE))
    assert all(
        block.extraction_method is ExtractionMethod.PARSER_DERIVED for block in parsed.blocks
    )


def test_markdown_does_not_emit_the_heading_marker(pipeline: ResearchParsePipeline) -> None:
    parsed = pipeline.parse(source(MARKDOWN, media_type=MARKDOWN_MEDIA_TYPE))
    assert not any(block.text.startswith("#") for block in parsed.blocks)


# --- source ranges (spec 7.6/7.7: a citation must point back into the original) ---


def test_markdown_blocks_carry_the_source_range_they_came_from(
    pipeline: ResearchParsePipeline,
) -> None:
    text = MARKDOWN.decode("utf-8")
    parsed = pipeline.parse(source(MARKDOWN, media_type=MARKDOWN_MEDIA_TYPE))

    for block in parsed.blocks:
        if block.block_type is BlockType.TABLE:
            # A table is reflowed into indexable text, so its text is not a verbatim slice;
            # its range still has to cover the table.
            assert block.source_span is not None
            continue
        assert block.source_span is not None, block.block_id
        assert block.text in text[block.source_span.start : block.source_span.end]


def test_a_markdown_source_range_is_the_block_and_not_the_whole_document(
    pipeline: ResearchParsePipeline,
) -> None:
    text = MARKDOWN.decode("utf-8")
    parsed = pipeline.parse(source(MARKDOWN, media_type=MARKDOWN_MEDIA_TYPE))
    heading = next(block for block in parsed.blocks if block.text == "欧洲市场")
    assert heading.source_span is not None
    assert text[heading.source_span.start : heading.source_span.end] == "### 欧洲市场"


def test_text_blocks_carry_the_source_range_they_came_from(
    pipeline: ResearchParsePipeline,
) -> None:
    normalized = PLAIN_TEXT.decode("utf-8").replace("\r\n", "\n")
    parsed = pipeline.parse(source(PLAIN_TEXT, media_type=TEXT_MEDIA_TYPE))

    assert parsed.blocks
    for block in parsed.blocks:
        assert block.source_span is not None
        raw = normalized[block.source_span.start : block.source_span.end]
        # The block text is what the parser made of that slice: wrapped lines rejoined.
        assert join_wrapped_lines(raw.splitlines()) == block.text


# --- plain text ---


def test_text_paragraphs_are_split_on_blank_lines(pipeline: ResearchParsePipeline) -> None:
    parsed = pipeline.parse(source(PLAIN_TEXT, media_type=TEXT_MEDIA_TYPE))
    paragraphs = [b for b in parsed.blocks if b.block_type is BlockType.PARAGRAPH]
    assert len(paragraphs) == 4
    assert paragraphs[0].text == "储能行业跟踪周报"
    assert "欧洲户储库存去化接近尾声" in paragraphs[1].text


def test_text_lines_inside_one_paragraph_are_joined(
    pipeline: ResearchParsePipeline,
) -> None:
    """A hard-wrapped sentence is one sentence, not one block per line."""
    wrapped = "第一句在这一行结束。\n第二句接着同一段的下一行。\n\n另一段。"
    parsed = pipeline.parse(source(wrapped.encode(), media_type=TEXT_MEDIA_TYPE))
    paragraphs = [b for b in parsed.blocks if b.block_type is BlockType.PARAGRAPH]
    assert len(paragraphs) == 2
    # No space is inserted: the wrap was a display artefact, and in Chinese a space
    # between two characters is a character the author did not write.
    assert paragraphs[0].text == "第一句在这一行结束。第二句接着同一段的下一行。"


def test_a_latin_wrap_keeps_the_space_it_stood_for(
    pipeline: ResearchParsePipeline,
) -> None:
    """The opposite rule for the opposite script: dropping it would fuse two words."""
    wrapped = "First sentence.\nSecond sentence."
    parsed = pipeline.parse(source(wrapped.encode(), media_type=TEXT_MEDIA_TYPE))
    assert parsed.blocks[0].text == "First sentence. Second sentence."


def test_a_space_the_author_wrote_between_two_chinese_characters_survives(
    pipeline: ResearchParsePipeline,
) -> None:
    """Only the space a wrap introduced is dropped; a real one must stay."""
    authored = "碳酸锂 价格回落。"
    parsed = pipeline.parse(source(authored.encode(), media_type=TEXT_MEDIA_TYPE))
    assert parsed.blocks[0].text == "碳酸锂 价格回落。"


def test_a_utf8_bom_is_not_left_in_the_first_block(pipeline: ResearchParsePipeline) -> None:
    payload = "﻿储能行业跟踪周报\n\n正文。".encode()
    parsed = pipeline.parse(source(payload, media_type=TEXT_MEDIA_TYPE))
    assert parsed.blocks[0].text == "储能行业跟踪周报"


def test_a_utf16_document_is_decoded(pipeline: ResearchParsePipeline) -> None:
    payload = "储能行业跟踪周报\n\n正文。".encode("utf-16")
    parsed = pipeline.parse(source(payload, media_type=TEXT_MEDIA_TYPE))
    assert parsed.blocks[0].text == "储能行业跟踪周报"


def test_a_gb18030_document_is_decoded_instead_of_becoming_replacement_characters(
    pipeline: ResearchParsePipeline,
) -> None:
    """A mis-decoded Chinese report indexes as garbage that still looks like content."""
    payload = "储能行业跟踪周报\n\n碳酸锂价格在同期明显回落。".encode("gb18030")
    parsed = pipeline.parse(source(payload, media_type=TEXT_MEDIA_TYPE))
    assert parsed.blocks[0].text == "储能行业跟踪周报"
    assert "碳酸锂价格" in parsed.blocks[1].text
    assert "�" not in "".join(b.text for b in parsed.blocks)


def test_windows_line_endings_do_not_become_paragraph_breaks(
    pipeline: ResearchParsePipeline,
) -> None:
    payload = "第一段。\r\n仍在第一段。\r\n\r\n第二段。\r\n".encode()
    parsed = pipeline.parse(source(payload, media_type=TEXT_MEDIA_TYPE))
    paragraphs = [b for b in parsed.blocks if b.block_type is BlockType.PARAGRAPH]
    assert len(paragraphs) == 2
    assert paragraphs[0].text == "第一段。仍在第一段。"
    assert "\r" not in paragraphs[0].text


def test_bytes_that_decode_no_known_way_still_produce_a_usable_document(
    pipeline: ResearchParsePipeline,
) -> None:
    """Losing a file is worse than decoding it imperfectly, but the loss must be visible."""
    payload = b"caf\xe9 latte\n\nsecond paragraph"
    parsed = pipeline.parse(source(payload, media_type=TEXT_MEDIA_TYPE))
    assert parsed.blocks
    assert parsed.warnings


def test_an_empty_text_file_produces_no_blocks_and_no_crash(
    pipeline: ResearchParsePipeline,
) -> None:
    parsed = pipeline.parse(source(b"", media_type=TEXT_MEDIA_TYPE))
    assert parsed.blocks == ()


# --- every producer honours the shared block rules ---


def test_blocks_are_unique_and_ordered_across_all_three_parsers(
    pipeline: ResearchParsePipeline,
) -> None:
    for src in (
        native_source(pages=2),
        source(MARKDOWN, media_type=MARKDOWN_MEDIA_TYPE),
        source(PLAIN_TEXT, media_type=TEXT_MEDIA_TYPE),
    ):
        blocks: tuple[DocumentBlock, ...] = pipeline.parse(src).blocks
        ids = [block.block_id for block in blocks]
        assert len(set(ids)) == len(ids), ids
        assert [block.block_order for block in blocks] == list(range(len(blocks)))
