"""非文本块规范化：决定一块内容以什么身份进入索引（规格 7.8–7.11）。

这一层存在的理由是索引是"匹配"，而匹配不会区分身份的差别：一张没有图题的图片和一条
结论在向量空间里同样是若干维浮点数。所以身份必须在这里定下来，用一个显式字段表达，
而不是靠下游哪一步记得要小心。

四条规则，各自对应规格中的一节：

- **表格**（7.8）产出确定性的句子形式文本，并保留结构化数据与单位、注释；
- **图表**（7.9）先索引文档自身的那一层（图题、图例、坐标轴、附近正文），视觉描述
  只在通过阈值、格式与一致性校验时才可以成为候选证据，否则只是一条待核验线索；
- **图片**（7.10）只索引原始图题，或明确标注为派生的描述；两者都没有就不进索引；
- **公式**（7.11）只在记法可靠时组块，且从不计算表达式——计算是确定性 Tool 的职责。

`indexable_text is None` 是这一层唯一的"不进索引"表达。它不等于丢弃：区域资产、页码、
源字符范围都还在，人可以找到它，只是检索不会把它当答案。
"""

import json
import re
from io import BytesIO

from sector_pulse.domain.research_library.models import BlockType, ExtractionMethod
from sector_pulse.ports.research_assets import (
    AssetMetadata,
    AssetRef,
    AssetRole,
    ResearchAssetStore,
)
from sector_pulse.ports.research_models import (
    ChartAxis,
    ChartInput,
    FormulaInput,
    ImageInput,
    NonTextBlock,
    NonTextPolicy,
    RegionAsset,
    TableData,
    VisualDescription,
)

TABLE_TITLE_PREFIX = "表格："
UNIT_PREFIX = "单位："
NOTES_PREFIX = "注释："
FORMULA_PREFIX = "公式："
LEGEND_PREFIX = "图例："
AXIS_PREFIX = "坐标轴："
FOOTNOTE_PREFIX = "脚注："
VARIABLES_PREFIX = "变量："

#: 视觉描述的数值行只在通过校验后才出现；没通过时它连"数值"都不是。
VALUES_PREFIX = "数值："

#: 派生描述的前缀。它进入的是与其他证据同一个索引，因此必须自报身份。
DERIVED_DESCRIPTION_PREFIX = "（模型派生描述）"

VARIABLE_SEPARATOR = " — "
CELL_SEPARATOR = "，"
LIST_SEPARATOR = "、"
VALUE_SEPARATOR = "；"

#: 结构化表格以 JSON 落库，内容类型固定，人工核对时可以直接打开。
EXTRACTED_TABLE_MEDIA_TYPE = "application/json"

YEAR_PATTERN = re.compile(r"^\d{4}$")
DIGIT_PATTERN = re.compile(r"\d")

DEFAULT_POLICY = NonTextPolicy()


def normalize_table(
    table: TableData,
    *,
    page_number: int | None = None,
    origin: ExtractionMethod = ExtractionMethod.PARSER_DERIVED,
    region: RegionAsset | None = None,
) -> NonTextBlock:
    """把表格变成可检索的句子形式，并保留它的结构。

    规格 7.8 给了一份确切的文本表示，这里逐字实现：表名、单位、每行一句。表名与单位
    不是装饰——切片之后数据行会离开表头，没有它们的数字既没有主语也没有量纲。
    """
    warnings: list[str] = []
    if not table.rows:
        warnings.append(
            "this table has no data rows, so it asserts nothing and is not indexed; "
            "its structure and locator are kept for human review"
        )
    return NonTextBlock(
        block_id=table.block_id,
        block_type=BlockType.TABLE,
        content_origin=origin,
        indexable_text=_table_text(table),
        page_number=page_number if page_number is not None else _region_page(region),
        table=table,
        region=region,
        warnings=tuple(warnings),
    )


def normalize_chart(chart: ChartInput, *, policy: NonTextPolicy | None = None) -> NonTextBlock:
    """图表：基础层照常索引，视觉层按其可信程度决定身份。"""
    active = policy if policy is not None else DEFAULT_POLICY
    base = _chart_base_text(chart)
    vision = chart.vision

    if vision is None:
        warnings = () if base else (_no_source_material("chart"),)
        return NonTextBlock(
            block_id=chart.block_id,
            block_type=BlockType.CHART,
            content_origin=chart.origin,
            indexable_text=base or None,
            page_number=_page_number(chart.page_number, chart.region),
            region=chart.region,
            warnings=warnings,
        )

    usable, reason = _vision_is_usable(vision, active)
    text = "\n".join(part for part in (base, _vision_text(vision, include_values=usable)) if part)
    return NonTextBlock(
        block_id=chart.block_id,
        block_type=BlockType.CHART,
        # 只要索引文本里有一句来自视觉模型，整块就按视觉派生的身份记账：读者据此知道
        # 这段话需要核对，而不会以为它来自文档正文。
        content_origin=ExtractionMethod.VISION_DERIVED,
        indexable_text=text or None,
        confidence=vision.confidence,
        requires_verification=not usable,
        page_number=_page_number(chart.page_number, chart.region),
        region=chart.region,
        warnings=() if usable else (reason,),
    )


