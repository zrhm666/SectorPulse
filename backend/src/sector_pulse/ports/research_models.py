"""解析与模型 Provider 的端口。

规格 6 要求解析、OCR、Embedding、Rerank、NLI、抽取和视觉识别都是可插拔接口。这里
描述的是“任何实现都必须做到的事”，因此不出现 PyMuPDF、Milvus、OpenAI 或任何具体
服务的词汇。

全部保持同步：摄取是一条本地 CPU 密集（解析、版面、切片）与网络调用（OCR、Embedding）
交替的流水线，把它拆成 async 只会把线程池的问题散布到每一层。Task 8 的实现负责在
自己的适配器内部决定并发。

这里只声明形状与错误词汇；语义约束（批量顺序、维度一致、JSON 严格解码、置信度上下界、
超时传播）由 Task 8 的 Provider 契约测试来钉。
"""

from collections.abc import Sequence
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import Field, model_validator

from sector_pulse.domain.research_library.models import (
    BlockType,
    BoundingBox,
    DocumentBlock,
    ExtractionMethod,
    Record,
    SourceSpan,
)
from sector_pulse.domain.research_library.retrieval import ExtractedClaim, NliRelation
from sector_pulse.ports.research_assets import AssetRole

# --- 错误词汇 ---


class ParseError(RuntimeError):
    """解析层的基准错误。"""


class UnsupportedMediaType(ParseError):
    """没有适配这个媒体类型的解析器。"""


class PasswordProtectedDocument(ParseError):
    """文档被加密。

    规格 18.1：返回“需要密码”，不尝试破解。因此这是一个终态失败，调用方不该重试。
    """


class DocumentTooLarge(ParseError):
    """超过配置的字节上限。"""


class TooManyPages(ParseError):
    """超过配置的页数上限。"""


class UnreadableDocument(ParseError):
    """文件无法按它声明的类型打开。"""


class OcrUnavailable(ParseError):
    """页面需要 OCR，但没有可用的 Provider。"""


# --- 解析输入 ---


class ParseLimits(Record):
    """规格 18.1 的大小与页数上限。

    在解析之前检查，而不是在解析过程中：一个 4GB 的 PDF 不该先被打开再被拒绝。
    """

    max_bytes: int = Field(gt=0)
    max_pages: int = Field(gt=0)


#: 未显式配置时的上限。放在端口层是为了让流水线和各个提取器用同一个数：两处各写一份
#: 意味着“上限”会随调用路径变化，而调用方无法知道哪一份生效了。
DEFAULT_PARSE_LIMITS = ParseLimits(max_bytes=64 * 1024 * 1024, max_pages=500)


class ParseSource(Record):
    """待解析的一份原件。

    `content` 是字节而不是流：解析器需要在同一份内容上做多次遍历（探测加密、计页、
    提取、必要时渲染页面图像），而上传路径已经在进入这里之前把大小限制和散列核对过了。
    """

    media_type: str = Field(min_length=1)
    content: bytes
    filename: str | None = None

    @property
    def byte_size(self) -> int:
        return len(self.content)

    def decoded_hint(self) -> str:
        """用于错误信息的简短描述，不含正文（正文可能很大，也可能是敏感内容）。"""
        return f"{self.media_type} ({self.byte_size} bytes)"


# --- OCR ---


class OcrWord(Record):
    text: str = Field(min_length=1)
    bounding_box: BoundingBox
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _text_is_meaningful(self) -> "OcrWord":
        if not self.text.strip():
            raise ValueError("an OCR word must not be blank")
        return self


class OcrPage(Record):
    """一页的 OCR 结果。"""

    page_number: int = Field(ge=1)
    words: tuple[OcrWord, ...] = ()
    provider: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)

    @property
    def text(self) -> str:
        return "\n".join(word.text for word in self.words)


# --- 解析输出 ---


class ChartAxis(Record):
    label: str = Field(min_length=1)
    unit: str | None = None


