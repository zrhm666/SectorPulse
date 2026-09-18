"""How the parse pipeline wires non-text normalization into a real document.

The rules in `test_non_text_blocks.py` are pure functions taking hand-built inputs. This
file is the other half: a document goes in through the pipeline and the table and image
blocks that come out are the normalized ones, with the pre-normalization text replaced
rather than kept alongside it — two representations of one table would let a later stage
index whichever it happened to read first.
"""

from sector_pulse.application.research_library.parsing import ResearchParsePipeline
from sector_pulse.domain.research_library.models import BlockType
from sector_pulse.infrastructure.research_library.parsing import build_parse_pipeline
from sector_pulse.ports.research_models import ParseSource

MARKDOWN_MEDIA_TYPE = "text/markdown"


def markdown_source(text: str) -> ParseSource:
    return ParseSource(media_type=MARKDOWN_MEDIA_TYPE, content=text.encode(), filename="n.md")


def parse(text: str, pipeline: ResearchParsePipeline | None = None):
    return (pipeline or build_parse_pipeline()).parse(markdown_source(text))


TABLE_DOCUMENT = """# 储能行业跟踪周报

## 欧洲市场

| 年份 | 营收 | 同比 |
| --- | --- | --- |
| 2025 | 120 亿 | 15% |
| 2026 | 138 亿 | 15% |
"""


def test_a_markdown_table_is_indexed_in_the_spec_sentence_form() -> None:
    parsed = parse(TABLE_DOCUMENT)

    table = next(block for block in parsed.blocks if block.block_type is BlockType.TABLE)

    assert table.text.startswith("表格：")
    assert "2025 年：营收 120 亿，同比 15%。" in table.text


def test_a_markdown_table_keeps_its_structure_next_to_the_indexed_text() -> None:
    parsed = parse(TABLE_DOCUMENT)

    table = next(block for block in parsed.blocks if block.block_type is BlockType.TABLE)
    normalized = next(
        block for block in parsed.non_text_blocks if block.block_id == table.block_id
    )

    assert normalized.table is not None
    assert normalized.table.columns == ("年份", "营收", "同比")
    assert normalized.table.rows[0] == ("2025", "120 亿", "15%")
    # 最近的标题成为表名：切片时表名会被重复，没有它数据行就没有主语。
    assert normalized.table.title == "欧洲市场"


def test_the_table_block_is_located_where_it_was_written() -> None:
    parsed = parse(TABLE_DOCUMENT)

    table = next(block for block in parsed.blocks if block.block_type is BlockType.TABLE)
    normalized = next(
        block for block in parsed.non_text_blocks if block.block_id == table.block_id
    )

    assert table.source_span is not None
    assert normalized.source_span == table.source_span
    assert normalized.heading_path == ("储能行业跟踪周报", "欧洲市场")


def test_a_markdown_image_with_alt_text_becomes_an_indexable_image_block() -> None:
    parsed = parse("## 图表\n\n![图 1 欧洲户储库存去化](chart.png)\n\n正文。\n")

    images = [block for block in parsed.blocks if block.block_type is BlockType.IMAGE]

    assert [block.text for block in images] == ["图 1 欧洲户储库存去化"]
    assert images[0].heading_path == ("图表",)


def test_a_markdown_image_without_alt_text_is_kept_but_not_indexed() -> None:
    parsed = parse("![](chart.png)\n")

    assert parsed.blocks == ()
    assert len(parsed.non_text_blocks) == 1
    assert parsed.non_text_blocks[0].indexable_text is None
    assert parsed.non_text_blocks[0].block_type is BlockType.IMAGE


def test_a_markdown_image_is_not_folded_into_the_paragraph_around_it() -> None:
    parsed = parse("欧洲市场库存见下图。\n\n![图 1 库存](chart.png)\n")

    paragraphs = [block.text for block in parsed.blocks if block.block_type is BlockType.PARAGRAPH]

    assert paragraphs == ["欧洲市场库存见下图。"]
    assert "图 1 库存" not in paragraphs[0]


def test_a_document_without_non_text_blocks_reports_none() -> None:
    parsed = parse("只有一段正文。\n")

    assert parsed.non_text_blocks == ()
