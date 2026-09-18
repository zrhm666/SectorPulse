"""内部研究资料库的不可变值模型。

三组状态刻意使用三个互不相同的枚举（规格 7.2）：摄取任务状态、文档版本状态和
Milvus 索引状态。混用它们会让“已发布”同时表示三件不同的事，是本设计里最容易
退化的地方，因此模型层面直接拒绝跨组取值。
"""

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

type BoundingBox = tuple[float, float, float, float]


def utc_now() -> datetime:
    return datetime.now(UTC)


class Record(BaseModel):
    """本包所有值模型的基类：不可变且拒绝未知字段。"""

    model_config = ConfigDict(frozen=True, extra="forbid")


class DocumentVersionStatus(StrEnum):
    PROCESSING = "PROCESSING"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"
    FAILED = "FAILED"
    DELETED = "DELETED"
    PURGED = "PURGED"


class IndexState(StrEnum):
    """Milvus 实体状态，只用于减少无效候选；可见性最终由 PostgreSQL 复核。"""

    STAGED = "STAGED"
    PUBLISHED = "PUBLISHED"


class IngestionStatus(StrEnum):
    RECEIVED = "RECEIVED"
    VALIDATING = "VALIDATING"
    PARSING = "PARSING"
    NORMALIZING = "NORMALIZING"
    CHUNKING = "CHUNKING"
    EMBEDDING = "EMBEDDING"
    INDEXING = "INDEXING"
    VERIFYING = "VERIFYING"
    PUBLISHED = "PUBLISHED"
    RETRYABLE_FAILED = "RETRYABLE_FAILED"
    PERMANENT_FAILED = "PERMANENT_FAILED"
    CANCELLED = "CANCELLED"


class ExtractionMethod(StrEnum):
    NATIVE = "native"
    OCR = "ocr"
    PARSER_DERIVED = "parser_derived"
    VISION_DERIVED = "vision_derived"


