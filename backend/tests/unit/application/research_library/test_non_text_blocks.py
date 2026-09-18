"""Tables, charts, images and formulas: what enters the text index, and as what.

Spec 7.8–7.11 are all one question asked four times — may this content be indexed, and in
whose name. The failures are asymmetric, which is why each rule gets its own test. Indexing
an image that has no caption puts a picture with nothing to say in front of a query it
cannot answer; indexing a vision model's numbers as fact puts a wrong digit in an answer
that reads exactly like a right one. The rules here are not about being conservative for its
own sake: an unindexed region still keeps its locator and its bytes, so a human can still
find it — it just cannot be mistaken for evidence.
"""

import json

import pytest
from pydantic import ValidationError
from sector_pulse.application.research_library.non_text_blocks import (
    normalize_chart,
    normalize_formula,
    normalize_image,
    normalize_table,
    store_region,
    table_region,
)
from sector_pulse.domain.research_library.models import ExtractionMethod
from sector_pulse.infrastructure.research_library.assets.memory import (
    InMemoryResearchAssetStore,
)
from sector_pulse.ports.research_assets import AssetRole
from sector_pulse.ports.research_models import (
    ChartAxis,
    ChartInput,
    FormulaInput,
    FormulaNotation,
    FormulaVariable,
    ImageInput,
    RegionAsset,
    TableData,
    VisualDescription,
)

REGION = RegionAsset(
    content=b"\x89PNG\r\n\x1a\n not a real chart",
    content_type="image/png",
    asset_role=AssetRole.CHART_IMAGE,
    filename="chart-1.png",
    page_number=18,
)

#: 规格 7.8 给出的例子，逐字使用：它的文本表示是这段代码的规格，不是示意。
SPEC_TABLE = TableData(
    block_id="blk_00007",
    title="公司营收情况",
    columns=("年份", "营收", "同比"),
    rows=(("2025", "120 亿", "15%"), ("2026", "138 亿", "15%")),
    unit="亿元",
)

CHART_BASE = ChartInput(
    block_id="blk_00011",
    caption="图 3 欧洲户储装机",
    legend=("2025", "2026"),
    axes=(ChartAxis(label="装机", unit="MWh"),),
    nearby_text="装机在二季度后明显回升。",
    page_number=21,
    origin=ExtractionMethod.NATIVE,
)

DIMMER_CHART = VisualDescription(
    description="欧洲户储月度装机连续三个月回升",
    chart_type="line",
    y_axis=ChartAxis(label="装机", unit="MWh"),
    series=("2025", "2026"),
    reported_values=("2025 年 12 月 3.2 MWh",),
    confidence=0.42,
    provider="fixture-vision",
    model_version="fixture-vision-v1",
)

CONFIDENT_CHART = DIMMER_CHART.model_copy(update={"confidence": 0.88})

UNLABELED_IMAGE = ImageInput(block_id="blk_00012", page_number=9, region=REGION)


# --- tables (spec 7.8) ---


def test_the_table_text_matches_the_spec_sentence_form() -> None:
    block = normalize_table(SPEC_TABLE, page_number=18)

    assert block.indexable_text == (
        "表格：公司营收情况\n"
        "单位：亿元\n"
        "2025 年：营收 120 亿，同比 15%。\n"
        "2026 年：营收 138 亿，同比 15%。"
    )
    assert block.content_origin is ExtractionMethod.PARSER_DERIVED
    assert block.requires_verification is False
    assert block.page_number == 18


def test_a_table_keeps_the_structure_the_index_cannot_hold() -> None:
    """结构化数据要落成资产（规格 7.8）：切片里放不下列与行。"""
    block = normalize_table(SPEC_TABLE)

    assert block.table == SPEC_TABLE
    assert block.table is not None
    assert block.table.unit == "亿元"


def test_a_table_without_data_rows_is_not_indexed() -> None:
    """一列表头不构成任何断言，索引它只会让文档匹配到它回答不了的问题。"""
    header_only = TableData(block_id="blk_00013", title="公司营收情况", columns=("年份", "营收"))

    block = normalize_table(header_only)

    assert block.indexable_text is None
    assert block.table is not None  # 结构留给人工核对
    assert block.warnings