class VisualDescription(Record):
    """视觉模型对一张图表或图片的结构化描述。

    规格 7.9：低置信度的视觉结论只能作为待核验线索。因此 `confidence` 是必填，
    调用方据 `min_vision_confidence` 决定是否让它的数值成为候选证据。

    定义在 `ChartInput`/`ImageInput` 之前：它们是它的消费者，而注解在类体执行时求值。
    """

    description: str = Field(min_length=1)
    caption: str | None = None
    chart_type: str | None = None
    x_axis: ChartAxis | None = None
    y_axis: ChartAxis | None = None
    series: tuple[str, ...] = ()
    reported_values: tuple[str, ...] = ()
    notes: str | None = None
    confidence: float = Field(ge=0, le=1)
    provider: str = Field(min_length=1)
    model_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def _description_is_meaningful(self) -> "VisualDescription":
        if not self.description.strip():
            raise ValueError("a visual description must not be blank")
        return self


class TableData(Record):
    """结构化表格（规格 7.8）。

    `block_id` 把它接回产生它的 `DocumentBlock`：结构化数据与可检索文本是同一张表的
    两个出口，各自服务于不同的读者——切片进索引，结构进对象存储供人工核对。
    """

    block_id: str = Field(min_length=1)
    columns: tuple[str, ...] = Field(min_length=1)
    rows: tuple[tuple[str, ...], ...] = ()
    title: str | None = None
    unit: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _every_row_has_one_cell_per_column(self) -> "TableData":
        for row in self.rows:
            if len(row) != len(self.columns):
                raise ValueError(
                    f"a row has {len(row)} cells for {len(self.columns)} columns; "
                    "a shifted row would be indexed as if its values belonged to other columns"
                )
        return self


class RegionAsset(Record):
    """需要落到对象存储的区域资产：图表裁剪、表格结构、公式截图。

    `content` 只在这里存在。索引文本与 Agent 上下文都不带字节（规格 7.9：Agent 默认只
    接收结构化描述和来源定位），原图留在对象存储里供人工核对与重新解析。
    """

    content: bytes = Field(min_length=1)
    content_type: str = Field(min_length=1)
    asset_role: AssetRole
    filename: str = Field(min_length=1)
    page_number: int | None = Field(default=None, ge=1)


class NonTextPolicy(Record):
    """非文本块规范化时可配置的部分。默认值与 `RagSettings.min_vision_confidence` 一致。"""

    min_vision_confidence: float = Field(default=0.6, gt=0, le=1)


class ChartInput(Record):
    """图表的两个来源层（规格 7.9）。

    基础层永远来自文档自身——图题、图例、坐标轴、脚注、附近正文——因此没有配置视觉
    Provider 时图表依然可检索。视觉层可能不存在，存在时也只是一条线索。
    """

    block_id: str = Field(min_length=1)
    caption: str | None = None
    legend: tuple[str, ...] = ()
    axes: tuple[ChartAxis, ...] = ()
    unit: str | None = None
    footnote: str | None = None
    nearby_text: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    origin: ExtractionMethod = ExtractionMethod.PARSER_DERIVED
    vision: VisualDescription | None = None
    region: RegionAsset | None = None


class ImageInput(Record):
    """普通图片（规格 7.10）。

    `caption` 是文档自带的说明，可能是 Markdown 的 alt。`is_decorative` 是调用方的判断：
    版式识别（它是否位于页眉、是否与正文同宽）不在这层的视野里。
    """

    block_id: str = Field(min_length=1)
    caption: str | None = None
    is_decorative: bool = False
    page_number: int | None = Field(default=None, ge=1)
    origin: ExtractionMethod = ExtractionMethod.PARSER_DERIVED
    vision: VisualDescription | None = None
    region: RegionAsset | None = None


class FormulaNotation(StrEnum):
    """公式被可靠提取时的记法。没有记法就不算可靠提取（规格 7.11）。"""

    UNICODE = "unicode"
    LATEX = "latex"
    MATHML = "mathml"


class FormulaVariable(Record):
    symbol: str = Field(min_length=1)
    description: str = Field(min_length=1)


class FormulaInput(Record):
    block_id: str = Field(min_length=1)
    expression: str | None = None
    notation: FormulaNotation | None = None
    name: str | None = None
    variables: tuple[FormulaVariable, ...] = ()
    context: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    origin: ExtractionMethod = ExtractionMethod.PARSER_DERIVED
    region: RegionAsset | None = None

    @model_validator(mode="after")
    def _an_expression_declares_how_it_was_read(self) -> "FormulaInput":
        if (self.expression is None) != (self.notation is None):
            raise ValueError(
                "a formula must carry both its expression and its notation, or neither"
            )
        return self


