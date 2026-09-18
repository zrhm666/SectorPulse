"""资料库治理命令与读取视图：**只有用户与 API 层能做的事**（规格 7.1、16、17、18.3）。

规格 4 把这条边界写成了硬约束：Agent 不能上传、删除、恢复、确认版本关系或调整来源权重。
边界靠两件事维持，缺一不可：

1. 本模块只被 `web/` 与接线层引用（`backend/tests/integration/test_research_library_api.py`
   里有一条静态检查守着它）；
2. 交给 A2 的是 `ResearchLibraryServices.agent_services()` 那个窄接口，它只有检索、
   只读仓库与上限。

几件刻意为之的事：

- **对象键由服务端构造**。用户给的文件名只参与两处：判断扩展名、以及键的最后一段，而且
  那一段先被压成安全字符集。绝不把用户字符串直接拼进键（规格 16.1）。
- **上传先落盘、再判门禁、最后才落库**。宽度与散列在上传过程中算出来，因此"太大"是在
  读满内存之前就发生的失败，而不是写完之后才发现的。
- **每一次用户动作都留审计**，包括被拒绝的上传：被拒的东西也是发生过的事。
- **幂等只由 SHA256 + 上传键决定**（规格 7.1）。标题、作者、向量相似度都不参与"这算不算
  同一份文件"的判断——猜版本关系正是规格明令禁止的那件事。
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from sector_pulse.application.research_library.ingestion import UnrecoverableIngestionError
from sector_pulse.domain.research_library.audit import (
    DocumentAuditAction,
    DocumentAuditEntry,
    document_audit_entry,
)
from sector_pulse.domain.research_library.models import (
    DocumentType,
    DocumentVersionStatus,
    IndexOutboxEvent,
    IngestionJob,
    IngestionStatus,
    OutboxOperation,
    Record,
    ResearchDocument,
    ResearchDocumentVersion,
)
from sector_pulse.infrastructure.research_library.assets.integrity import SpooledAsset
from sector_pulse.ports.research_assets import (
    AssetMetadata,
    AssetNotFound,
    AssetRole,
    ResearchDocumentAsset,
    ScanStatus,
)
from sector_pulse.ports.research_models import media_type_of
from sector_pulse.ports.vector_index import IndexVerification
from sector_pulse.storage.ports.research_library import ResearchLibraryConflict

if TYPE_CHECKING:  # pragma: no cover - 只为类型
    from sector_pulse.application.research_library.services import ResearchLibraryServices

#: 审计详情里允许出现的字符数。审计要回答"发生了什么"，不是"原文是什么"。
AUDIT_DETAIL_CHARS = 120

#: 对象键最后一段允许的长度。键整体不超过 255，而用户文件名可以很长。
OBJECT_NAME_CHARS = 80

#: 扩展名 → 规范化媒体类型。上传方给的文件名只在这里参与判断。
EXTENSION_MEDIA_TYPES: Mapping[str, str] = {
    ".pdf": "application/pdf",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
}

#: 同一件事的多种写法 → 规范写法。`text/x-plain` 与 `text/plain` 是同一件事，因此扩展名
#: 核对与落库的 `content_type` 都先用这一份收敛：让两种写法各自走完流程，会让"同一个
#: 解析器"这件事在库里看起来像两个不同的输入。
CANONICAL_MEDIA_TYPES: Mapping[str, str] = {
    "application/text": "text/plain",
    "text/x-plain": "text/plain",
    "application/markdown": "text/markdown",
    "text/x-markdown": "text/markdown",
}

#: 可识别格式的魔数。门禁的用途只有一个：在这份文件被登记成版本之前就说出"它不是它
#: 声称的那种东西"，因为一份没有解析器读得懂的文件会在摄取阶段变成一个谁也修不好的
#: 永久失败版本。
MAGIC_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "application/pdf"),
    (b"PK\x03\x04", "application/zip"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "application/x-ole-storage"),
    (b"%!PS", "application/postscript"),
    (b"\x1f\x8b", "application/gzip"),
)

#: 必须命中魔数才算数对的媒体类型。`.pdf` 的字节里没有 `%PDF-` 就不是 PDF，无论文件名
#: 叫什么；反过来，一份 TXT 只要不像上面任何一种已知格式，就按文本收下——解码阶梯
#: （UTF-8 → GB18030 → latin-1）是解析器的事，上传门禁不做编码猜测。
MAGIC_REQUIRED_MEDIA_TYPES = frozenset({"application/pdf"})

MAGIC_HEAD_BYTES = 16

#: 键的段里允许出现的字符，与 `validate_asset_key` 同一套。
_UNSAFE_IN_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_WHITESPACE = re.compile(r"\s+")


class ResearchLibraryCommandError(RuntimeError):
    """治理命令的基准错误。`code` 是稳定的客户端标识，不是给日志看的。"""

    code = "RESEARCH_LIBRARY_ERROR"


class DocumentNotFound(ResearchLibraryCommandError):
    code = "DOCUMENT_NOT_FOUND"


class VersionNotFound(ResearchLibraryCommandError):
    code = "VERSION_NOT_FOUND"


class JobNotFound(ResearchLibraryCommandError):
    code = "INGESTION_JOB_NOT_FOUND"


class SourceUnavailable(ResearchLibraryCommandError):
    """原件不在对象存储里（从未写入、或已经被清理）。"""

    code = "SOURCE_NOT_AVAILABLE"


class GovernanceRefused(ResearchLibraryCommandError):
    """动作本身合法，但对这份文档的当前状态不成立。"""

    code = "GOVERNANCE_REFUSED"


class UploadRejected(ResearchLibraryCommandError):
    """上传门禁的拒绝。"""

    code = "UPLOAD_REJECTED"


class UploadTargetRequired(UploadRejected):
    code = "UPLOAD_TARGET_REQUIRED"


class UploadTargetConflict(UploadRejected):
    code = "UPLOAD_TARGET_CONFLICT"


class UploadEmpty(UploadRejected):
    code = "UPLOAD_EMPTY"


class UploadUnsupportedType(UploadRejected):
    code = "UPLOAD_UNSUPPORTED_TYPE"


class UploadTypeMismatch(UploadRejected):
    code = "UPLOAD_TYPE_MISMATCH"


class UploadScanRejected(UploadRejected):
    code = "UPLOAD_SCAN_FAILED"


class UploadKeyConflict(UploadRejected):
    code = "UPLOAD_KEY_CONFLICT"


class UploadTarget(StrEnum):
    """规格 7.1：用户明确选择新文档还是既有文档的新版本。没有第三种。"""

    NEW_DOCUMENT = "new_document"
    NEW_VERSION = "new_version"


class UploadResult(Record):
    """一次上传的结果：文档（可能是新建的）、版本、任务，以及它是不是幂等重放。

    `scan_status` 在幂等重放时是 `None`：那次上传没有产生新的扫描结论，而回一句
    `NOT_SCANNED` 会把"早就扫过、结论已经落库"说成"没有扫过"。
    """

    document: ResearchDocument
    version: ResearchDocumentVersion
    job: IngestionJob
    created: bool
    scan_status: ScanStatus | None = None
    scan_detail: str | None = None


class SourceDownload(Record):
    """原件的下载描述。私人读取：不进 Agent 工具，也不产生预签名链接。"""

    document_id: str
    document_version_id: str
    object_key: str
    content_type: str
    sha256: str
    byte_size: int
    filename: str | None = None


class DocumentDetail(Record):
    """一份文档的全貌：版本、摄取任务与治理痕迹。"""

    document: ResearchDocument
    versions: tuple[ResearchDocumentVersion, ...]
    jobs: tuple[IngestionJob, ...]
    audit: tuple[DocumentAuditEntry, ...]


def _one_line(text: str, *, limit: int = AUDIT_DETAIL_CHARS) -> str:
    """把任意文本压成一行有界摘要。

    审计详情会被日志与告警转抄，因此它不能带换行、不能没有长度上限：一份文件的标题里
    可以有一整段正文，而那正是审计不该承载的东西。
    """
    collapsed = _WHITESPACE.sub(" ", text).strip()
    if len(collapsed) <= limit:
        return collapsed or "(empty)"
    return collapsed[: limit - 1] + "…"


def _require_actor(actor: str) -> str:
    """治理动作必须有一个具名的执行者（规格 16.2 的可追责性）。

    空字符串在此被拒绝：一个"谁都没做"的审计条目，在追责时的价值等于零。
    """
    if not actor.strip():
        raise GovernanceRefused("a governance action must name the actor who performed it")
    return actor.strip()


def _object_name(filename: str, media_type: str) -> str:
    """文件名的安全版本，用作对象键的最后一段。

    规则是"只保留可安全放进键的字符"，因此一份中文名的报告不会产生一个非 ASCII 的键，
    也不会因为名字被压空而丢掉扩展名。原始文件名保存在资产元数据里（元数据不是键），
    两者各自承担一件事。
    """
    extension = Path(filename).suffix.lower()
    if EXTENSION_MEDIA_TYPES.get(extension) != media_type:
        extension = next(
            (suffix for suffix, mapped in EXTENSION_MEDIA_TYPES.items() if mapped == media_type),
            "",
        )
    stem = Path(filename).stem
    safe = _UNSAFE_IN_NAME.sub("_", stem).strip("._-")
    safe = safe[: max(1, OBJECT_NAME_CHARS - len(extension))]
    return f"{safe}{extension}" if safe else f"original{extension}"


def _canonical_media_type(value: str | None) -> str:
    """规范化并收敛别名：`application/PDF; charset=binary` 与 `application/pdf` 是同一件事。"""
    normalized = media_type_of(value)
    return CANONICAL_MEDIA_TYPES.get(normalized, normalized)


def _extension_media_type(filename: str) -> str | None:
    return EXTENSION_MEDIA_TYPES.get(Path(filename).suffix.lower())


def _detected_media_type(head: bytes) -> str | None:
    for signature, media_type in MAGIC_SIGNATURES:
        if head.startswith(signature):
            return media_type
    return None


def _event_id(generation: str, operation: OutboxOperation) -> str:
    """派生索引动作的意图 ID：同一代 + 同一种动作只有一个待办。"""
    return f"idx_{generation}_{operation.value}"


class ResearchLibraryCommands:
    """规格 7、16、17 的治理动作。"""

    def __init__(self, services: ResearchLibraryServices) -> None:
        self._services = services

    # --- 注册 ---

    def register_document(
        self,
        *,
        title: str,
        document_type: DocumentType,
        actor: str,
        author: str | None = None,
        institution: str | None = None,
        source_weight: Decimal | None = None,
        now: datetime | None = None,
    ) -> ResearchDocument:
        """登记一份逻辑文档（不含文件）。

        上传是两步：先有文档，再有版本。合成一步会让"传错了文件"和"建错了文档"变成同一
        件要回滚的事，而这两件事的补救方式完全不同。
        """
        who = _require_actor(actor)
        stamp = self._now(now)
        document = ResearchDocument(
            document_id=f"doc_{uuid4().hex}",
            title=title.strip(),
            document_type=document_type,
            author=author,
            institution=institution,
            source_weight=source_weight if source_weight is not None else Decimal("0.5"),
            # 谁上传的谁拥有：这份文档的治理动作从此有一个人可以追。
            owner_id=who,
            created_at=stamp,
        )
        created = self._services.repository.create_document(document)
        self._audit(
            created.document_id,
            action=DocumentAuditAction.REGISTER_DOCUMENT,
            actor=who,
            detail=f"registered {created.document_type} {_one_line(created.title)}",
            now=stamp,
        )
        return created

    # --- 上传 ---

    def upload(
        self,
        *,
        spooled: SpooledAsset,
        media_type: str,
        filename: str,
        target: UploadTarget,
        actor: str,
        document_id: str | None = None,
        title: str | None = None,
        document_type: DocumentType | None = None,
        author: str | None = None,
        institution: str | None = None,
        upload_key: str | None = None,
        declared_sha256: str | None = None,
        published_at: datetime | None = None,
        effective_from: datetime | None = None,
        effective_to: datetime | None = None,
        now: datetime | None = None,
    ) -> UploadResult:
        """把一份已经落盘的文件登记成一个版本（规格 7.1）。

        落盘由调用方完成（HTTP 请求体是异步流，见 `AssetSpool`），"这算不算允许的上传"
        由这里判断。顺序是刻意的：

        1. 门禁（空的、类型、扩展名、魔数）——任何一条不通过，库房里就不会多出任何一行；
        2. 建文档/版本行；
        3. 写对象存储，**同时**得到扫描结论；
        4. 结论不干净：登记资产行、留审计、拒绝请求。文件留在对象存储里作为隔离证据，
           但**没有**摄取任务，因此它永远不会被解析或进索引；
        5. 干净：登记资产行、建摄取任务、留审计。

        对象存储写失败时（键冲突、存储不可达）版本行已经在了，这一点刻意不做补偿删除：
        同一次上传用同一个 `upload_key` 重试会重新走到第 3 步，从而把这件事修好。少了这
        条路径，一次网络抖动就要靠人手去清理一份半成品。
        """
        who = _require_actor(actor)
        stamp = self._now(now)
        normalized = _canonical_media_type(media_type)
        self._require_uploadable(spooled, media_type=normalized, filename=filename)
        document = self._resolve_target(
            target=target,
            actor=who,
            document_id=document_id,
            title=title,
            document_type=document_type,
            author=author,
            institution=institution,
            now=stamp,
        )

        version_id = f"docv_{uuid4().hex}"
        key = f"original/{document.document_id}/{version_id}/{_object_name(filename, normalized)}"
        metadata = AssetMetadata(
            content_type=normalized,
            asset_role=AssetRole.ORIGINAL,
            filename=filename,
            document_id=document.document_id,
            document_version_id=version_id,
            sha256=spooled.sha256,
            byte_size=spooled.byte_size,
        )

        try:
            version = self._create_version(
                document=document,
                version_id=version_id,
                spooled=spooled,
                upload_key=upload_key,
                published_at=published_at,
                effective_from=effective_from,
                effective_to=effective_to,
                now=stamp,
            )
        except ResearchLibraryConflict as error:
            raise UploadKeyConflict(str(error)) from error

        if version.document_version_id != version_id:
            # 幂等重放：这个上传键（+ 同一份内容）已经登记过了。不再写第二份字节，也不再
            # 建第二个任务——重复的"运行中"任务是对同一份文件的两次并行解析。
            job = self._existing_job(version.document_version_id)
            if job is None:
                raise GovernanceRefused(
                    f"version {version.document_version_id!r} has no ingestion job; the upload "
                    f"was rejected earlier or interrupted before the job was created"
                )
            return UploadResult(
                document=document,
                version=version,
                job=job,
                created=False,
                scan_detail="the upload was already registered; its stored verdict stands",
            )

        with Path(spooled.path).open("rb") as handle:
            reference = self._services.assets.put(key=key, content=handle, metadata=metadata)

        self._services.repository.register_asset(
            ResearchDocumentAsset(
                asset_id=f"asset_{uuid4().hex}",
                document_id=document.document_id,
                document_version_id=version.document_version_id,
                asset_role=AssetRole.ORIGINAL,
                object_key=key,
                content_type=normalized,
                byte_size=reference.byte_size,
                sha256=reference.sha256,
                scan_status=reference.scan_status,
                scan_detail=reference.scan_detail,
                created_at=stamp,
            )
        )

        if reference.scan_status in {ScanStatus.INFECTED, ScanStatus.FAILED}:
            # 拒绝但仍然留下痕迹：文件留在对象存储里作为隔离证据，资产行记着结论，审计
            # 记着是谁在什么时候被拒的。没有摄取任务，因此它永远不会被解析或进索引——
            # 静默删掉一份被判定为恶意的文件，等于把它变成一次"没有发生过"的事件。
            self._audit(
                document.document_id,
                action=DocumentAuditAction.REFUSE_UPLOAD,
                actor=who,
                detail=(
                    f"refused {_one_line(filename)} for version "
                    f"{version.document_version_id}: "
                    f"{reference.scan_detail or reference.scan_status}"
                ),
                now=stamp,
                document_version_id=version.document_version_id,
            )
            raise UploadScanRejected(
                f"the file was rejected by the safety scanner "
                f"({reference.scan_status}): {reference.scan_detail or 'no detail'}"
            )

        job = IngestionJob(
            job_id=f"job_{uuid4().hex}",
            document_id=document.document_id,
            document_version_id=version.document_version_id,
            created_at=stamp,
            updated_at=stamp,
        )
        stored_job = self._services.repository.create_ingestion_job(job)
        self._audit(
            document.document_id,
            action=DocumentAuditAction.REGISTER_VERSION,
            actor=who,
            detail=(
                f"registered version {version.version_number} of "
                f"{_one_line(document.title)} ({_one_line(filename)})"
            ),
            now=stamp,
            document_version_id=version.document_version_id,
        )
        return UploadResult(
            document=document,
            version=version,
            job=stored_job,
            created=True,
            scan_status=reference.scan_status,
            scan_detail=reference.scan_detail,
        )

    # --- 治理 ---

    def set_source_weight(
        self, document_id: str, *, source_weight: Decimal, actor: str, now: datetime | None = None
    ) -> ResearchDocument:
        """改来源权重（规格 17）。软删除的文档拒绝——恢复后必须是删除前的那一个权重。"""
        who = _require_actor(actor)
        stamp = self._now(now)
        try:
            document = self._services.repository.set_source_weight(
                document_id, source_weight=source_weight
            )
        except ResearchLibraryConflict as error:
            raise GovernanceRefused(str(error)) from error
        self._audit(
            document_id,
            action=DocumentAuditAction.SET_SOURCE_WEIGHT,
            actor=who,
            detail=f"source weight is now {document.source_weight}",
            now=stamp,
        )
        return document

    def archive_version(
        self,
        document_id: str,
        document_version_id: str,
        *,
        actor: str,
        now: datetime | None = None,
    ) -> ResearchDocumentVersion:
        """归档一版并登记"删掉它那一代向量"的意图（规格 16.4）。

        意图是一次写入（Outbox），不是一次 Milvus 调用：派生索引不在线时归档仍然必须
        成功，而"该删的还没删"是一个可以被维护流程看见的状态。

        "只有已经在服务集里的版本才能归档"这条判断写在这里，而不是交给存储层去拒绝：
        它不是一次并发冲突，是一个对当前状态不成立的请求，而调用方需要的是一个能照着改的
        答案（409 与一句为什么），不是一个来自存储实现的异常。
        """
        who = _require_actor(actor)
        stamp = self._now(now)
        version = self._require_version(document_id, document_version_id)
        if version.status not in (
            DocumentVersionStatus.ACTIVE,
            DocumentVersionStatus.SUPERSEDED,
        ):
            raise GovernanceRefused(
                f"version {document_version_id!r} is {version.status}; only an ACTIVE or "
                f"SUPERSEDED version can be archived"
            )
        try:
            archived = self._services.repository.archive_version(
                document_version_id, expected_status=version.status
            )
        except ResearchLibraryConflict as error:
            raise GovernanceRefused(str(error)) from error
        if version.index_generation is not None:
            self._enqueue_delete(version, generation=version.index_generation, now=stamp)
        self._audit(
            document_id,
            action=DocumentAuditAction.ARCHIVE_VERSION,
            actor=who,
            detail=f"archived version {version.version_number}",
            now=stamp,
            document_version_id=document_version_id,
        )
        return archived

    def soft_delete(
        self, document_id: str, *, actor: str, now: datetime | None = None
    ) -> ResearchDocument:
        """软删除一份文档并在保留期之后清理（规格 16.3）。

        向量删除的意图在这里就登记：检索侧立刻就读不到它（权威库是可见性的唯一来源），
        而派生索引晚一点清干净是可以接受的，反过来不行。
        """
        who = _require_actor(actor)
        stamp = self._now(now)
        self._require_document(document_id)
        try:
            document = self._services.repository.soft_delete_document(
                document_id, now=stamp, retention_days=self._services.settings.retention_days
            )
        except ResearchLibraryConflict as error:
            raise GovernanceRefused(str(error)) from error
        for version in self._services.repository.list_versions(document_id):
            if version.index_generation is not None:
                self._enqueue_delete(version, generation=version.index_generation, now=stamp)
        self._audit(
            document_id,
            action=DocumentAuditAction.SOFT_DELETE,
            actor=who,
            detail=(
                f"soft deleted {_one_line(document.title)}; purge after {document.purge_after}"
            ),
            now=stamp,
        )
        return document

    def restore(
        self, document_id: str, *, actor: str, now: datetime | None = None
    ) -> ResearchDocument:
        """恢复一份软删除的文档。

        不自动重建索引：软删除时登记的删除意图可能已经执行，因此这一版的派生索引可能是
        空的。自动重建意味着一次"恢复"动作偷偷触发一轮重新嵌入（真实花费），而恢复的
        语义只是"让它重新可用"。需要重建时由用户显式调 `rebuild_index`。

        恢复一份没被删过的文档是一次**拒绝对话**：存储层会照做（把 `deleted_at` 再清一遍
        本来就是空操作），于是响应看起来像成功，而审计里会多出一条什么都没改变的"恢复"。
        审计里出现没有改变任何东西的动作，比少一条记录更难发现。
        """
        who = _require_actor(actor)
        stamp = self._now(now)
        document = self._require_document(document_id)
        if document.deleted_at is None:
            raise GovernanceRefused(
                f"document {document_id!r} is not soft-deleted; there is nothing to restore"
            )
        try:
            document = self._services.repository.restore_document(document_id, now=stamp)
        except ResearchLibraryConflict as error:
            raise GovernanceRefused(str(error)) from error
        self._audit(
            document_id,
            action=DocumentAuditAction.RESTORE,
            actor=who,
            detail=f"restored {_one_line(document.title)}",
            now=stamp,
        )
        return document

    def retry_ingestion(
        self, job_id: str, *, actor: str, now: datetime | None = None
    ) -> IngestionJob:
        """把一个失败的摄取任务重新放回队列开头。

        这是一次**重排**而不是一次状态迁移（`requeue_ingestion` 的域函数说得很清楚）：
        `PERMANENT_FAILED` 是终态，而用户重试是在为同一份文件开一段新的处理历程。
        """
        who = _require_actor(actor)
        stamp = self._now(now)
        job = self._services.repository.get_ingestion_job(job_id)
        if job is None:
            raise JobNotFound(f"ingestion job {job_id!r} does not exist")
        if job.status not in {
            IngestionStatus.PERMANENT_FAILED,
            IngestionStatus.RETRYABLE_FAILED,
            IngestionStatus.CANCELLED,
        }:
            raise GovernanceRefused(
                f"ingestion job {job_id!r} is {job.status}, not a failed attempt"
            )
        try:
            requeued = self._services.repository.requeue_ingestion_job(
                job_id, now=stamp, expected_status=job.status
            )
        except ResearchLibraryConflict as error:
            raise GovernanceRefused(str(error)) from error
        self._audit(
            job.document_id,
            action=DocumentAuditAction.RETRY_INGESTION,
            actor=who,
            detail=f"requeued ingestion job {job_id}",
            now=stamp,
            document_version_id=job.document_version_id,
        )
        return requeued

    def run_ingestion(
        self, job_id: str, *, worker_id: str, now: datetime | None = None
    ) -> IngestionJob:
        """推进一步摄取。

        刻意**不**记审计：这一步是 worker 在做的事，它每次重试、每次租约续期都会发生。
        把 worker 的每一步都写成治理痕迹，等于让真正需要被追责的那几行被埋在噪声里。
        """
        if self._services.repository.get_ingestion_job(job_id) is None:
            raise JobNotFound(f"ingestion job {job_id!r} does not exist")
        return self._services.ingestion.run(job_id, worker_id, self._now(now))

    def rebuild_index(
        self,
        document_id: str,
        document_version_id: str,
        *,
        actor: str,
        worker_id: str = "api-rebuild",
        now: datetime | None = None,
    ) -> IndexVerification:
        """按权威切片重建一版的派生索引（规格 16.3、16.4）。

        "这一版还不在服务集里"要变成一次治理拒绝（409），而不是一次 500：
        `UnrecoverableIngestionError` 在协调器那里意思是"重跑多少遍结果都一样"，它不是
        程序坏了，是这次请求对当前状态不成立。
        """
        who = _require_actor(actor)
        stamp = self._now(now)
        version = self._require_version(document_id, document_version_id)
        try:
            report = self._services.ingestion.rebuild_index(
                document_version_id, worker_id=worker_id, now=stamp
            )
        except (ResearchLibraryConflict, UnrecoverableIngestionError) as error:
            raise GovernanceRefused(str(error)) from error
        self._audit(
            document_id,
            action=DocumentAuditAction.REBUILD_INDEX,
            actor=who,
            detail=(
                f"rebuilt {report.generation}: {report.present_count}/"
                f"{report.expected_count} chunks present"
            ),
            now=stamp,
            document_version_id=version.document_version_id,
        )
        return report

    # --- 内部 ---

    def _now(self, now: datetime | None) -> datetime:
        return self._services.clock() if now is None else now

    def _require_document(self, document_id: str) -> ResearchDocument:
        document = self._services.repository.get_document(document_id)
        if document is None:
            raise DocumentNotFound(f"document {document_id!r} does not exist")
        return document

    def _require_version(
        self, document_id: str, document_version_id: str
    ) -> ResearchDocumentVersion:
        version = self._services.repository.get_version(document_version_id)
        # 版本必须属于路径上的那份文档：只按版本 ID 找，会让一个版本 ID 变成跨文档的访问
        # 凭据，而"这份文档的哪一版"正是路由想表达的东西。
        if version is None or version.document_id != document_id:
            raise VersionNotFound(
                f"version {document_version_id!r} does not belong to document {document_id!r}"
            )
        return version

    def _existing_job(self, document_version_id: str) -> IngestionJob | None:
        jobs = self._services.repository.list_ingestion_jobs(
            document_version_id=document_version_id, limit=1
        )
        return jobs[0] if jobs else None

    def _enqueue_delete(
        self, version: ResearchDocumentVersion, *, generation: str, now: datetime
    ) -> None:
        self._services.repository.enqueue_index_event(
            IndexOutboxEvent(
                event_id=_event_id(generation, OutboxOperation.DELETE_GENERATION),
                document_version_id=version.document_version_id,
                index_generation=generation,
                operation=OutboxOperation.DELETE_GENERATION,
                available_at=now,
                created_at=now,
            )
        )

    def _audit(
        self,
        document_id: str,
        *,
        action: DocumentAuditAction,
        actor: str,
        detail: str,
        now: datetime,
        document_version_id: str | None = None,
    ) -> DocumentAuditEntry:
        entry = document_audit_entry(
            document_id=document_id,
            action=action,
            actor=actor,
            detail=detail,
            created_at=now,
            document_version_id=document_version_id,
        )
        return self._services.repository.append_document_audit(entry)

    def _require_uploadable(self, spooled: SpooledAsset, *, media_type: str, filename: str) -> None:
        """上传门禁。任何一条不通过，权威库里就不会多出任何一行。

        不检查编码：TXT 解析器的解码阶梯（UTF-8 → GB18030 → latin-1）是刻意的设计，
        在这里再判一次"是不是 UTF-8"会让一份 GB18030 的报告被门禁拒绝，而解析器本来
        就是为它写的。这里只判断"它是不是它声称的那种东西"。
        """
        if spooled.byte_size == 0:
            raise UploadEmpty("the uploaded file is empty")
        pipeline = self._services.parse_pipeline
        if not pipeline.supports(media_type):
            raise UploadUnsupportedType(
                f"no parser is registered for {media_type}; "
                f"supported types are {', '.join(sorted(pipeline.supported_media_types))}"
            )
        declared_extension = _extension_media_type(filename)
        if declared_extension != media_type:
            raise UploadTypeMismatch(
                f"the file is named {_one_line(filename)} but was sent as {media_type}"
            )
        with Path(spooled.path).open("rb") as handle:
            head = handle.read(MAGIC_HEAD_BYTES)
        detected = _detected_media_type(head)
        if detected is not None and detected != media_type:
            raise UploadTypeMismatch(
                f"the file content looks like {detected} but was sent as {media_type}"
            )
        if detected is None and media_type in MAGIC_REQUIRED_MEDIA_TYPES:
            raise UploadTypeMismatch(
                f"a {media_type} file must start with its format signature; this one does not"
            )

    def _resolve_target(
        self,
        *,
        target: UploadTarget,
        actor: str,
        document_id: str | None,
        title: str | None,
        document_type: DocumentType | None,
        author: str | None,
        institution: str | None,
        now: datetime,
    ) -> ResearchDocument:
        """把"新文档 / 新版本"这个显式选择解析成一份文档。

        两种选择各自要求什么，写在这里而不是散在路由里：传新版本却没说给谁，和传新文档
        却报了一个已有文档 ID，都是**用户没说清楚**，必须拒绝而不是替它猜一个。
        """
        if target is UploadTarget.NEW_VERSION:
            if document_id is None:
                raise UploadTargetRequired(
                    "uploading a new version requires the document it belongs to"
                )
            if title is not None or document_type is not None:
                raise UploadTargetConflict(
                    "a new version does not carry a title or a document type; those belong to "
                    "the document and must be changed through the document, not through an upload"
                )
            document = self._require_document(document_id)
            if document.deleted_at is not None:
                raise GovernanceRefused(
                    f"document {document_id!r} is soft-deleted; restore it before adding versions"
                )
            return document
        if document_id is not None:
            raise UploadTargetConflict(
                "uploading a new document must not name an existing document"
            )
        if title is None or document_type is None:
            raise UploadTargetRequired(
                "uploading a new document requires a title and a document type"
            )
        return self.register_document(
            title=title,
            document_type=document_type,
            actor=actor,
            author=author,
            institution=institution,
            now=now,
        )

    def _create_version(
        self,
        *,
        document: ResearchDocument,
        version_id: str,
        spooled: SpooledAsset,
        upload_key: str | None,
        published_at: datetime | None,
        effective_from: datetime | None,
        effective_to: datetime | None,
        now: datetime,
    ) -> ResearchDocumentVersion:
        """登记版本行。

        版本号由既有版本数推出来，因此并发上传同一份文档的两次会撞上
        `UNIQUE (document_id, version_number)`，其中的一次失败——这是对的：两次上传
        本来就是两个版本，而"给它们同一个号"不是一种可以接受的合并方式。
        """
        version = ResearchDocumentVersion(
            document_version_id=version_id,
            document_id=document.document_id,
            version_number=len(self._services.repository.list_versions(document.document_id)) + 1,
            uploaded_at=now,
            original_file_hash=f"sha256:{spooled.sha256}",
            published_at=published_at,
            effective_from=effective_from,
            effective_to=effective_to,
        )
        return self._services.repository.create_version(version, upload_key=upload_key)


class ResearchLibraryQueries:
    """API 层的读取视图。不改变任何状态。"""

    def __init__(self, services: ResearchLibraryServices) -> None:
        self._services = services

    def list_documents(
        self, *, include_deleted: bool = False, limit: int = 100
    ) -> tuple[ResearchDocument, ...]:
        return self._services.repository.list_documents(
            include_deleted=include_deleted, limit=limit
        )

    def detail(self, document_id: str) -> DocumentDetail:
        document = self._services.repository.get_document(document_id)
        if document is None:
            raise DocumentNotFound(f"document {document_id!r} does not exist")
        return DocumentDetail(
            document=document,
            versions=self._services.repository.list_versions(document_id),
            jobs=self._services.repository.list_ingestion_jobs(document_id=document_id),
            audit=self._services.repository.list_document_audit(document_id),
        )

    def latest_job(self, document_version_id: str) -> IngestionJob | None:
        """这一版最近的那个摄取任务，状态与失败原因都取自它。"""
        jobs = self._services.repository.list_ingestion_jobs(
            document_version_id=document_version_id, limit=1
        )
        return jobs[0] if jobs else None

    def source(self, document_id: str, document_version_id: str) -> SourceDownload:
        """原件的下载描述：用户按引用定位回原文件的那条路（规格 18.2）。

        版本必须属于路径上的这份文档；对象键从权威库读，不从请求里读——否则一个构造出来
        的键就是一次任意对象读取。
        """
        version = self._version(document_id, document_version_id)
        key = self._services.repository.get_original_asset_key(version.document_version_id)
        if key is None:
            raise SourceUnavailable(f"version {document_version_id!r} has no registered original")
        try:
            reference = self._services.assets.stat(key)
        except AssetNotFound as error:
            raise SourceUnavailable(
                f"the original of version {document_version_id!r} is not in the asset store"
            ) from error
        return SourceDownload(
            document_id=document_id,
            document_version_id=document_version_id,
            object_key=key,
            content_type=reference.content_type,
            sha256=reference.sha256,
            byte_size=reference.byte_size,
            filename=reference.metadata.filename,
        )

    def stream(self, download: SourceDownload, *, chunk_bytes: int = 64 * 1024) -> Iterator[bytes]:
        """按块读原件。

        不读进内存：一份 256MB 的原件在浏览器里是一段下载，在服务器上不该是一块常驻内存。
        """
        with self._services.assets.open(download.object_key) as handle:
            while chunk := handle.read(chunk_bytes):
                yield chunk

    def corpus_generation(self) -> str:
        """当前语料世代（规格 17）。列表页显示它，好让"检索结果变了"有据可查。"""
        return self._services.corpus_generation()

    def _version(self, document_id: str, document_version_id: str) -> ResearchDocumentVersion:
        version = self._services.repository.get_version(document_version_id)
        if version is None or version.document_id != document_id:
            raise VersionNotFound(
                f"version {document_version_id!r} does not belong to document {document_id!r}"
            )
        return version


__all__ = [
    "DocumentDetail",
    "DocumentNotFound",
    "GovernanceRefused",
    "JobNotFound",
    "ResearchLibraryCommandError",
    "ResearchLibraryCommands",
    "ResearchLibraryQueries",
    "SourceDownload",
    "SourceUnavailable",
    "UploadEmpty",
    "UploadKeyConflict",
    "UploadRejected",
    "UploadResult",
    "UploadScanRejected",
    "UploadTarget",
    "UploadTargetConflict",
    "UploadTargetRequired",
    "UploadTypeMismatch",
    "UploadUnsupportedType",
    "VersionNotFound",
]