def normalize_image(
    image: ImageInput, *, policy: NonTextPolicy | None = None
) -> NonTextBlock | None:
    """普通图片。装饰图片返回 `None`：它不该在库里留下任何东西。

    返回 `None` 而不是一个不可索引的块，是因为调用方需要能区分"这张图没内容"和
    "这张图根本不是内容"。前者要留定位供人核对，后者连留都不该留。
    """
    if image.is_decorative:
        return None

    active = policy if policy is not None else DEFAULT_POLICY
    caption = (image.caption or "").strip()
    if caption:
        return NonTextBlock(
            block_id=image.block_id,
            block_type=BlockType.IMAGE,
            content_origin=image.origin,
            indexable_text=caption,
            page_number=_page_number(image.page_number, image.region),
            region=image.region,
        )

    vision = image.vision
    if vision is not None:
        usable, reason = _vision_is_usable(vision, active)
        return NonTextBlock(
            block_id=image.block_id,
            block_type=BlockType.IMAGE,
            content_origin=ExtractionMethod.VISION_DERIVED,
            indexable_text=_vision_text(vision, include_values=usable),
            confidence=vision.confidence,
            requires_verification=not usable,
            page_number=_page_number(image.page_number, image.region),
            region=image.region,
            warnings=() if usable else (reason,),
        )

    return NonTextBlock(
        block_id=image.block_id,
        block_type=BlockType.IMAGE,
        content_origin=image.origin,
        indexable_text=None,
        page_number=_page_number(image.page_number, image.region),
        region=image.region,
        warnings=(_no_source_material("image"),),
    )


def normalize_formula(
    formula: FormulaInput, *, policy: NonTextPolicy | None = None
) -> NonTextBlock:
    """公式：名称、表达式、变量与附近正文组成一个块；没有可靠记法就不组。

    `policy` 目前不参与判定：公式的可靠性由"有没有记法"决定，而记法已经在
    `FormulaInput` 上验证过。保留参数是为了让四个规范化函数的签名一致，
    调用方不必记住哪一个多一个参数。
    """
    if formula.expression is None:
        return NonTextBlock(
            block_id=formula.block_id,
            block_type=BlockType.FORMULA,
            content_origin=formula.origin,
            indexable_text=None,
            page_number=_page_number(formula.page_number, formula.region),
            region=formula.region,
            warnings=(
                "this formula was not recognized from text — only its region is kept, and no "
                "expression is guessed from the image",
            ),
        )

    lines: list[str] = []
    if formula.name:
        lines.append(f"{FORMULA_PREFIX}{formula.name}")
    # 表达式原样出现，不做任何化简或计算（规格 7.11：计算结果由确定性 Tool 负责）。
    lines.append(formula.expression)
    if formula.variables:
        lines.append(
            VARIABLES_PREFIX
            + VALUE_SEPARATOR.join(
                f"{variable.symbol}{VARIABLE_SEPARATOR}{variable.description}"
                for variable in formula.variables
            )
        )
    if formula.context:
        lines.append(formula.context)

    return NonTextBlock(
        block_id=formula.block_id,
        block_type=BlockType.FORMULA,
        content_origin=formula.origin,
        indexable_text="\n".join(lines),
        page_number=_page_number(formula.page_number, formula.region),
        region=formula.region,
    )