class NonTextBlock(Record):
    """非文本块规范化后的结果（规格 7.8–7.11）。

    `indexable_text is None` 是"这块内容不进文本索引"的唯一表达：内容仍然带着定位与
    区域引用，供人工核对，但不参与向量与 BM25 检索，也就不会回应它回答不了的问题。
    """

    block_id: str = Field(min_length=1)
    block_type: BlockType
    content_origin: ExtractionMethod
    indexable_text: str | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)
    requires_verification: bool = False
    page_number: int | None = Field(default=None, ge=1)
    heading_path: tuple[str, ...] = ()
    source_span: SourceSpan | None = None
    table: TableData | None = None
    region: RegionAsset | None = None
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _only_a_table_carries_table_structure(self) -> "NonTextBlock":
        if (self.table is not None) != (self.block_type is BlockType.TABLE):
            raise ValueError("table structure belongs to a table block and to nothing else")
        return self


class ParsedDocument(Record):
    """一次解析的完整结果。

    `warnings` 是这套结构里最重要的一列：它记录“哪些内容没有被读到”。扫描页没有配置
    OCR 时，页面上没有 block 是事实，但把这件事只表达成“没有 block”会让残缺的文档
    看起来像完整的文档。
    """

    blocks: tuple[DocumentBlock, ...] = ()
    #: 提取器识别出的表格结构，按 `block_id` 接回对应的块。提取器负责"这里有一张表"，
    #: 规范化（Task 6）负责它进索引时是什么样子。
    tables: tuple[TableData, ...] = ()
    #: 规范化后的非文本块。表格、图表、图片和公式都在这里留一份：块流是给索引用的，
    #: 这里的内容是给"这块到底能不能被当成证据"这个问题用的。
    non_text_blocks: tuple[NonTextBlock, ...] = ()
    page_count: int = Field(default=0, ge=0)
    parser_name: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    ocr_provider: str | None = None
    ocr_model_version: str | None = None
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _ocr_attribution_is_all_or_nothing(self) -> "ParsedDocument":
        if (self.ocr_provider is None) != (self.ocr_model_version is None):
            raise ValueError("OCR attribution must name both the provider and the model")
        return self

    @model_validator(mode="after")
    def _blocks_are_ordered_and_identified(self) -> "ParsedDocument":
        ids = [block.block_id for block in self.blocks]
        if len(set(ids)) != len(ids):
            raise ValueError("block ids must be unique across the document")
        orders = [block.block_order for block in self.blocks]
        if orders != sorted(orders):
            raise ValueError("blocks must be ordered by block_order")
        return self

    def blocks_for_page(self, page_number: int) -> tuple[DocumentBlock, ...]:
        return tuple(block for block in self.blocks if block.page_number == page_number)

    @property
    def native_block_count(self) -> int:
        return sum(1 for block in self.blocks if block.extraction_method.value == "native")


@runtime_checkable
class TokenCounter(Protocol):
    """把一段文本折算成 token 数。

    切片预算以 token 计（规格 8），但不下载模型：词表属于部署环境，块却要在任何环境里
    都切成同一个样子。因此分词器是一个注入的端口，`version` 参与 chunk ID 的构造——
    换一个分词器意味着换一套切法，沿用旧 ID 会让 Milvus 里留着按旧切法切出来的实体。
    """

    @property
    def version(self) -> str: ...

    def count(self, text: str) -> int: ...


@runtime_checkable
class DocumentParser(Protocol):
    """一种源格式的解析器。"""

    @property
    def name(self) -> str: ...

    @property
    def media_types(self) -> frozenset[str]: ...

    def parse(self, source: ParseSource) -> ParsedDocument: ...


@runtime_checkable
class OcrProvider(Protocol):
    """按页 OCR。只接收已经判定为需要 OCR 的页面。"""

    def recognize_page(
        self, *, page_number: int, page_image: bytes, width: int, height: int
    ) -> OcrPage: ...


# --- Provider 调用错误词汇 ---
#
# 与解析层的错误分开：解析失败说的是"这份文件读不了"，是一次就定性的；Provider 失败说的
# 是"这次调用没成"，同一份输入重试一次可能就成了。把两者混在一个异常里，重试策略就只能
# 靠匹配错误字符串来猜。
#
# `retriable` 是这套词汇里唯一有语义的字段：上层的预算与重试（Task 14）据它决定是再花
# 一次钱还是就此停下。因此每个子类都写死自己的值，调用方没有机会改动它。