def test_a_row_that_does_not_match_the_columns_is_refused() -> None:
    with pytest.raises(ValidationError):
        TableData(block_id="blk_1", columns=("年份", "营收"), rows=(("2025",),))


def test_an_empty_cell_is_left_out_instead_of_becoming_a_blank_claim() -> None:
    sparse = TableData(
        block_id="blk_00014",
        title="公司营收情况",
        columns=("年份", "营收", "同比"),
        rows=(("2025", "", "15%"),),
    )

    text = normalize_table(sparse).indexable_text

    assert text is not None
    # The empty cell is gone from the sentence; the column heading still appears in the
    # table's title, which is a different sentence and is supposed to be there.
    assert text.splitlines()[-1] == "2025 年：同比 15%。"


def test_a_year_column_reads_as_a_year() -> None:
    """规格的例子里 `2025` 被读成 `2025 年`：检索问的是"哪一年"，不是"哪个数字"。"""
    text = normalize_table(SPEC_TABLE).indexable_text

    assert text is not None
    assert "2025 年：" in text
    assert "2025：" not in text


def test_table_notes_survive_into_the_indexed_text() -> None:
    noted = SPEC_TABLE.model_copy(update={"notes": "口径为合并报表。"})

    text = normalize_table(noted).indexable_text

    assert text is not None
    assert "注释：口径为合并报表。" in text


# --- charts (spec 7.9) ---


def test_low_confidence_chart_is_searchable_only_as_unverified_lead() -> None:
    block = normalize_chart(CHART_BASE.model_copy(update={"vision": DIMMER_CHART}))

    assert block.content_origin is ExtractionMethod.VISION_DERIVED
    assert block.requires_verification is True
    assert block.indexable_text is not None
    assert DIMMER_CHART.description in block.indexable_text
    # 文档自身的那一层不因为视觉层不可信而消失。
    assert "图 3 欧洲户储装机" in block.indexable_text
    assert block.warnings


def test_a_confident_consistent_chart_description_is_candidate_evidence() -> None:
    block = normalize_chart(CHART_BASE.model_copy(update={"vision": CONFIDENT_CHART}))

    assert block.requires_verification is False
    assert block.confidence == pytest.approx(0.88)
    assert block.warnings == ()
    assert block.indexable_text is not None
    assert CONFIDENT_CHART.description in block.indexable_text


def test_a_value_that_is_not_a_number_is_not_candidate_evidence() -> None:
    """规格 7.9 要求视觉数值通过格式校验；"明显回升"不是一个数值。"""
    malformed = CONFIDENT_CHART.model_copy(update={"reported_values": ("装机明显回升",)})

    block = normalize_chart(CHART_BASE.model_copy(update={"vision": malformed}))

    assert block.requires_verification is True
    assert any("format" in warning for warning in block.warnings)


def test_reported_values_without_a_series_are_not_candidate_evidence() -> None:
    """有数值却没有系列：读者无法知道这个数说的是哪条线。"""
    orphaned = CONFIDENT_CHART.model_copy(update={"series": ()})

    block = normalize_chart(CHART_BASE.model_copy(update={"vision": orphaned}))

    assert block.requires_verification is True
    assert any("consistency" in warning for warning in block.warnings)


def test_a_chart_without_a_caption_or_a_description_has_nothing_to_index() -> None:
    block = normalize_chart(ChartInput(block_id="blk_00015"))

    assert block.indexable_text is None
    assert block.warnings


def test_a_chart_is_readable_with_no_vision_provider_at_all() -> None:
    block = normalize_chart(CHART_BASE)

    assert block.requires_verification is False
    assert block.content_origin is ExtractionMethod.NATIVE
    assert block.indexable_text is not None
    assert "图 3 欧洲户储装机" in block.indexable_text


# --- images (spec 7.10) ---


def test_image_without_caption_or_description_is_not_indexable() -> None:
    block = normalize_image(UNLABELED_IMAGE)

    assert block.indexable_text is None
    assert block.region is not None
    assert block.page_number == 9


def test_an_image_is_indexed_from_the_document_own_caption() -> None:
    block = normalize_image(ImageInput(block_id="blk_00016", caption="图 5 储能电站分布"))

    assert block.indexable_text == "图 5 储能电站分布"
    assert block.content_origin is not ExtractionMethod.VISION_DERIVED
    assert block.requires_verification is False