def table_region(table: TableData, *, page_number: int | None = None) -> RegionAsset:
    """表格结构落成对象存储资产（规格 7.8：结构化数据与检索文本同时保存）。"""
    payload = json.dumps(
        {
            "title": table.title,
            "columns": list(table.columns),
            "rows": [list(row) for row in table.rows],
            "unit": table.unit,
            "notes": table.notes,
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return RegionAsset(
        content=payload,
        content_type=EXTRACTED_TABLE_MEDIA_TYPE,
        asset_role=AssetRole.EXTRACTED_TABLE,
        filename=f"{table.block_id}.json",
        page_number=page_number,
    )


def store_region(
    store: ResearchAssetStore,
    region: RegionAsset,
    *,
    document_id: str,
    document_version_id: str,
) -> AssetRef:
    """把区域资产写进对象存储，返回可核对的引用。

    键在这里构造而不是由调用方给出：对象键是服务端的命名空间，调用方能决定的是角色与
    文件名，不是路径（Task 4 的键文法）。调用方随后持有的只是引用——原图字节既不进
    索引文本，也不进 Agent 上下文（规格 7.9）。
    """
    key = f"{region.asset_role.value}/{document_id}/{document_version_id}/{region.filename}"
    return store.put(
        key=key,
        content=BytesIO(region.content),
        metadata=AssetMetadata(
            content_type=region.content_type,
            asset_role=region.asset_role,
            filename=region.filename,
            document_id=document_id,
            document_version_id=document_version_id,
            page_number=region.page_number,
            byte_size=len(region.content),
        ),
    )


# --- 内部 ---


def _table_text(table: TableData) -> str | None:
    if not table.rows:
        return None
    lines: list[str] = []
    if table.title:
        lines.append(f"{TABLE_TITLE_PREFIX}{table.title}")
    if table.unit:
        lines.append(f"{UNIT_PREFIX}{table.unit}")
    lines.extend(_row_sentence(table.columns, row) for row in table.rows)
    if table.notes:
        # 注释说明口径与来源，通常是这张表最容易被误读的地方，因此跟着每一行一起被检索。
        lines.append(f"{NOTES_PREFIX}{table.notes}")
    return "\n".join(lines)


def _row_sentence(columns: tuple[str, ...], row: tuple[str, ...]) -> str:
    """一行一句话。第一列是这一行的主语，其余列是它的属性。"""
    label = _row_label(row[0].strip())
    pairs = [
        f"{column} {value.strip()}"
        for column, value in zip(columns[1:], row[1:], strict=False)
        if value.strip()
    ]
    if not pairs:
        return f"{label}。"
    return f"{label}：{CELL_SEPARATOR.join(pairs)}。"


def _row_label(value: str) -> str:
    """规格 7.8 的例子里 `2025` 被读作 `2025 年`：检索问的是哪一年，不是一个数字。"""
    return f"{value} 年" if YEAR_PATTERN.match(value) else value


def _chart_base_text(chart: ChartInput) -> str:
    """文档自身那一层。全部来自原件，因此永远不会是待核验内容。"""
    parts: list[str] = []
    if chart.caption:
        parts.append(chart.caption.strip())
    if chart.legend:
        parts.append(f"{LEGEND_PREFIX}{LIST_SEPARATOR.join(chart.legend)}")
    parts.extend(_axis_text(axis) for axis in chart.axes)
    if chart.unit:
        parts.append(f"{UNIT_PREFIX}{chart.unit}")
    if chart.footnote:
        parts.append(f"{FOOTNOTE_PREFIX}{chart.footnote}")
    if chart.nearby_text:
        parts.append(chart.nearby_text.strip())
    return "\n".join(part for part in parts if part)


def _axis_text(axis: ChartAxis) -> str:
    return f"{AXIS_PREFIX}{axis.label}" + (f"（{axis.unit}）" if axis.unit else "")


def _vision_text(vision: VisualDescription, *, include_values: bool) -> str:
    parts = [f"{DERIVED_DESCRIPTION_PREFIX}{vision.description}"]
    if include_values and vision.reported_values:
        parts.append(f"{VALUES_PREFIX}{VALUE_SEPARATOR.join(vision.reported_values)}")
    return "\n".join(parts)


def _vision_is_usable(vision: VisualDescription, policy: NonTextPolicy) -> tuple[bool, str]:
    """三道校验，顺序即优先级：先看置信度，再看数值的格式，最后看它有没有主语。

    置信度不过只是"不确定"；格式与一致性不过则是"这条描述本身是坏的"。两者都让内容
    留在库里当线索，但都不允许它单独支撑结论——差别只写在警告里，供人工判断。
    """
    if vision.confidence < policy.min_vision_confidence:
        return False, (
            f"the vision description scores {vision.confidence:.2f}, below the "
            f"{policy.min_vision_confidence:.2f} threshold, so it is a lead rather than evidence"
        )
    malformed = [value for value in vision.reported_values if not DIGIT_PATTERN.search(value)]
    if malformed:
        return False, (
            f"the vision value {malformed[0]!r} carries no number and failed the format check; "
            "a value that is not a number cannot be candidate evidence"
        )
    if vision.reported_values and not vision.series:
        return False, (
            "the vision description reports values without naming a series, so the numbers "
            "cannot be attributed to a line and failed the consistency check"
        )
    return True, ""


def _no_source_material(kind: str) -> str:
    return (
        f"this {kind} has no caption, no axis or legend text, no nearby text and no usable "
        "description, so there is nothing to index; its locator and region are kept"
    )


def _region_page(region: RegionAsset | None) -> int | None:
    return region.page_number if region is not None else None


def _page_number(explicit: int | None, region: RegionAsset | None) -> int | None:
    """显式页码优先，其次取区域资产上的：两者说的是同一页，只是来源不同。"""
    return explicit if explicit is not None else _region_page(region)