class ProviderError(RuntimeError):
    """模型 Provider 的基准错误。"""

    def __init__(self, message: str, *, retriable: bool) -> None:
        super().__init__(message)
        self.retriable = retriable


class ProviderTimeout(ProviderError):
    """调用在超时内没有得到响应。重试有意义：下一次可能就快。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, retriable=True)


class ProviderUnavailable(ProviderError):
    """网络失败、5xx，或重试用尽后的 429。重试有意义，但要在预算之内。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, retriable=True)


class ProviderRejected(ProviderError):
    """Provider 拒绝了这次请求（4xx 或空批次）。重试只会把同一个错误再问一遍。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, retriable=False)


class ProviderResponseInvalid(ProviderError):
    """响应不是约定的形状，或其中的值越界。

    绝不降级成"能解析多少算多少"：一个置信度读错字段的结论会以证据的身份进入报告，
    而那时已经没有人能看出它是坏的。
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, retriable=False)


class ProviderNotConfigured(ProviderError):
    """这个输入没有对应的 Provider 或 Fixture。

    单独成一类，是因为它与"Provider 说没有"是两件事：前者是部署缺了一件东西，后者
    是一个结论。
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, retriable=False)


# --- 模型 Provider 的结果形状 ---


class EmbeddingBatch(Record):
    """一批文本的向量；顺序必须与输入顺序一致。"""

    vectors: tuple[tuple[float, ...], ...]
    dimension: int = Field(gt=0)
    provider: str = Field(min_length=1)
    model_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def _vectors_are_rectangular_and_non_empty(self) -> "EmbeddingBatch":
        if not self.vectors:
            raise ValueError("an embedding batch must contain at least one vector")
        for vector in self.vectors:
            if len(vector) != self.dimension:
                raise ValueError("every vector in a batch must have the declared dimension")
        return self


class RerankResult(Record):
    """与输入文档一一对应的重排分数。"""

    scores: tuple[float, ...]
    provider: str = Field(min_length=1)
    model_version: str = Field(min_length=1)

    def best_order(self) -> tuple[int, ...]:
        """按分数降序返回输入下标；同分时保持原下标顺序，保证可复现。"""
        return tuple(sorted(range(len(self.scores)), key=lambda i: (-self.scores[i], i)))


class NliVerdict(Record):
    """一次 NLI 判定。`UNCERTAIN` 是结论，不是缺省。"""

    relation: NliRelation
    confidence: float = Field(ge=0, le=1)
    provider: str = Field(min_length=1)
    model_version: str = Field(min_length=1)


class ClaimSourceChunk(Record):
    chunk_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class ClaimExtractionRequest(Record):
    """查询期抽取的输入：一个问题，加上有限的一段候选正文。"""

    question: str = Field(min_length=1)
    chunks: tuple[ClaimSourceChunk, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _question_is_meaningful(self) -> "ClaimExtractionRequest":
        if not self.question.strip():
            raise ValueError("a claim extraction request must carry a real question")
        return self


# --- 模型 Provider 端口 ---


@runtime_checkable
class EmbeddingProvider(Protocol):
    def embed(self, texts: Sequence[str]) -> EmbeddingBatch: ...


@runtime_checkable
class RerankerProvider(Protocol):
    def rerank(self, *, query: str, documents: Sequence[str]) -> RerankResult: ...


@runtime_checkable
class NliProvider(Protocol):
    def classify(self, *, premise: str, hypothesis: str) -> NliVerdict: ...


@runtime_checkable
class ClaimExtractorProvider(Protocol):
    def extract(self, request: ClaimExtractionRequest) -> tuple[ExtractedClaim, ...]: ...


@runtime_checkable
class VisionDocumentProvider(Protocol):
    def describe(
        self, *, image: bytes, media_type: str, context: str | None = None
    ) -> VisualDescription: ...


def media_type_of(value: str | None) -> str:
    """规范化媒体类型：丢掉 `;charset=` 参数并统一大小写。

    上传方给的 `application/PDF; charset=binary` 和 `application/pdf` 必须落到同一个
    解析器上，否则“可插拔”在真实流量下会变成一个 415。
    """
    if not value:
        return "application/octet-stream"
    return value.split(";", 1)[0].strip().lower()
