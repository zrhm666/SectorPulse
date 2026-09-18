"""解析流水线：把原件交给适配它的解析器，并统一记下解析口径。

解析器各自只管一种格式。这一层负责三件跨格式的事：

1. **分发**按规范化后的媒体类型，而不是上传方给的原始字符串——`application/PDF`
   和 `application/pdf; charset=binary` 必须落到同一个解析器上。
2. **大小上限在派发之前检查**，因为它的目的就是不去打开那个文件。
3. **版本写进结果**。`research_document_versions.parser_version` 只留得下一个值，而
   决定“要不要重新解析”的从来不是某个提取器单独的行为，而是整条流水线：换一个提取器、
   调一次版面规则，产出的块都会变。`PARSE_PIPELINE_VERSION` 因此代表整套解析口径，
   其中任一环节改变都要提升它。
"""

from collections.abc import Sequence

from sector_pulse.application.research_library.non_text_blocks import (
    normalize_image,
    normalize_table,
)
from sector_pulse.domain.research_library.models import BlockType, DocumentBlock
from sector_pulse.ports.research_models import (
    DEFAULT_PARSE_LIMITS,
    DocumentParser,
    DocumentTooLarge,
    ImageInput,
    NonTextBlock,
    ParsedDocument,
    ParseLimits,
    ParseSource,
    TableData,
    UnsupportedMediaType,
    media_type_of,
)

#: 整套解析口径的版本。任何提取器或版面规则的改变都要提升它（见模块文档）。
PARSE_PIPELINE_VERSION = "parse-pipeline-v1"


class ResearchParsePipeline:
    """按媒体类型分发到解析器，并在入口处统一执行大小上限。"""

    def __init__(
        self, *, parsers: Sequence[DocumentParser], limits: ParseLimits | None = None
    ) -> None:
        self.parsers: tuple[DocumentParser, ...] = tuple(parsers)
        self._limits = limits if limits is not None else DEFAULT_PARSE_LIMITS
        self._by_media_type: dict[str, DocumentParser] = {}
        for parser in self.parsers:
            for media_type in parser.media_types:
                self._by_media_type[media_type_of(media_type)] = parser

    def supports(self, media_type: str) -> bool:
        """这个媒体类型有没有解析器。

        上传门禁要在**落盘之前**问这一句：一份没有任何解析器能读的文件进了对象存储，只会
        在摄取阶段变成一个谁也修不好的失败版本。规范化走的是 `media_type_of`，因此
        `application/PDF; charset=binary` 与 `application/pdf` 在这里是同一个答案。
        """
        return media_type_of(media_type) in self._by_media_type

    @property
    def supported_media_types(self) -> frozenset[str]:
        return frozenset(self._by_media_type)

    def parse(self, source: ParseSource) -> ParsedDocument:
        media_type = media_type_of(source.media_type)
        # 先看有没有解析器：一个 4GB 的 zip 不该先被读一遍再被告知格式不支持。
        parser = self._by_media_type.get(media_type)
        if parser is None:
            raise UnsupportedMediaType(
                f"no parser is registered for {media_type}; "
                f"known types are {', '.join(sorted(self._by_media_type))}"
            )
        if source.byte_size > self._limits.max_bytes:
            raise DocumentTooLarge(
                f"{source.decoded_hint()} exceeds the {self._limits.max_bytes} byte limit"
            )

        parsed = _normalize_non_text(parser.parse(source))
        return parsed.model_copy(update={"parser_version": PARSE_PIPELINE_VERSION})


def _normalize_non_text(parsed: ParsedDocument) -> ParsedDocument:
    """把非文本块换成规范化后的形式。

    规范化发生在流水线而不是提取器里：提取器说"这里有一张表、这里有一张图"，至于它进
    索引时是什么样子、能不能进索引，是同一套规则对所有格式说的同一句话。放进各提取器
    里就变成了每个格式各说各话。

    进不了索引的块会从块流里移除，但留在 `non_text_blocks` 里：块流是给切片和嵌入用的，
    留一个空文本块只会让 Task 7 面对"要不要为一段空文本建 chunk"这个没有正确答案的问题。
    """
    tables = {table.block_id: table for table in parsed.tables}
    blocks: list[DocumentBlock] = []
    non_text: list[NonTextBlock] = []

    for block in parsed.blocks:
        normalized = _normalize_block(block, tables)
        if normalized is None:
            blocks.append(block)
            continue
        non_text.append(_located(normalized, block))
        if normalized.indexable_text is not None:
            blocks.append(block.model_copy(update={"text": normalized.indexable_text}))

    return parsed.model_copy(update={"blocks": tuple(blocks), "non_text_blocks": tuple(non_text)})


def _normalize_block(block: DocumentBlock, tables: dict[str, TableData]) -> NonTextBlock | None:
    """按块类型选择规范化规则；没有对应规则的块原样通过。

    图表与公式暂时没有生产者：当前三个提取器都还不识别它们（PDF 区域裁剪在后续任务里），
    因此这里不为它们写分支——没有输入的分支只会掩盖"这条规则还没接上"这件事。
    """
    table = tables.get(block.block_id)
    if table is not None and block.block_type is BlockType.TABLE:
        return normalize_table(table, page_number=block.page_number)
    if block.block_type is BlockType.IMAGE:
        return normalize_image(
            ImageInput(
                block_id=block.block_id,
                # Markdown 的 alt 就是这张图的说明；没有它，图片就只剩定位。
                caption=block.text or None,
                page_number=block.page_number,
            )
        )
    return None


def _located(normalized: NonTextBlock, block: DocumentBlock) -> NonTextBlock:
    """把块的位置接到规范化结果上。位置不因规范化而改变，只是被带过去。"""
    return normalized.model_copy(
        update={
            "heading_path": block.heading_path,
            "source_span": block.source_span,
            "page_number": (
                block.page_number if block.page_number is not None else normalized.page_number
            ),
        }
    )
