"""资料库 API 的请求与响应模型。

有一条约束贯穿整份文件：**浏览器拿不到模型与存储的实现标识**。版本摘要里没有
`index_generation`、`original_file_hash`、嵌入或 OCR 的 provider/model，因为它们描述的是
"我们怎么做的"，而不是"这份资料是什么"。前端的每一个显示项都能在这份文件里找到来源，
而它找不到的那些字段，也正是它不该知道的东西。
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sector_pulse.domain.research_library.models import DocumentType


class DocumentSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: str
    title: str
    document_type: DocumentType
    author: str | None = None
    institution: str | None = None
    source_weight: Decimal
    current_version_id: str | None = None
    created_at: datetime
    deleted_at: datetime | None = None
    purge_after: datetime | None = None


class VersionSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_version_id: str
    version_number: int
    status: str
    uploaded_at: datetime
    published_at: datetime | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    indexed_at: datetime | None = None
    expected_chunk_count: int | None = None
    has_source: bool = False


class JobSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: str
    document_version_id: str
    status: str
    attempt_id: int
    max_attempts: int
    failure_reason: str | None = None
    updated_at: datetime


class AuditEntrySummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    audit_id: str
    document_id: str
    document_version_id: str | None = None
    action: str
    actor: str
    detail: str
    created_at: datetime


class DocumentListItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    document: DocumentSummary
    versions: tuple[VersionSummary, ...]
    latest_job: JobSummary | None = None


class DocumentListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    corpus_generation: str
    documents: tuple[DocumentListItem, ...]


class DocumentDetailResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    document: DocumentSummary
    versions: tuple[VersionSummary, ...]
    jobs: tuple[JobSummary, ...]
    audit: tuple[AuditEntrySummary, ...]


class UploadResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    document: DocumentSummary
    version: VersionSummary
    job: JobSummary
    created: bool
    scan_status: str | None = None
    scan_detail: str | None = None


class DocumentCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str = Field(min_length=1, max_length=300)
    document_type: DocumentType
    author: str | None = Field(default=None, max_length=200)
    institution: str | None = Field(default=None, max_length=200)
    source_weight: Decimal = Field(default=Decimal("0.5"), ge=0, le=1)
    actor: str = Field(min_length=1, max_length=200)


class SourceWeightRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_weight: Decimal = Field(ge=0, le=1)
    actor: str = Field(min_length=1, max_length=200)


class ActorRequest(BaseModel):
    """只带执行者的动作：归档、恢复、重试、重建。"""

    model_config = ConfigDict(frozen=True)

    actor: str = Field(min_length=1, max_length=200)


class RebuildRequest(ActorRequest):
    worker_id: str = Field(default="api-rebuild", min_length=1, max_length=200)


class RunIngestionRequest(BaseModel):
    """推进一步摄取。不需要 actor：这是 worker 的动作，不进治理审计。"""

    model_config = ConfigDict(frozen=True)

    worker_id: str = Field(min_length=1, max_length=200)


class RebuildResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_version_id: str
    index_generation: str
    expected_count: int
    present_count: int
    missing_ids: tuple[str, ...] = ()
    unexpected_ids: tuple[str, ...] = ()
    published: bool


class IndexGapResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_version_id: str
    index_generation: str
    expected_count: int
    present_count: int
    missing_ids: tuple[str, ...] = ()
    unexpected_ids: tuple[str, ...] = ()


class AssetDiscrepancyResponse(BaseModel):
    """权威库登记了、对象存储里对不上的那一项。

    不带 `object_key`：它是服务端派生出来的存储标识，`commands.source` 一路都在避免让它
    落到调用方手里，维护接口不能成为那个例外。定位一项资产，文档 + 版本 + 角色就够了。
    """

    model_config = ConfigDict(frozen=True)

    document_id: str
    document_version_id: str
    kind: str
    expected_sha256: str
    actual_sha256: str | None = None
    detail: str | None = None


class IncompleteVersionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: str
    document_version_id: str
    status: str
    reason: str


class FailedJobResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: str
    document_id: str
    document_version_id: str
    status: str
    attempt_id: int
    failure_reason: str | None = None


class UnreadableVersionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: str
    document_version_id: str
    detail: str


class PurgeCandidateResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: str
    purge_after: datetime


class MaintenanceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    corpus_generation: str
    document_limit: int
    checked_documents: int
    checked_versions: int
    consistent: bool
    repaired: bool
    orphans_removed: int
    index_gaps: tuple[IndexGapResponse, ...] = ()
    asset_discrepancies: tuple[AssetDiscrepancyResponse, ...] = ()
    incomplete_versions: tuple[IncompleteVersionResponse, ...] = ()
    failed_jobs: tuple[FailedJobResponse, ...] = ()
    unreadable_versions: tuple[UnreadableVersionResponse, ...] = ()
    purgeable: tuple[PurgeCandidateResponse, ...] = ()


class ReconcileRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    repair: bool = False
    document_limit: int = Field(default=500, ge=1, le=5000)
    actor: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _repair_is_named(self) -> "ReconcileRequest":
        """删除向量是一次人做的决定，因此 `repair=True` 必须说出来是谁。"""
        if self.repair and not (self.actor or "").strip():
            raise ValueError("repairing the derived index requires an actor")
        return self


class PurgeRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    actor: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=100, ge=1, le=1000)


class PurgeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    purged: tuple[str, ...] = ()


class OutboxRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    worker_id: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=10, ge=1, le=100)


class OutboxResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    events: tuple[str, ...] = ()


class DeletedDocumentResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    document: DocumentSummary


__all__ = [
    "ActorRequest",
    "AssetDiscrepancyResponse",
    "AuditEntrySummary",
    "DeletedDocumentResponse",
    "DocumentCreateRequest",
    "DocumentDetailResponse",
    "DocumentListItem",
    "DocumentListResponse",
    "DocumentSummary",
    "FailedJobResponse",
    "IncompleteVersionResponse",
    "IndexGapResponse",
    "JobSummary",
    "MaintenanceResponse",
    "OutboxRequest",
    "OutboxResponse",
    "PurgeCandidateResponse",
    "PurgeRequest",
    "PurgeResponse",
    "RebuildRequest",
    "RebuildResponse",
    "ReconcileRequest",
    "RunIngestionRequest",
    "SourceWeightRequest",
    "UnreadableVersionResponse",
    "UploadResponse",
    "VersionSummary",
]