class BlockType(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    CHART = "chart"
    IMAGE = "image"
    FIGURE_CAPTION = "figure_caption"
    FORMULA = "formula"
    CODE = "code"


TEXTUAL_BLOCK_TYPES = (
    BlockType.HEADING,
    BlockType.PARAGRAPH,
    BlockType.LIST,
    BlockType.TABLE,
    BlockType.CODE,
    BlockType.FIGURE_CAPTION,
)


class ChunkType(StrEnum):
    TEXT = "text"
    TABLE = "table"
    CODE = "code"
    FORMULA = "formula"
    CHART = "chart"
    IMAGE_CAPTION = "image_caption"


class ChunkEmbeddingStatus(StrEnum):
    PENDING = "pending"
    EMBEDDED = "embedded"
    FAILED = "failed"


class DocumentType(StrEnum):
    REPORT = "report"
    HISTORICAL_ARTICLE = "historical_article"
    ANNOUNCEMENT = "announcement"
    OTHER = "other"


class SourceSpan(Record):
    """规范化文本内的半开区间 `[start, end)`。"""

    start: int = Field(ge=0)
    end: int = Field(ge=1)

    @model_validator(mode="after")
    def _span_must_be_forward(self) -> Self:
        if self.end <= self.start:
            raise ValueError("span end must be greater than span start")
        return self


class SourceLocator(Record):
    """从切片回到上传原文件的定位信息。

    至少要有页码、章节路径或源 block 之一；完全无法定位的切片不能进入资料库。
    """

    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    section_path: tuple[str, ...] = ()
    block_ids: tuple[str, ...] = ()
    spans: tuple[SourceSpan, ...] = ()
    bounding_boxes: tuple[BoundingBox, ...] = ()

    @model_validator(mode="after")
    def _require_lineage(self) -> Self:
        if self.page_start is None and not self.section_path and not self.block_ids:
            raise ValueError(
                "a chunk must keep source lineage: page, section path or source block id"
            )
        if self.page_start is None and self.page_end is not None:
            raise ValueError("page_end requires a page_start")
        if (
            self.page_start is not None
            and self.page_end is not None
            and self.page_end < self.page_start
        ):
            raise ValueError("page range end must not precede page start")
        return self


class DocumentBlock(Record):
    """解析产出的统一结构块。

    图片和图表可以没有自身文本（无图题的图仍然有定位信息，只是不可检索）；
    承载正文的块则不能为空白。
    """

    block_id: str = Field(min_length=1)
    block_type: BlockType
    text: str = ""
    heading_path: tuple[str, ...] = ()
    page_number: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    block_order: int = Field(ge=0)
    bounding_box: BoundingBox | None = None
    #: 本块文本在解析器规范化后文本中的字符区间（规格 7.6/7.7 要求保留源字符范围）。
    #: PDF 用页码与坐标定位，因此这里是 None；Markdown 与 TXT 没有坐标，只能靠它定位。
    source_span: SourceSpan | None = None
    extraction_method: ExtractionMethod
    extraction_confidence: float = Field(default=1.0, ge=0, le=1)
    source_asset_ref: str | None = None

    @model_validator(mode="after")
    def _text_matches_block_type(self) -> Self:
        if not self.text.strip() and self.block_type in TEXTUAL_BLOCK_TYPES:
            raise ValueError(f"a {self.block_type} block must carry text")
        if (
            self.page_number is not None
            and self.page_end is not None
            and self.page_end < self.page_number
        ):
            raise ValueError("page range end must not precede page start")
        return self


class ResearchChunk(Record):
    chunk_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_version_id: str = Field(min_length=1)
    parent_chunk_id: str | None = None
    chunk_type: ChunkType = ChunkType.TEXT
    content: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    source: SourceLocator
    content_origin: ExtractionMethod
    confidence: float = Field(default=1.0, ge=0, le=1)
    requires_verification: bool = False
    embedding_status: ChunkEmbeddingStatus = ChunkEmbeddingStatus.PENDING
    created_at: AwareDatetime

    @model_validator(mode="after")
    def _content_is_meaningful(self) -> Self:
        if not self.content.strip():
            raise ValueError("chunk content must not be blank")
        for span in self.source.spans:
            if span.end > len(self.content):
                raise ValueError("chunk content span must stay inside the chunk content")
        return self


class ResearchDocument(Record):
    document_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    document_type: DocumentType
    author: str | None = None
    institution: str | None = None
    source_weight: Decimal = Field(default=Decimal("0.5"), ge=0, le=1)
    current_version_id: str | None = None
    # 第一版固定为全局资料库；字段预留，但取值暂时只有一个。
    visibility_scope: Literal["GLOBAL"] = "GLOBAL"
    owner_id: str | None = None
    access_tags: tuple[str, ...] = ()
    created_at: AwareDatetime
    deleted_at: AwareDatetime | None = None
    purge_after: AwareDatetime | None = None

    @model_validator(mode="after")
    def _purge_schedule_follows_deletion(self) -> Self:
        if self.purge_after is None:
            return self
        if self.deleted_at is None:
            raise ValueError("purge_after requires a deleted_at timestamp")
        if self.purge_after <= self.deleted_at:
            raise ValueError("purge_after must be later than deleted_at")
        return self

    def is_retrievable(self) -> bool:
        return self.deleted_at is None


class ResearchDocumentVersion(Record):
    document_version_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    version_number: int = Field(ge=1)
    status: DocumentVersionStatus = DocumentVersionStatus.PROCESSING
    published_at: AwareDatetime | None = None
    effective_from: AwareDatetime | None = None
    effective_to: AwareDatetime | None = None
    uploaded_at: AwareDatetime
    original_file_hash: str = Field(min_length=1)
    parser_version: str | None = None
    chunking_policy_version: str | None = None
    ocr_provider: str | None = None
    ocr_model_version: str | None = None
    embedding_provider: str | None = None
    embedding_model_version: str | None = None
    index_generation: str | None = None
    expected_chunk_count: int | None = Field(default=None, ge=0)
    indexed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _effective_window_is_forward(self) -> Self:
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise ValueError("effective_to must not precede effective_from")
        return self

    @model_validator(mode="after")
    def _active_version_is_fully_published(self) -> Self:
        """规格 10：只有索引已发布并复核过的版本才能成为 ACTIVE。"""
        if self.status is not DocumentVersionStatus.ACTIVE:
            return self
        if self.index_generation is None:
            raise ValueError("an ACTIVE version must record the index_generation it came from")
        if self.indexed_at is None:
            raise ValueError("an ACTIVE version must record when it was indexed")
        if self.expected_chunk_count is None:
            raise ValueError("an ACTIVE version must record its expected_chunk_count")
        return self

    def is_retrievable(self) -> bool:
        return self.status is DocumentVersionStatus.ACTIVE


FAILURE_INGESTION_STATUSES = (
    IngestionStatus.RETRYABLE_FAILED,
    IngestionStatus.PERMANENT_FAILED,
)


class IngestionJob(Record):
    job_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_version_id: str = Field(min_length=1)
    status: IngestionStatus = IngestionStatus.RECEIVED
    attempt_id: int = Field(default=0, ge=0)
    worker_id: str | None = None
    lease_expires_at: AwareDatetime | None = None
    max_attempts: int = Field(default=3, ge=1, le=10)
    failure_reason: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def _lease_has_an_owner(self) -> Self:
        if self.lease_expires_at is not None and self.worker_id is None:
            raise ValueError("a job lease must name the worker that holds it")
        if self.worker_id is not None and self.lease_expires_at is None:
            raise ValueError("a worker_id without a job lease is meaningless")
        if self.attempt_id > self.max_attempts:
            raise ValueError("attempt_id must not exceed max_attempts")
        return self

    @model_validator(mode="after")
    def _failure_reason_matches_status(self) -> Self:
        failed = self.status in FAILURE_INGESTION_STATUSES
        if failed and not self.failure_reason:
            raise ValueError("failure_reason is required for a failed ingestion job")
        if not failed and self.failure_reason is not None:
            raise ValueError("failure_reason is only meaningful for a failed ingestion job")
        return self

    def holds_lease_for(self, worker_id: str, attempt: int) -> bool:
        return self.worker_id == worker_id and self.attempt_id == attempt


class OutboxOperation(StrEnum):
    PUBLISH_GENERATION = "publish_generation"
    DELETE_GENERATION = "delete_generation"


class OutboxStatus(StrEnum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    DONE = "DONE"
    FAILED = "FAILED"


class IndexOutboxEvent(Record):
    """PostgreSQL 记录、由派生索引 worker 兑现的索引变更意图。

    规格 10 要求可见性由 PostgreSQL 最终确认：这里持久化的是“要对 Milvus 做什么”，
    而不是“Milvus 已经做了什么”。因此事件先落库、再执行副作用，进程崩溃只是让事件
    留在可认领状态，不会让索引静默落后于权威状态。
    """

    event_id: str = Field(min_length=1)
    document_version_id: str = Field(min_length=1)
    index_generation: str = Field(min_length=1)
    operation: OutboxOperation
    status: OutboxStatus = OutboxStatus.PENDING
    payload: dict[str, object] = Field(default_factory=dict)
    attempt_count: int = Field(default=0, ge=0)
    claimed_by: str | None = None
    claimed_at: AwareDatetime | None = None
    available_at: AwareDatetime
    last_error: str | None = None
    created_at: AwareDatetime

    @model_validator(mode="after")
    def _claim_is_all_or_nothing(self) -> Self:
        if (self.claimed_by is None) != (self.claimed_at is None):
            raise ValueError("a claimed event must record both the claimer and the claim time")
        if self.status is OutboxStatus.CLAIMED and self.claimed_by is None:
            raise ValueError("a CLAIMED event must name the worker that claimed it")
        if self.status is not OutboxStatus.CLAIMED and self.claimed_by is not None:
            raise ValueError("only a CLAIMED event may still be held by a worker")
        return self