def test_a_derived_image_description_says_that_it_is_derived() -> None:
    block = normalize_image(ImageInput(block_id="blk_00017", vision=CONFIDENT_CHART))

    assert block.indexable_text is not None
    assert block.indexable_text.startswith("（模型派生描述）")
    assert block.content_origin is ExtractionMethod.VISION_DERIVED


def test_a_low_confidence_image_description_is_an_unverified_lead() -> None:
    block = normalize_image(ImageInput(block_id="blk_00018", vision=DIMMER_CHART))

    assert block.requires_verification is True
    assert block.indexable_text is not None


def test_decorative_images_are_excluded_entirely() -> None:
    """Logo 和背景图不是资料内容；为它们留一个块只会让每次检索都扫过它们。"""
    logo = ImageInput(block_id="blk_00019", caption="公司 logo", is_decorative=True)

    assert normalize_image(logo) is None


# --- formulas (spec 7.11) ---


def test_a_formula_with_reliable_notation_is_indexed_with_its_variables() -> None:
    formula = FormulaInput(
        block_id="blk_00020",
        name="产能利用率",
        expression="U = Q / C",
        notation=FormulaNotation.UNICODE,
        variables=(
            FormulaVariable(symbol="U", description="产能利用率"),
            FormulaVariable(symbol="Q", description="实际产量"),
            FormulaVariable(symbol="C", description="设计产能"),
        ),
        context="产能利用率在报告期内环比提升。",
    )

    text = normalize_formula(formula).indexable_text

    assert text is not None
    assert "公式：产能利用率" in text
    assert "U = Q / C" in text
    assert "U — 产能利用率" in text
    assert "产能利用率在报告期内环比提升。" in text


def test_a_formula_that_exists_only_as_a_screenshot_is_not_indexed() -> None:
    block = normalize_formula(FormulaInput(block_id="blk_00021", region=REGION))

    assert block.indexable_text is None
    assert block.region is not None
    assert block.warnings


def test_an_extracted_formula_must_declare_its_notation() -> None:
    """没有记法就无法在引用时重新渲染，也无法判断它是不是猜出来的。"""
    with pytest.raises(ValidationError):
        FormulaInput(block_id="blk_1", expression="U = Q / C")


def test_the_formula_normalizer_does_not_evaluate_the_expression() -> None:
    """计算结果属于确定性计算 Tool（规格 7.11）；检索层算出来的数字没有可核对的过程。"""
    block = normalize_formula(
        FormulaInput(
            block_id="blk_00022",
            expression="x = 2 + 3",
            notation=FormulaNotation.LATEX,
        )
    )

    assert block.indexable_text is not None
    assert "5" not in block.indexable_text


# --- regions are written through the asset store, never into agent context ---


def test_a_region_asset_is_written_under_a_role_scoped_key() -> None:
    store = InMemoryResearchAssetStore()

    ref = store_region(store, REGION, document_id="doc_1", document_version_id="ver_2")

    assert ref.key == "chart_image/doc_1/ver_2/chart-1.png"
    assert ref.asset_role is AssetRole.CHART_IMAGE
    with store.open(ref.key) as handle:
        assert handle.read() == REGION.content


def test_a_table_structure_is_stored_as_an_extracted_table_asset() -> None:
    store = InMemoryResearchAssetStore()
    region = table_region(SPEC_TABLE, page_number=18)

    ref = store_region(store, region, document_id="doc_1", document_version_id="ver_2")

    assert ref.key.startswith("extracted_table/doc_1/ver_2/")
    with store.open(ref.key) as handle:
        stored = json.loads(handle.read())
    assert stored["columns"] == ["年份", "营收", "同比"]
    assert stored["rows"][0] == ["2025", "120 亿", "15%"]
    assert stored["unit"] == "亿元"


def test_the_normalized_block_keeps_the_region_out_of_the_indexed_text() -> None:
    """原图只留下引用：索引文本会进入检索结果与 Agent 上下文，字节不会。"""
    block = normalize_image(ImageInput(block_id="blk_00023", caption="图 5", region=REGION))

    assert block.indexable_text is not None
    assert REGION.content.decode("latin-1") not in block.indexable_text
    assert block.region is not None
