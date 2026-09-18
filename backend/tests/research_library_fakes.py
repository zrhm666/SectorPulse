"""An in-memory authority store, so the ingestion pipeline can actually be run offline.

This is test infrastructure rather than a deployable adapter, which is why it lives under
`tests/` while the asset store's in-memory adapter lives in `src/`. It exists for one
reason: the coordinator, the publication gate and the outbox worker are the parts of this
system most likely to be wrong, and a test suite that skips whenever no PostgreSQL server is
configured would leave every one of those properties unverified on a developer machine.

What it does not pretend to do is reproduce database concurrency. Conditional updates,
`FOR UPDATE`, `SKIP LOCKED` and same-transaction supersede are all single-threaded here.
The properties that genuinely depend on the database — two workers racing for one lease, a
version superseded in the same transaction that activates its successor — are tested against
real PostgreSQL in `backend/tests/integration/test_research_index_publication.py`, and this
class only has to be faithful enough that the *logic* above it is exercised honestly.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sector_pulse.domain.research_library.audit import DocumentAuditEntry
from sector_pulse.domain.research_library.ingestion import (
    IngestionLeaseLost,
    InvalidIngestionTransition,
    acquire_ingestion_lease,
    requeue_ingestion,
)
from sector_pulse.domain.research_library.models import (
    FAILURE_INGESTION_STATUSES,
    ChunkEmbeddingStatus,
    DocumentVersionStatus,
    IndexOutboxEvent,
    IngestionJob,
    IngestionStatus,
    OutboxStatus,
    ResearchChunk,
    ResearchDocument,
    ResearchDocumentVersion,
)
from sector_pulse.domain.research_library.retrieval import RetrievalAuditRecord
from sector_pulse.ports.research_assets import AssetRole, ResearchDocumentAsset
from sector_pulse.storage.ports.research_library import ResearchLibraryConflict

#: 与 PostgreSQL 实现保持同一个认领过期时间：一个被认领后崩掉的 worker 留下的 CLAIMED
#: 事件，只有在超过这个时间之后才能被别人接手。
CLAIM_STALE_SECONDS = 300


class InMemoryResearchLibraryRepository:
    """`ResearchLibraryRepositoryPort` 的单线程实现。"""

    def __init__(self) -> None:
        self._documents: dict[str, ResearchDocument] = {}
        self._versions: dict[str, ResearchDocumentVersion] = {}
        self._version_order: dict[str, list[str]] = {}
        self._upload_keys: dict[str, str] = {}
        self._chunks: dict[str, ResearchChunk] = {}
        self._chunk_order: dict[str, list[str]] = {}
        self._jobs: dict[str, IngestionJob] = {}
        self._outbox: dict[str, IndexOutboxEvent] = {}
        self._audits: dict[str, RetrievalAuditRecord] = {}
        self._original_keys: dict[str, str] = {}
        self._assets: dict[str, ResearchDocumentAsset] = {}
        self._asset_order: dict[str, list[str]] = {}
        self._document_audit: dict[str, DocumentAuditEntry] = {}

    # --- 文档 ---

    def create_document(self, document: ResearchDocument) -> ResearchDocument:
        if document.document_id in self._documents:
            raise ResearchLibraryConflict(f"document {document.document_id!r} already exists")
        self._documents[document.document_id] = document
        self._version_order.setdefault(document.document_id, [])
        return document

    def get_document(self, document_id: str) -> ResearchDocument | None:
        return self._documents.get(document_id)

    def list_documents(
        self, *, include_deleted: bool = False, limit: int = 100
    ) -> tuple[ResearchDocument, ...]:
        documents = [
            document
            for document in self._documents.values()
            if include_deleted or document.deleted_at is None
        ]
        return tuple(sorted(documents, key=lambda item: item.created_at)[:limit])

    def set_current_version(self, document_id: str, document_version_id: str) -> None:
        document = self._require_document(document_id)
        self._documents[document_id] = document.model_copy(
            update={"current_version_id": document_version_id}
        )

    def soft_delete_document(
        self, document_id: str, *, now: datetime, retention_days: int
    ) -> ResearchDocument:
        document = self._require_document(document_id)
        deleted = document.model_copy(
            update={"deleted_at": now, "purge_after": now + timedelta(days=retention_days)}
        )
        self._documents[document_id] = deleted
        return deleted

    def restore_document(self, document_id: str, *, now: datetime) -> ResearchDocument:
        document = self._require_document(document_id)
        restored = document.model_copy(update={"deleted_at": None, "purge_after": None})
        self._documents[document_id] = restored
        return restored

    def set_source_weight(self, document_id: str, *, source_weight: Decimal) -> ResearchDocument:
        document = self._documents.get(document_id)
        if document is None or document.deleted_at is not None:
            raise ResearchLibraryConflict(
                f"document {document_id!r} is missing or deleted; restore it before "
                f"changing its source weight"
            )
        updated = document.model_copy(update={"source_weight": source_weight})
        self._documents[document_id] = updated
        return updated

    def purge_document(
        self, document_id: str, *, now: datetime, audit: DocumentAuditEntry
    ) -> ResearchDocument:
        """物理清理，与 PostgreSQL 的条件更新同一件事：声明过期只是声明。"""
        if audit.document_id != document_id:
            raise ValueError("the purge audit entry belongs to another document")
        document = self._documents.get(document_id)
        if (
            document is None
            or document.deleted_at is None
            or document.purge_after is None
            or document.purge_after > now
        ):
            raise ResearchLibraryConflict(
                f"document {document_id!r} is not deleted, has no retention deadline, or "
                f"its retention period has not expired yet"
            )
        self._documents[document_id] = document.model_copy(update={"current_version_id": None})
        for version_id, chunk_ids in list(self._chunk_order.items()):
            # 块的顺序表跟着块一起清。只删 `_chunks` 会让 `list_chunks` 与 `count_chunks`
            # 在清理之后对着一个不存在的 ID 报 KeyError——那不是"清理干净了"，是假实现
            # 自己坏了，而它会伪装成被清理的文档还有块。
            kept = [
                chunk_id
                for chunk_id in chunk_ids
                if self._chunks[chunk_id].document_id != document_id
            ]
            self._chunk_order[version_id] = kept
        for chunk_id in list(self._chunks):
            if self._chunks[chunk_id].document_id == document_id:
                del self._chunks[chunk_id]
        for version_id, version in list(self._versions.items()):
            if (
                version.document_id == document_id
                and version.status is not DocumentVersionStatus.PURGED
            ):
                self._versions[version_id] = version.model_copy(
                    update={"status": DocumentVersionStatus.PURGED}
                )
        for asset_id, asset in list(self._assets.items()):
            if asset.document_id == document_id and asset.deleted_at is None:
                self._assets[asset_id] = asset.model_copy(update={"deleted_at": now})
        self.append_document_audit(audit)
        purged = self._documents[document_id]
        return purged

    # --- 清理与审计 ---

    def append_document_audit(self, entry: DocumentAuditEntry) -> DocumentAuditEntry:
        if entry.audit_id in self._document_audit:
            raise ResearchLibraryConflict(f"document audit {entry.audit_id!r} already exists")
        self._document_audit[entry.audit_id] = entry
        return entry

    def list_document_audit(
        self, document_id: str, *, limit: int = 100
    ) -> tuple[DocumentAuditEntry, ...]:
        entries = [
            entry for entry in self._document_audit.values() if entry.document_id == document_id
        ]
        entries.sort(key=lambda entry: (entry.created_at, entry.audit_id))
        return tuple(entries[:limit])

    # --- 文档版本 ---

    def create_version(
        self, version: ResearchDocumentVersion, *, upload_key: str | None = None
    ) -> ResearchDocumentVersion:
        """按上传幂等键去重，与 PostgreSQL 实现同一条规则。"""
        if upload_key is not None:
            existing_id = self._upload_keys.get(upload_key)
            if existing_id is not None:
                existing = self._versions[existing_id]
                if existing.original_file_hash != version.original_file_hash:
                    raise ResearchLibraryConflict(
                        f"upload key {upload_key!r} was already used for different content"
                    )
                return existing
        if version.document_version_id in self._versions:
            raise ResearchLibraryConflict(
                f"document version {version.document_version_id!r} already exists"
            )
        self._require_document(version.document_id)
        self._versions[version.document_version_id] = version
        self._version_order[version.document_id].append(version.document_version_id)
        if upload_key is not None:
            self._upload_keys[upload_key] = version.document_version_id
        return version

    def get_version(self, document_version_id: str) -> ResearchDocumentVersion | None:
        return self._versions.get(document_version_id)

    def list_versions(self, document_id: str) -> tuple[ResearchDocumentVersion, ...]:
        return tuple(
            self._versions[version_id] for version_id in self._version_order.get(document_id, [])
        )

    def load_version_statuses(
        self, document_version_ids: Sequence[str]
    ) -> dict[str, DocumentVersionStatus]:
        """未知的 ID 不出现在结果里——调用方因此能区分"不是 ACTIVE"和"查不到"。

        软删除的文档名下的版本同样不出现在结果里（规格 16.3 第 2 步："检索立即过滤"）。
        PostgreSQL 实现用 `JOIN` 表达这件事，这里用文档的 `deleted_at`。两边都必须在**这一
        处**回答正确：三个调用方（检索复核、证据可见性复核、索引命中过滤）都把"查不到"当作
        "不可用"，因此漏掉这一步的表现是"删掉的材料照旧可引用"。
        """
        return {
            version_id: self._versions[version_id].status
            for version_id in document_version_ids
            if version_id in self._versions
            and self._is_live(self._versions[version_id].document_id)
        }

    def _is_live(self, document_id: str) -> bool:
        document = self._documents.get(document_id)
        return document is not None and document.deleted_at is None

    def save_version_metadata(
        self, version: ResearchDocumentVersion, *, expected_status: DocumentVersionStatus
    ) -> ResearchDocumentVersion:
        held = self._versions.get(version.document_version_id)
        if held is None:
            raise ResearchLibraryConflict(
                f"document version {version.document_version_id!r} does not exist"
            )
        if held.status is not expected_status:
            raise ResearchLibraryConflict(
                f"document version {version.document_version_id!r} is no longer {expected_status}"
            )
        updated = version.model_copy(update={"status": held.status})
        self._versions[version.document_version_id] = updated
        return updated

    def activate_version(
        self, document_version_id: str, *, expected_status: DocumentVersionStatus
    ) -> None:
        """让新版本生效并让同一文档的旧版本失效，与 PostgreSQL 实现同一件事。

        PostgreSQL 版本在同一个事务里做这两步，这里没有事务，只在单线程下等价。
        """
        held = self._versions.get(document_version_id)
        if held is None:
            raise ResearchLibraryConflict(
                f"document version {document_version_id!r} does not exist"
            )
        for other_id in self._version_order[held.document_id]:
            other = self._versions[other_id]
            if other_id != document_version_id and other.status is DocumentVersionStatus.ACTIVE:
                self._versions[other_id] = other.model_copy(
                    update={"status": DocumentVersionStatus.SUPERSEDED}
                )
        if held.status is not expected_status:
            raise ResearchLibraryConflict(
                f"document version {document_version_id!r} is no longer {expected_status}"
            )
        self._versions[document_version_id] = held.model_copy(
            update={
                "status": DocumentVersionStatus.ACTIVE,
                # PostgreSQL 用 COALESCE(published_at, now)；这里用 indexed_at 代替 now，
                # 好让断言不必依赖墙上时钟。两者都满足"发布时间不早于索引完成时间"。
                "published_at": held.published_at or held.indexed_at,
            }
        )
        self.set_current_version(held.document_id, document_version_id)

    def archive_version(
        self, document_version_id: str, *, expected_status: DocumentVersionStatus
    ) -> ResearchDocumentVersion:
        if expected_status not in (
            DocumentVersionStatus.ACTIVE,
            DocumentVersionStatus.SUPERSEDED,
        ):
            raise ValueError(
                f"a {expected_status} version cannot be archived; only ACTIVE or SUPERSEDED "
                f"versions are in the serving set"
            )
        held = self._versions.get(document_version_id)
        if held is None:
            raise ResearchLibraryConflict(
                f"document version {document_version_id!r} does not exist"
            )
        if held.status is not expected_status:
            raise ResearchLibraryConflict(
                f"document version {document_version_id!r} is no longer {expected_status}"
            )
        archived = held.model_copy(update={"status": DocumentVersionStatus.ARCHIVED})
        self._versions[document_version_id] = archived
        document = self._documents.get(held.document_id)
        if document is not None and document.current_version_id == document_version_id:
            self._documents[held.document_id] = document.model_copy(
                update={"current_version_id": None}
            )
        return archived

    def get_original_asset_key(self, document_version_id: str) -> str | None:
        for asset_id in self._asset_order.get(document_version_id, []):
            asset = self._assets[asset_id]
            if asset.asset_role is AssetRole.ORIGINAL and asset.deleted_at is None:
                return asset.object_key
        return self._original_keys.get(document_version_id)

    def register_original_asset(self, document_version_id: str, object_key: str) -> None:
        """登记一版原件。

        测试里的快捷方式：只留下"原件在哪里"这一件事（`get_original_asset_key` 与 PG 实现
        读同一张表时看的也是这件事）。真实的上传命令走 `register_asset`，那里才有内容类型、
        散列与扫描结论。
        """
        self._original_keys[document_version_id] = object_key

    def register_asset(self, asset: ResearchDocumentAsset) -> ResearchDocumentAsset:
        for held in self._assets.values():
            if held.object_key == asset.object_key and held.asset_id != asset.asset_id:
                raise ResearchLibraryConflict(
                    f"object key {asset.object_key!r} is already registered by another asset"
                )
        if asset.asset_id in self._assets:
            raise ResearchLibraryConflict(f"asset {asset.asset_id!r} already exists")
        self._assets[asset.asset_id] = asset
        if asset.document_version_id is not None:
            self._asset_order.setdefault(asset.document_version_id, []).append(asset.asset_id)
        return asset

    def list_asset_keys(self, document_version_id: str) -> tuple[str, ...]:
        return tuple(
            self._assets[asset_id].object_key
            for asset_id in self._asset_order.get(document_version_id, [])
            if self._assets[asset_id].deleted_at is None
        )

    # --- 切片 ---

    def append_chunks(self, chunks: Sequence[ResearchChunk]) -> None:
        for chunk in chunks:
            if chunk.chunk_id in self._chunks:
                raise ResearchLibraryConflict(f"chunk {chunk.chunk_id!r} already exists")
        for chunk in chunks:
            self._chunks[chunk.chunk_id] = chunk
            self._chunk_order.setdefault(chunk.document_version_id, []).append(chunk.chunk_id)

    def get_chunk(self, chunk_id: str) -> ResearchChunk | None:
        return self._chunks.get(chunk_id)

    def load_chunks(self, chunk_ids: Sequence[str]) -> dict[str, ResearchChunk]:
        return {
            chunk_id: self._chunks[chunk_id] for chunk_id in chunk_ids if chunk_id in self._chunks
        }

    def list_chunks(
        self, document_version_id: str, *, limit: int = 500
    ) -> tuple[ResearchChunk, ...]:
        return tuple(
            self._chunks[chunk_id]
            for chunk_id in self._chunk_order.get(document_version_id, [])[:limit]
        )

    def count_chunks(self, document_version_id: str) -> int:
        return len(self._chunk_order.get(document_version_id, []))

    def mark_chunks_embedded(self, chunk_ids: Sequence[str]) -> None:
        for chunk_id in chunk_ids:
            held = self._chunks.get(chunk_id)
            if held is None:
                raise ResearchLibraryConflict(f"chunk {chunk_id!r} does not exist")
            self._chunks[chunk_id] = held.model_copy(
                update={"embedding_status": ChunkEmbeddingStatus.EMBEDDED}
            )

    # --- 摄取任务 ---

    def create_ingestion_job(self, job: IngestionJob) -> IngestionJob:
        if job.job_id in self._jobs:
            raise ResearchLibraryConflict(f"ingestion job {job.job_id!r} already exists")
        self._jobs[job.job_id] = job
        return job

    def get_ingestion_job(self, job_id: str) -> IngestionJob | None:
        return self._jobs.get(job_id)

    def acquire_ingestion_job(
        self, job_id: str, *, worker_id: str, now: datetime, lease_seconds: int
    ) -> IngestionJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise ResearchLibraryConflict(f"ingestion job {job_id!r} does not exist")
        try:
            claimed = acquire_ingestion_lease(
                job, now=now, worker_id=worker_id, lease_seconds=lease_seconds
            )
        except (IngestionLeaseLost, InvalidIngestionTransition) as error:
            raise ResearchLibraryConflict(str(error)) from error
        self._jobs[job_id] = claimed
        return claimed

    def save_ingestion_job(
        self, job: IngestionJob, *, expected_status: IngestionStatus, expected_attempt: int
    ) -> IngestionJob:
        held = self._jobs.get(job.job_id)
        if (
            held is None
            or held.status is not expected_status
            or held.attempt_id != expected_attempt
        ):
            raise ResearchLibraryConflict(
                f"ingestion job {job.job_id!r} is no longer "
                f"{expected_status} at attempt {expected_attempt}"
            )
        # `research_ingestion_jobs` 的两条 CHECK 也说这件事。这里重复一遍不是冗余：领域层用
        # `model_copy` 造新任务，而 Pydantic 的 `model_copy` **不跑校验器**，所以一个"非失败
        # 状态带着 failure_reason"的任务能被安静地造出来。真库会拒绝它，并把那条 CHECK 违规
        # 报告成一次并发冲突；如果这个假实现不拒绝，离线套件就会为一件事亮绿灯、真库却在
        # 同一个地方停下——那正是这个类存在的意义反过来。
        failed = job.status in FAILURE_INGESTION_STATUSES
        if failed and not job.failure_reason:
            raise ResearchLibraryConflict(
                f"ingestion job {job.job_id!r} is {job.status} but states no reason"
            )
        if not failed and job.failure_reason is not None:
            raise ResearchLibraryConflict(
                f"ingestion job {job.job_id!r} is {job.status} yet still carries a failure "
                f"reason; it should have been cleared on the way out of a failed state"
            )
        self._jobs[job.job_id] = job
        return job

    def list_ingestion_jobs(
        self,
        *,
        document_id: str | None = None,
        document_version_id: str | None = None,
        limit: int = 100,
    ) -> tuple[IngestionJob, ...]:
        if document_id is None and document_version_id is None:
            raise ValueError(
                "listing every ingestion job of every document is not a query this port "
                "offers; name a document or a version"
            )
        selected = [
            job
            for job in self._jobs.values()
            if (document_id is None or job.document_id == document_id)
            and (document_version_id is None or job.document_version_id == document_version_id)
        ]
        selected.sort(key=lambda job: (job.created_at, job.job_id), reverse=True)
        return tuple(selected[:limit])

    def requeue_ingestion_job(
        self, job_id: str, *, now: datetime, expected_status: IngestionStatus
    ) -> IngestionJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise ResearchLibraryConflict(f"ingestion job {job_id!r} does not exist")
        if job.status is not expected_status:
            raise ResearchLibraryConflict(
                f"ingestion job {job_id!r} is {job.status}, not {expected_status}; the "
                f"caller decided on a stale snapshot"
            )
        try:
            requeued = requeue_ingestion(job, now=now)
        except InvalidIngestionTransition as error:
            raise ResearchLibraryConflict(str(error)) from error
        self._jobs[job_id] = requeued
        return requeued

    # --- 派生索引 outbox ---

    def enqueue_index_event(self, event: IndexOutboxEvent) -> IndexOutboxEvent:
        """幂等登记：同一条 `event_id` 只留一行，**已兑现**的那一行重新登记时重新激活。

        正在被认领、或已经失败等待重试的事件一律原样返回：重置它们会抹掉别人的认领和失败
        原因。`DONE` 是唯一的例外——它既没有人认领，也没有失败原因要留，而重新登记它是有
        意义的（重建一代索引做的正是这件事）：那一条意图已经用掉了，不重新要一次，重建写
        回去的切片会永远停在 STAGED。
        """
        existing = self._outbox.get(event.event_id)
        if existing is not None and existing.status is not OutboxStatus.DONE:
            return existing
        self._outbox[event.event_id] = event
        return event

    def claim_outbox_events(
        self, *, worker_id: str, now: datetime, limit: int = 10
    ) -> tuple[IndexOutboxEvent, ...]:
        stale_before = now - timedelta(seconds=CLAIM_STALE_SECONDS)
        claimable = [
            event
            for event in self._outbox.values()
            if event.available_at <= now
            and (
                event.status in (OutboxStatus.PENDING, OutboxStatus.FAILED)
                or (
                    event.status is OutboxStatus.CLAIMED
                    and event.claimed_at is not None
                    and event.claimed_at <= stale_before
                )
            )
        ]
        claimable.sort(key=lambda item: (item.available_at, item.event_id))

        claimed: list[IndexOutboxEvent] = []
        for event in claimable[:limit]:
            taken = event.model_copy(
                update={
                    "status": OutboxStatus.CLAIMED,
                    "claimed_by": worker_id,
                    "claimed_at": now,
                    "attempt_count": event.attempt_count + 1,
                }
            )
            self._outbox[event.event_id] = taken
            claimed.append(taken)
        return tuple(claimed)

    def finish_outbox_event(
        self, event_id: str, *, worker_id: str, now: datetime, error: str | None = None
    ) -> IndexOutboxEvent:
        """结束事件；失败时释放认领，让下一个 worker 能重试（与 PostgreSQL 实现一致）。"""
        event = self._outbox.get(event_id)
        if (
            event is None
            or event.status is not OutboxStatus.CLAIMED
            or event.claimed_by != worker_id
        ):
            raise ResearchLibraryConflict(
                f"index outbox event {event_id!r} is not claimed by {worker_id!r}"
            )
        finished = event.model_copy(
            update={
                "status": OutboxStatus.FAILED if error else OutboxStatus.DONE,
                "claimed_by": None,
                "claimed_at": None,
                "last_error": error,
                "available_at": now,
            }
        )
        self._outbox[event_id] = finished
        return finished

    def list_outbox_events(self) -> tuple[IndexOutboxEvent, ...]:
        """测试用的读取口：端口只需要认领与结束，断言需要看到全貌。"""
        return tuple(self._outbox.values())

    # --- 检索审计 ---

    def record_retrieval_audit(self, audit: RetrievalAuditRecord) -> None:
        if audit.retrieval_id in self._audits:
            raise ResearchLibraryConflict(f"retrieval audit {audit.retrieval_id!r} already exists")
        self._audits[audit.retrieval_id] = audit

    def get_retrieval_audit(self, retrieval_id: str) -> RetrievalAuditRecord | None:
        return self._audits.get(retrieval_id)

    # --- 内部 ---

    def _require_document(self, document_id: str) -> ResearchDocument:
        document = self._documents.get(document_id)
        if document is None:
            raise ResearchLibraryConflict(f"document {document_id!r} does not exist")
        return document


def new_ingestion_job(
    *,
    document_id: str,
    document_version_id: str,
    created_at: datetime,
    max_attempts: int = 3,
) -> IngestionJob:
    """一个刚收到、还没被认领的任务。"""
    return IngestionJob(
        job_id=f"job_{uuid4().hex}",
        document_id=document_id,
        document_version_id=document_version_id,
        created_at=created_at,
        updated_at=created_at,
        max_attempts=max_attempts,
    )
