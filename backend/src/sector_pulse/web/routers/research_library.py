"""资料库管理 API（规格 18.1～18.3）。

三条贯穿整份文件的规则：

1. **没接上资料库时是 404 `RESEARCH_LIBRARY_DISABLED`，不是 500**。RAG 默认关闭，因此
   "这个部署没有资料库"是一个正常状态，前端据此显示空态而不是错误态。
2. **上传的请求体是原始字节**，不是 multipart。媒体类型取自 `Content-Type`，文件名取自
   `X-Research-Filename`。这不是风格选择：`python-multipart` 不在依赖里，而把整份文件先
   收进内存再落盘的做法（`UploadFile` 的默认路径）恰恰违反"不把无界文件读进内存"。
   流式落盘、边收边算散列在 `AssetSpool` 里，两者共用同一份上限规则。
3. **治理动作要么在请求里点名 `actor`，要么根本不成立**。Agent 无法通过调用一个端点来
   完成一次治理：它没有一个人名可以填。
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, TypeVar
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from sector_pulse.application.research_library.commands import (
    DocumentNotFound,
    GovernanceRefused,
    JobNotFound,
    SourceUnavailable,
    UploadEmpty,
    UploadKeyConflict,
    UploadScanRejected,
    UploadTarget,
    UploadTargetConflict,
    UploadTargetRequired,
    UploadTypeMismatch,
    UploadUnsupportedType,
    VersionNotFound,
)
from sector_pulse.application.research_library.maintenance import ReconciliationReport
from sector_pulse.application.research_library.services import ResearchLibraryServices
from sector_pulse.domain.research_library.audit import DocumentAuditEntry
from sector_pulse.domain.research_library.models import (
    DocumentType,
    IngestionJob,
    ResearchDocument,
    ResearchDocumentVersion,
)
from sector_pulse.infrastructure.research_library.assets.integrity import AssetSpool
from sector_pulse.ports.research_assets import AssetConflict, AssetIntegrityError
from sector_pulse.ports.research_models import ProviderError
from sector_pulse.ports.vector_index import VectorIndexError
from sector_pulse.storage.ports.research_library import ResearchLibraryConflict
from sector_pulse.web.schemas.research_library import (
    ActorRequest,
    AssetDiscrepancyResponse,
    AuditEntrySummary,
    DeletedDocumentResponse,
    DocumentCreateRequest,
    DocumentDetailResponse,
    DocumentListItem,
    DocumentListResponse,
    DocumentSummary,
    FailedJobResponse,
    IncompleteVersionResponse,
    IndexGapResponse,
    JobSummary,
    MaintenanceResponse,
    OutboxRequest,
    OutboxResponse,
    PurgeCandidateResponse,
    PurgeRequest,
    PurgeResponse,
    RebuildRequest,
    RebuildResponse,
    ReconcileRequest,
    RunIngestionRequest,
    SourceWeightRequest,
    UnreadableVersionResponse,
    UploadResponse,
    VersionSummary,
)

T = TypeVar("T")

SOURCE_CHUNK_BYTES = 64 * 1024

#: 命令错误 → HTTP 状态。表里没有的按 400 处理，而 `code` 一律来自异常自己。
_STATUS_BY_ERROR: tuple[tuple[type[Exception], int], ...] = (
    (DocumentNotFound, 404),
    (VersionNotFound, 404),
    (JobNotFound, 404),
    (SourceUnavailable, 404),
    (UploadEmpty, 422),
    (UploadTargetRequired, 422),
    (UploadTargetConflict, 422),
    (UploadTypeMismatch, 422),
    (UploadScanRejected, 422),
    (UploadUnsupportedType, 415),
    (UploadKeyConflict, 409),
    (GovernanceRefused, 409),
    (ResearchLibraryConflict, 409),
    (AssetConflict, 409),
    (VectorIndexError, 503),
    (ProviderError, 503),
)

#: `_governed` 该接住哪些异常。表里列的就是这一层会翻译的全部类型，所以从这里取，而不是
#: 另写一遍 `except`：两者分开写过一次，结果是 `VectorIndexError` 与 `ProviderError` 那两行
#: 永远走不到——它们是 `RuntimeError` 的另一个分支，不是 `ResearchLibraryCommandError`，
#: 于是"派生索引连不上"在每一个端点上都绕过表，报成 500。表说 503、代码给 500，两张嘴。
_GOVERNED_ERRORS: tuple[type[Exception], ...] = tuple(kind for kind, _ in _STATUS_BY_ERROR)


def _http_error(error: Exception) -> HTTPException:
    """把应用层的错误翻成一个带稳定 `code` 的响应。

    `web/errors.py` 只在 detail 是一个全大写、无空格的单词时把它当成错误码，因此这里传
    detail 的就是那个码本身——与 `shadow_prompts` 等路由同一种做法。
    """
    status = 400
    for kind, mapped in _STATUS_BY_ERROR:
        if isinstance(error, kind):
            status = mapped
            break
    code = getattr(error, "code", "RESEARCH_LIBRARY_ERROR")
    return HTTPException(status, code)


def _governed(route: Callable[..., Any]) -> Callable[..., Any]:
    """把命令错误翻译成 HTTP 响应。

    一次装饰胜过每个端点各写一遍 try/except：错误码到状态码的映射只有一份，而漏写一次
    就会让一个 404 变成一个 500，那种错误在测试里很容易被当成"环境问题"放过。
    """
    if inspect.iscoroutinefunction(route):

        @functools.wraps(route)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await route(*args, **kwargs)
            except _GOVERNED_ERRORS as error:
                raise _http_error(error) from error

        return async_wrapper

    @functools.wraps(route)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return route(*args, **kwargs)
        except _GOVERNED_ERRORS as error:
            raise _http_error(error) from error

    return wrapper


def _document_summary(document: ResearchDocument) -> DocumentSummary:
    return DocumentSummary(
        document_id=document.document_id,
        title=document.title,
        document_type=document.document_type,
        author=document.author,
        institution=document.institution,
        source_weight=document.source_weight,
        current_version_id=document.current_version_id,
        created_at=document.created_at,
        deleted_at=document.deleted_at,
        purge_after=document.purge_after,
    )


def _version_summary(
    version: ResearchDocumentVersion, *, has_source: bool = False
) -> VersionSummary:
    return VersionSummary(
        document_version_id=version.document_version_id,
        version_number=version.version_number,
        status=version.status.value,
        uploaded_at=version.uploaded_at,
        published_at=version.published_at,
        effective_from=version.effective_from,
        effective_to=version.effective_to,
        indexed_at=version.indexed_at,
        expected_chunk_count=version.expected_chunk_count,
        has_source=has_source,
    )


def _job_summary(job: IngestionJob) -> JobSummary:
    return JobSummary(
        job_id=job.job_id,
        document_version_id=job.document_version_id,
        status=job.status.value,
        attempt_id=job.attempt_id,
        max_attempts=job.max_attempts,
        failure_reason=job.failure_reason,
        updated_at=job.updated_at,
    )


def _audit_summary(entry: DocumentAuditEntry) -> AuditEntrySummary:
    return AuditEntrySummary(
        audit_id=entry.audit_id,
        document_id=entry.document_id,
        document_version_id=entry.document_version_id,
        action=entry.action.value,
        actor=entry.actor,
        detail=entry.detail,
        created_at=entry.created_at,
    )


def _maintenance_response(report: ReconciliationReport) -> MaintenanceResponse:
    return MaintenanceResponse(
        corpus_generation=report.corpus_generation,
        document_limit=report.document_limit,
        checked_documents=report.checked_documents,
        checked_versions=report.checked_versions,
        consistent=report.consistent,
        repaired=report.repaired,
        orphans_removed=report.orphans_removed,
        index_gaps=tuple(
            IndexGapResponse(
                document_version_id=gap.document_version_id,
                index_generation=gap.index_generation,
                expected_count=gap.expected_count,
                present_count=gap.present_count,
                missing_ids=gap.missing_ids,
                unexpected_ids=gap.unexpected_ids,
            )
            for gap in report.index_gaps
        ),
        asset_discrepancies=tuple(
            AssetDiscrepancyResponse(
                document_id=item.document_id,
                document_version_id=item.document_version_id,
                kind=item.kind.value,
                expected_sha256=item.expected_sha256,
                actual_sha256=item.actual_sha256,
                detail=item.detail,
            )
            for item in report.asset_discrepancies
        ),
        incomplete_versions=tuple(
            IncompleteVersionResponse(
                document_id=item.document_id,
                document_version_id=item.document_version_id,
                status=item.status.value,
                reason=item.reason,
            )
            for item in report.incomplete_versions
        ),
        failed_jobs=tuple(
            FailedJobResponse(
                job_id=item.job_id,
                document_id=item.document_id,
                document_version_id=item.document_version_id,
                status=item.status.value,
                attempt_id=item.attempt_id,
                failure_reason=item.failure_reason,
            )
            for item in report.failed_jobs
        ),
        unreadable_versions=tuple(
            UnreadableVersionResponse(
                document_id=item.document_id,
                document_version_id=item.document_version_id,
                detail=item.detail,
            )
            for item in report.unreadable_versions
        ),
        purgeable=tuple(
            PurgeCandidateResponse(document_id=item.document_id, purge_after=item.purge_after)
            for item in report.purgeable
        ),
    )


def build_research_library_router(
    services: ResearchLibraryServices | None,
) -> APIRouter:
    """构造资料库路由。`services=None` 表示这个部署没有接上资料库。"""

    def _enabled() -> None:
        """这个部署有没有资料库。

        放在路由级依赖里而不是每个处理函数开头，是因为依赖**先于**请求体校验执行：一个
        没有资料库的部署拿到一份畸形的上传请求时，该说的是"这里没有资料库"，而不是"你的
        请求体有问题"——后者会让调用方去修一份本来就没有终点的请求。
        """
        if services is None:
            raise HTTPException(404, "RESEARCH_LIBRARY_DISABLED")

    router = APIRouter(tags=["research-library"], dependencies=[Depends(_enabled)])

    def stack() -> ResearchLibraryServices:
        # 走到这里 `_enabled` 已经放行，因此这一句只为类型收窄。
        assert services is not None
        return services

    # --- 文档 ---

    @router.get("/api/research-library/documents", response_model=DocumentListResponse)
    async def list_documents(
        include_deleted: bool = False, limit: int = Query(default=100, ge=1, le=500)
    ) -> DocumentListResponse:
        current = stack()
        items: list[DocumentListItem] = []
        for document in current.queries.list_documents(
            include_deleted=include_deleted, limit=limit
        ):
            versions = current.repository.list_versions(document.document_id)
            latest = (
                current.queries.latest_job(versions[-1].document_version_id) if versions else None
            )
            items.append(
                DocumentListItem(
                    document=_document_summary(document),
                    versions=tuple(
                        _version_summary(
                            version,
                            has_source=(
                                current.repository.get_original_asset_key(
                                    version.document_version_id
                                )
                                is not None
                            ),
                        )
                        for version in versions
                    ),
                    latest_job=_job_summary(latest) if latest is not None else None,
                )
            )
        return DocumentListResponse(
            corpus_generation=current.queries.corpus_generation(), documents=tuple(items)
        )

    @router.post("/api/research-library/documents", response_model=DocumentSummary, status_code=201)
    async def create_document(request: DocumentCreateRequest) -> DocumentSummary:
        current = stack()
        document = current.commands.register_document(
            title=request.title,
            document_type=request.document_type,
            actor=request.actor,
            author=request.author,
            institution=request.institution,
            source_weight=request.source_weight,
        )
        return _document_summary(document)

    @router.get(
        "/api/research-library/documents/{document_id}", response_model=DocumentDetailResponse
    )
    @_governed
    async def document_detail(document_id: str) -> DocumentDetailResponse:
        current = stack()
        detail = current.queries.detail(document_id)
        return DocumentDetailResponse(
            document=_document_summary(detail.document),
            versions=tuple(
                _version_summary(
                    version,
                    has_source=(
                        current.repository.get_original_asset_key(version.document_version_id)
                        is not None
                    ),
                )
                for version in detail.versions
            ),
            jobs=tuple(_job_summary(job) for job in detail.jobs),
            audit=tuple(_audit_summary(entry) for entry in detail.audit),
        )

    # --- 上传 ---

    @router.post("/api/research-library/uploads", response_model=UploadResponse, status_code=201)
    @_governed
    async def upload(
        request: Request,
        response: Response,
        target: Annotated[UploadTarget, Query()],
        actor: Annotated[str, Query(min_length=1, max_length=200)],
        x_research_filename: Annotated[str, Header(min_length=1, max_length=500)],
        document_id: str | None = None,
        title: str | None = None,
        document_type: DocumentType | None = None,
        author: str | None = None,
        institution: str | None = None,
        upload_key: str | None = None,
        published_at: datetime | None = None,
        effective_from: datetime | None = None,
        effective_to: datetime | None = None,
    ) -> UploadResponse:
        """收一份文件，登记为一个新文档或某个文档的新版本（规格 7.1）。

        请求体是原始字节，因此所有附加信息都在查询串与请求头里：媒体类型取
        `Content-Type`，文件名取 `X-Research-Filename`。

        文件名按 RFC 3986 解码，与下载那一步的转义互逆。理由和下载那边是同一条：HTTP 头
        只能放 latin-1，而浏览器里 `fetch` 见到非 ASCII 的头值会直接抛
        `TypeError`——一份中文名的报告连请求都发不出去。转义只能在前端做，那么解码就必须
        在这里做；只做一半，权威库里存着的原件名就是一串 `%E5%82%A8…`。
        """
        current = stack()
        media_type = request.headers.get("content-type", "")
        if published_at is not None and published_at.tzinfo is None:
            raise HTTPException(422, "PUBLISHED_AT_REQUIRES_TIMEZONE")
        with AssetSpool(max_bytes=current.max_upload_bytes) as spool:
            try:
                async for chunk in request.stream():
                    spool.write(chunk)
            except AssetIntegrityError as error:
                # 上限是传输层的问题：请求体还没收完就该停下，而不是收完之后再说太大。
                raise HTTPException(413, "UPLOAD_TOO_LARGE") from error
            spooled = spool.finish()
            result = current.commands.upload(
                spooled=spooled,
                media_type=media_type,
                filename=unquote(x_research_filename),
                target=target,
                actor=actor,
                document_id=document_id,
                title=title,
                document_type=document_type,
                author=author,
                institution=institution,
                upload_key=upload_key,
                published_at=published_at,
                effective_from=effective_from,
                effective_to=effective_to,
            )
        if not result.created:
            # 幂等重放：没有新版本产生，因此不是 201。
            response.status_code = 200
        return UploadResponse(
            document=_document_summary(result.document),
            # 问仓库，而不是假定。新建的那一支当然刚写完原件，但幂等重放这一支返回的是**已有**
            # 的版本：它当初可能根本没写进原件（上传被拒、或那次没跑完），照着 True 写回去
            # 等于替它担保。另外三个调用点都是这么问的，这里是第四个。
            version=_version_summary(
                result.version,
                has_source=(
                    current.repository.get_original_asset_key(result.version.document_version_id)
                    is not None
                ),
            ),
            job=_job_summary(result.job),
            created=result.created,
            scan_status=None if result.scan_status is None else result.scan_status.value,
            scan_detail=result.scan_detail,
        )

    @router.get(
        "/api/research-library/documents/{document_id}/versions/{document_version_id}/source"
    )
    @_governed
    async def download_source(document_id: str, document_version_id: str) -> StreamingResponse:
        """原件下载（规格 18.2）。

        私人读取：路由直接按块流出对象，不发预签名链接——链接会绕过鉴权，而这条路本来
        就没有必要绕过它。
        """
        current = stack()
        download = current.queries.source(document_id, document_version_id)
        headers = {"X-Research-Sha256": download.sha256}
        if download.filename is not None:
            # 头部只能是 latin-1，因此按 RFC 3986 转义；前端解码后再显示。
            headers["X-Research-Filename"] = quote(download.filename, safe="")
        return StreamingResponse(
            current.queries.stream(download, chunk_bytes=SOURCE_CHUNK_BYTES),
            media_type=download.content_type,
            headers=headers,
        )

    # --- 治理 ---

    @router.patch(
        "/api/research-library/documents/{document_id}/source-weight",
        response_model=DocumentSummary,
    )
    @_governed
    async def set_source_weight(document_id: str, request: SourceWeightRequest) -> DocumentSummary:
        current = stack()
        document = current.commands.set_source_weight(
            document_id, source_weight=request.source_weight, actor=request.actor
        )
        return _document_summary(document)

    @router.post(
        "/api/research-library/documents/{document_id}/versions/{document_version_id}/archive",
        response_model=VersionSummary,
    )
    @_governed
    async def archive_version(
        document_id: str, document_version_id: str, request: ActorRequest
    ) -> VersionSummary:
        current = stack()
        version = current.commands.archive_version(
            document_id, document_version_id, actor=request.actor
        )
        return _version_summary(
            version,
            has_source=(
                current.repository.get_original_asset_key(version.document_version_id) is not None
            ),
        )

    @router.delete(
        "/api/research-library/documents/{document_id}", response_model=DeletedDocumentResponse
    )
    @_governed
    async def soft_delete_document(
        document_id: str, actor: Annotated[str, Query(min_length=1, max_length=200)]
    ) -> DeletedDocumentResponse:
        current = stack()
        document = current.commands.soft_delete(document_id, actor=actor)
        return DeletedDocumentResponse(document=_document_summary(document))

    @router.post(
        "/api/research-library/documents/{document_id}/restore",
        response_model=DocumentSummary,
    )
    @_governed
    async def restore_document(document_id: str, request: ActorRequest) -> DocumentSummary:
        current = stack()
        document = current.commands.restore(document_id, actor=request.actor)
        return _document_summary(document)

    # --- 摄取 ---

    @router.post("/api/research-library/ingestion-jobs/{job_id}/run", response_model=JobSummary)
    @_governed
    async def run_ingestion(job_id: str, request: RunIngestionRequest) -> JobSummary:
        current = stack()
        return _job_summary(current.commands.run_ingestion(job_id, worker_id=request.worker_id))

    @router.post("/api/research-library/ingestion-jobs/{job_id}/retry", response_model=JobSummary)
    @_governed
    async def retry_ingestion(job_id: str, request: ActorRequest) -> JobSummary:
        current = stack()
        return _job_summary(current.commands.retry_ingestion(job_id, actor=request.actor))

    @router.post(
        "/api/research-library/documents/{document_id}/versions/{document_version_id}/rebuild",
        response_model=RebuildResponse,
    )
    @_governed
    async def rebuild_index(
        document_id: str, document_version_id: str, request: RebuildRequest
    ) -> RebuildResponse:
        current = stack()
        report = current.commands.rebuild_index(
            document_id,
            document_version_id,
            actor=request.actor,
            worker_id=request.worker_id,
        )
        return RebuildResponse(
            document_version_id=document_version_id,
            index_generation=report.generation,
            expected_count=report.expected_count,
            present_count=report.present_count,
            missing_ids=report.missing_ids,
            unexpected_ids=report.unexpected_ids,
            published=report.published,
        )

    # --- 维护 ---

    @router.get("/api/research-library/maintenance", response_model=MaintenanceResponse)
    @_governed
    async def maintenance_report(
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> MaintenanceResponse:
        """只读的核对：GET 不带 `repair`，因此它永远不改动任何东西。"""
        return _maintenance_response(stack().maintenance.reconcile(document_limit=limit))

    @router.post("/api/research-library/maintenance/reconcile", response_model=MaintenanceResponse)
    @_governed
    async def reconcile(request: ReconcileRequest) -> MaintenanceResponse:
        return _maintenance_response(
            stack().maintenance.reconcile(
                repair=request.repair,
                document_limit=request.document_limit,
                actor=request.actor,
            )
        )

    @router.post("/api/research-library/maintenance/outbox", response_model=OutboxResponse)
    @_governed
    async def retry_outbox(request: OutboxRequest) -> OutboxResponse:
        events = stack().maintenance.retry_outbox(worker_id=request.worker_id, limit=request.limit)
        return OutboxResponse(events=tuple(event.event_id for event in events))

    @router.post("/api/research-library/maintenance/purge", response_model=PurgeResponse)
    @_governed
    async def purge(request: PurgeRequest) -> PurgeResponse:
        return PurgeResponse(
            purged=stack().maintenance.purge_expired(actor=request.actor, limit=request.limit)
        )

    return router


__all__ = ["build_research_library_router"]
