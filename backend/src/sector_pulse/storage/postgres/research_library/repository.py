"""内部研究资料库的 PostgreSQL 仓储。

并发策略：状态与所有权的推进一律使用“带前置条件的 UPDATE”。领域层先算出应当发生
什么，这里再用 `WHERE 旧值 = 期望值` 让那个判断在数据库里原子成立；`rowcount != 1`
即说明有别人先写成功，抛 `ResearchLibraryConflict` 而不是覆盖。租约与 outbox 的
候选行额外加 `FOR UPDATE SKIP LOCKED`，让多个 worker 直接跳过彼此而不是排队。

时间戳沿用仓库既有做法：列类型为 TEXT，写入前统一规范化到 UTC 的 ISO-8601 字符串，
因此 `lease_expires_at <= now`、`available_at <= now` 这类比较按字典序即可成立。
"""

import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.engine.row import RowMapping
from sqlalchemy.exc import IntegrityError

from sector_pulse.domain.research_library.audit import (
    DocumentAuditAction,
    DocumentAuditEntry,
)
from sector_pulse.domain.research_library.ingestion import (
    IngestionLeaseLost,
    InvalidIngestionTransition,
    acquire_ingestion_lease,
    requeue_ingestion,
)
from sector_pulse.domain.research_library.models import (
    ChunkEmbeddingStatus,
    ChunkType,
    DocumentType,
    DocumentVersionStatus,
    ExtractionMethod,
    IndexOutboxEvent,
    IngestionJob,
    IngestionStatus,
    OutboxOperation,
    OutboxStatus,
    ResearchChunk,
    ResearchDocument,
    ResearchDocumentVersion,
    SourceLocator,
)
from sector_pulse.domain.research_library.retrieval import RetrievalAuditRecord
from sector_pulse.ports.research_assets import AssetRole, ResearchDocumentAsset
from sector_pulse.storage.ports.research_library import ResearchLibraryConflict
from sector_pulse.storage.postgres.database import PostgresDatabase
from sector_pulse.storage.postgres.research_library.json_columns import payload

# 认领后超过这个时长仍未完成的事件视为持有者已死，允许下一个 worker 接手。
CLAIM_STALE_SECONDS = 300

DOCUMENT_COLUMNS = (
    "document_id, title, document_type, author, institution, source_weight, "
    "current_version_id, visibility_scope, owner_id, access_tags_json, created_at, "
    "deleted_at, purge_after"
)
VERSION_COLUMNS = (
    "document_version_id, document_id, version_number, status, upload_key, published_at, "
    "effective_from, effective_to, uploaded_at, original_file_hash, parser_version, "
    "chunking_policy_version, ocr_provider, ocr_model_version, embedding_provider, "
    "embedding_model_version, index_generation, expected_chunk_count, indexed_at"
)
CHUNK_COLUMNS = (
    "chunk_id, document_id, document_version_id, parent_chunk_id, chunk_type, content, "
    "content_hash, source_json, content_origin, confidence, requires_verification, "
    "embedding_status, created_at"
)
JOB_COLUMNS = (
    "job_id, document_id, document_version_id, status, attempt_id, worker_id, "
    "lease_expires_at, max_attempts, failure_reason, created_at, updated_at"
)
OUTBOX_COLUMNS = (
    "event_id, document_version_id, index_generation, operation, status, payload_json, "
    "attempt_count, claimed_by, claimed_at, available_at, last_error, created_at"
)
AUDIT_COLUMNS = (
    "retrieval_id, run_id, task_id, attempt_id, role, question, query_fingerprint, "
    "filters_json, corpus_generation, provider_versions_json, dense_candidates_json, "
    "bm25_candidates_json, fused_candidates_json, reranked_candidates_json, "
    "parent_expansions_json, claims_json, conflicts_json, returned_evidence_json, "
    "duration_ms, provider_calls, input_tokens, output_tokens, cost_cny, created_at"
)
DOCUMENT_AUDIT_COLUMNS = (
    "audit_id, document_id, document_version_id, action, actor, detail, created_at"
)


def _stamp(moment: datetime) -> str:
    """规范化到 UTC ISO-8601，使 TEXT 列上的比较与写入顺序一致。"""
    return moment.astimezone(UTC).isoformat()


def _optional_stamp(moment: datetime | None) -> str | None:
    return None if moment is None else _stamp(moment)


def _moment(value: object) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _optional_moment(value: object) -> datetime | None:
    return None if value is None else _moment(value)


def _payload(value: Any) -> Any:
    """JSONB 由驱动直接给出 Python 对象，TEXT 列则需要显式解析。

    规则本身住在 `json_columns`：已接纳证据的读取端曾经自己写了一遍，写成了无条件
    `json.loads`，于是在 PostgreSQL 上对着 JSONB 抛 `TypeError`，而离线夹具看不见。
    """
    return payload(value)


def _dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _flag(value: bool) -> int:
    """布尔列在通用迁移里是 INTEGER（SQLite 没有 BOOLEAN），必须显式转换。"""
    return int(value)


@contextmanager
def _conflicts() -> Iterator[None]:
    """把数据库层面的约束违规翻译成端口承诺的冲突类型。"""
    try:
        yield
    except IntegrityError as error:
        raise ResearchLibraryConflict(str(error.orig)) from error


class PostgresResearchLibraryRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def _connect(self) -> Connection:
        return self._database.start().connect()

    # --- 文档 ---

    def create_document(self, document: ResearchDocument) -> ResearchDocument:
        with _conflicts(), self._database.start().begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO research_documents (document_id, title, document_type, "
                    "author, institution, source_weight, current_version_id, visibility_scope, "
                    "owner_id, access_tags_json, created_at, deleted_at, purge_after) VALUES "
                    "(:document_id, :title, :document_type, :author, :institution, "
                    ":source_weight, :current_version_id, :visibility_scope, :owner_id, "
                    "CAST(:access_tags AS JSONB), :created_at, :deleted_at, :purge_after)"
                ),
                {
                    "document_id": document.document_id,
                    "title": document.title,
                    "document_type": document.document_type.value,
                    "author": document.author,
                    "institution": document.institution,
                    "source_weight": document.source_weight,
                    "current_version_id": document.current_version_id,
                    "visibility_scope": document.visibility_scope,
                    "owner_id": document.owner_id,
                    "access_tags": _dumps(list(document.access_tags)),
                    "created_at": _stamp(document.created_at),
                    "deleted_at": _optional_stamp(document.deleted_at),
                    "purge_after": _optional_stamp(document.purge_after),
                },
            )
        return document

    def get_document(self, document_id: str) -> ResearchDocument | None:
        with self._connect() as connection:
            return self._load_document(connection, document_id)

    def list_documents(
        self, *, include_deleted: bool = False, limit: int = 100
    ) -> tuple[ResearchDocument, ...]:
        clause = "" if include_deleted else "WHERE deleted_at IS NULL "
        with self._connect() as connection:
            rows = connection.execute(
                text(
                    f"SELECT {DOCUMENT_COLUMNS} FROM research_documents {clause}"
                    "ORDER BY created_at DESC, document_id LIMIT :limit"
                ),
                {"limit": limit},
            ).fetchall()
        return tuple(_document_of(row._mapping) for row in rows)

    def set_current_version(self, document_id: str, document_version_id: str) -> None:
        with self._database.start().begin() as connection:
            result = connection.execute(
                text(
                    "UPDATE research_documents SET current_version_id = :document_version_id "
                    "WHERE document_id = :document_id"
                ),
                {"document_id": document_id, "document_version_id": document_version_id},
            )
            if result.rowcount != 1:
                raise ResearchLibraryConflict(f"document {document_id!r} does not exist")

    def soft_delete_document(
        self, document_id: str, *, now: datetime, retention_days: int
    ) -> ResearchDocument:
        if retention_days <= 0:
            raise ValueError("retention_days must be positive")
        purge_after = now + timedelta(days=retention_days)
        with self._database.start().begin() as connection:
            result = connection.execute(
                text(
                    "UPDATE research_documents SET deleted_at = :deleted_at, "
                    "purge_after = :purge_after "
                    "WHERE document_id = :document_id AND deleted_at IS NULL"
                ),
                {
                    "document_id": document_id,
                    "deleted_at": _stamp(now),
                    "purge_after": _stamp(purge_after),
                },
            )
            if result.rowcount != 1:
                raise ResearchLibraryConflict(
                    f"document {document_id!r} is missing or already deleted"
                )
            document = self._load_document(connection, document_id)
        assert document is not None
        return document

    def restore_document(self, document_id: str, *, now: datetime) -> ResearchDocument:
        with self._database.start().begin() as connection:
            result = connection.execute(
                text(
                    "UPDATE research_documents SET deleted_at = NULL, purge_after = NULL "
                    "WHERE document_id = :document_id AND deleted_at IS NOT NULL"
                ),
                {"document_id": document_id},
            )
            if result.rowcount != 1:
                raise ResearchLibraryConflict(f"document {document_id!r} is missing or not deleted")
            document = self._load_document(connection, document_id)
        assert document is not None
        return document

    def set_source_weight(self, document_id: str, *, source_weight: Decimal) -> ResearchDocument:
        """改来源权重。`deleted_at IS NULL` 是条件的一部分，理由见端口文档。"""
        with self._database.start().begin() as connection:
            result = connection.execute(
                text(
                    "UPDATE research_documents SET source_weight = :source_weight "
                    "WHERE document_id = :document_id AND deleted_at IS NULL"
                ),
                {"document_id": document_id, "source_weight": source_weight},
            )
            if result.rowcount != 1:
                raise ResearchLibraryConflict(
                    f"document {document_id!r} is missing or deleted; restore it before "
                    f"changing its source weight"
                )
            document = self._load_document(connection, document_id)
        assert document is not None
        return document

    def purge_document(
        self, document_id: str, *, now: datetime, audit: DocumentAuditEntry
    ) -> ResearchDocument:
        """物理清理：删块、置版本为 PURGED、标记资产、写下审计。全部在一个事务里。"""
        if audit.document_id != document_id:
            raise ValueError("the purge audit entry belongs to another document")
        moment = _stamp(now)
        with _conflicts(), self._database.start().begin() as connection:
            result = connection.execute(
                text(
                    "UPDATE research_documents SET current_version_id = NULL "
                    "WHERE document_id = :document_id AND deleted_at IS NOT NULL "
                    "AND purge_after IS NOT NULL AND purge_after <= :now"
                ),
                {"document_id": document_id, "now": moment},
            )
            if result.rowcount != 1:
                raise ResearchLibraryConflict(
                    f"document {document_id!r} is not deleted, has no retention deadline, or "
                    f"its retention period has not expired yet"
                )
            connection.execute(
                text("DELETE FROM research_chunks WHERE document_id = :document_id"),
                {"document_id": document_id},
            )
            connection.execute(
                text(
                    "UPDATE research_document_versions SET status = :purged "
                    "WHERE document_id = :document_id AND status <> :purged"
                ),
                {"document_id": document_id, "purged": DocumentVersionStatus.PURGED.value},
            )
            connection.execute(
                text(
                    "UPDATE research_document_assets SET deleted_at = :now "
                    "WHERE document_id = :document_id AND deleted_at IS NULL"
                ),
                {"document_id": document_id, "now": moment},
            )
            self._insert_document_audit(connection, audit)
            document = self._load_document(connection, document_id)
        assert document is not None
        return document

    # --- 清理与审计 ---

    def append_document_audit(self, entry: DocumentAuditEntry) -> DocumentAuditEntry:
        with _conflicts(), self._database.start().begin() as connection:
            self._insert_document_audit(connection, entry)
        return entry

    def list_document_audit(
        self, document_id: str, *, limit: int = 100
    ) -> tuple[DocumentAuditEntry, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                text(
                    f"SELECT {DOCUMENT_AUDIT_COLUMNS} FROM research_document_audit "
                    "WHERE document_id = :document_id "
                    "ORDER BY created_at, audit_id LIMIT :limit"
                ),
                {"document_id": document_id, "limit": limit},
            ).fetchall()
        return tuple(_document_audit_of(row._mapping) for row in rows)

    @staticmethod
    def _insert_document_audit(connection: Connection, entry: DocumentAuditEntry) -> None:
        connection.execute(
            text(
                "INSERT INTO research_document_audit (audit_id, document_id, "
                "document_version_id, action, actor, detail, created_at) VALUES (:audit_id, "
                ":document_id, :document_version_id, :action, :actor, :detail, :created_at)"
            ),
            {
                "audit_id": entry.audit_id,
                "document_id": entry.document_id,
                "document_version_id": entry.document_version_id,
                "action": entry.action.value,
                "actor": entry.actor,
                "detail": entry.detail,
                "created_at": _stamp(entry.created_at),
            },
        )

    @staticmethod
    def _load_document(connection: Connection, document_id: str) -> ResearchDocument | None:
        row = connection.execute(
            text(
                f"SELECT {DOCUMENT_COLUMNS} FROM research_documents "
                "WHERE document_id = :document_id"
            ),
            {"document_id": document_id},
        ).first()
        return None if row is None else _document_of(row._mapping)

    # --- 文档版本 ---

    def create_version(
        self, version: ResearchDocumentVersion, *, upload_key: str | None = None
    ) -> ResearchDocumentVersion:
        """按上传幂等键去重：同一个键 + 同一个内容散列返回既有版本，不新增行。"""
        with _conflicts(), self._database.start().begin() as connection:
            if upload_key is not None:
                existing = self._load_version_by_upload_key(connection, upload_key)
                if existing is not None:
                    if existing.original_file_hash != version.original_file_hash:
                        raise ResearchLibraryConflict(
                            f"upload key {upload_key!r} was already used for different content"
                        )
                    return existing
            connection.execute(
                text(
                    "INSERT INTO research_document_versions (document_version_id, document_id, "
                    "version_number, status, upload_key, published_at, effective_from, "
                    "effective_to, uploaded_at, original_file_hash, parser_version, "
                    "chunking_policy_version, ocr_provider, ocr_model_version, "
                    "embedding_provider, embedding_model_version, index_generation, "
                    "expected_chunk_count, indexed_at) VALUES (:document_version_id, "
                    ":document_id, :version_number, :status, :upload_key, :published_at, "
                    ":effective_from, :effective_to, :uploaded_at, :original_file_hash, "
                    ":parser_version, :chunking_policy_version, :ocr_provider, "
                    ":ocr_model_version, :embedding_provider, :embedding_model_version, "
                    ":index_generation, :expected_chunk_count, :indexed_at)"
                ),
                {
                    "document_version_id": version.document_version_id,
                    "document_id": version.document_id,
                    "version_number": version.version_number,
                    "status": version.status.value,
                    "upload_key": upload_key,
                    "published_at": _optional_stamp(version.published_at),
                    "effective_from": _optional_stamp(version.effective_from),
                    "effective_to": _optional_stamp(version.effective_to),
                    "uploaded_at": _stamp(version.uploaded_at),
                    "original_file_hash": version.original_file_hash,
                    "parser_version": version.parser_version,
                    "chunking_policy_version": version.chunking_policy_version,
                    "ocr_provider": version.ocr_provider,
                    "ocr_model_version": version.ocr_model_version,
                    "embedding_provider": version.embedding_provider,
                    "embedding_model_version": version.embedding_model_version,
                    "index_generation": version.index_generation,
                    "expected_chunk_count": version.expected_chunk_count,
                    "indexed_at": _optional_stamp(version.indexed_at),
                },
            )
        return version

    def get_version(self, document_version_id: str) -> ResearchDocumentVersion | None:
        with self._connect() as connection:
            row = connection.execute(
                text(
                    f"SELECT {VERSION_COLUMNS} FROM research_document_versions "
                    "WHERE document_version_id = :document_version_id"
                ),
                {"document_version_id": document_version_id},
            ).first()
        return None if row is None else _version_of(row._mapping)

    def list_versions(self, document_id: str) -> tuple[ResearchDocumentVersion, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                text(
                    f"SELECT {VERSION_COLUMNS} FROM research_document_versions "
                    "WHERE document_id = :document_id ORDER BY version_number"
                ),
                {"document_id": document_id},
            ).fetchall()
        return tuple(_version_of(row._mapping) for row in rows)

    def load_version_statuses(
        self, document_version_ids: Sequence[str]
    ) -> dict[str, DocumentVersionStatus]:
        """只取状态：可见性复核会在每次检索的候选上调用它。

        `JOIN research_documents` 与 `deleted_at IS NULL` 不是可以省掉的过滤：软删除只改文档
        行（规格 16.3 第 1 步），版本行的 `status` 仍然是 `ACTIVE`。不在这里把已删除文档名下的
        版本剔出去，"检索立即过滤"（第 2 步）就只能靠调用方各自记得再查一次文档——而三个调用
        方（检索复核、索引命中过滤、已接纳证据可见性）都把"查不到"当作"不可用"，漏掉一次就
        是"删掉的材料照旧可引用"。
        """
        if not document_version_ids:
            return {}
        with self._connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT v.document_version_id, v.status "
                    "FROM research_document_versions v "
                    "JOIN research_documents d ON d.document_id = v.document_id "
                    "WHERE v.document_version_id = ANY(CAST(:ids AS TEXT[])) "
                    "AND d.deleted_at IS NULL"
                ),
                {"ids": list(document_version_ids)},
            ).fetchall()
        return {str(row[0]): DocumentVersionStatus(row[1]) for row in rows}

    def activate_version(
        self, document_version_id: str, *, expected_status: DocumentVersionStatus
    ) -> None:
        """在一个事务里让新版本生效并让旧版本失效。

        顺序刻意是先失效再生效：一个文档最多只能有一个 ACTIVE 版本由部分唯一索引
        兜底，反过来写会先撞上那个索引。
        """
        now = datetime.now(UTC)
        with _conflicts(), self._database.start().begin() as connection:
            row = connection.execute(
                text(
                    "SELECT document_id, status FROM research_document_versions "
                    "WHERE document_version_id = :document_version_id FOR UPDATE"
                ),
                {"document_version_id": document_version_id},
            ).first()
            if row is None:
                raise ResearchLibraryConflict(
                    f"document version {document_version_id!r} does not exist"
                )
            document_id = str(row[0])

            connection.execute(
                text(
                    "UPDATE research_document_versions SET status = :superseded "
                    "WHERE document_id = :document_id AND status = :active "
                    "AND document_version_id <> :document_version_id"
                ),
                {
                    "superseded": DocumentVersionStatus.SUPERSEDED.value,
                    "active": DocumentVersionStatus.ACTIVE.value,
                    "document_id": document_id,
                    "document_version_id": document_version_id,
                },
            )
            activated = connection.execute(
                text(
                    "UPDATE research_document_versions "
                    "SET status = :active, published_at = COALESCE(published_at, :now) "
                    "WHERE document_version_id = :document_version_id AND status = :expected"
                ),
                {
                    "active": DocumentVersionStatus.ACTIVE.value,
                    "now": _stamp(now),
                    "document_version_id": document_version_id,
                    "expected": expected_status.value,
                },
            )
            if activated.rowcount != 1:
                raise ResearchLibraryConflict(
                    f"document version {document_version_id!r} is no longer {expected_status}"
                )
            connection.execute(
                text(
                    "UPDATE research_documents SET current_version_id = :document_version_id "
                    "WHERE document_id = :document_id"
                ),
                {"document_id": document_id, "document_version_id": document_version_id},
            )

    def archive_version(
        self, document_version_id: str, *, expected_status: DocumentVersionStatus
    ) -> ResearchDocumentVersion:
        """归档一版，并在同一个事务里让文档不再指向它。"""
        allowed = (
            DocumentVersionStatus.ACTIVE.value,
            DocumentVersionStatus.SUPERSEDED.value,
        )
        if expected_status.value not in allowed:
            raise ValueError(
                f"a {expected_status} version cannot be archived; only ACTIVE or SUPERSEDED "
                f"versions are in the serving set"
            )
        with _conflicts(), self._database.start().begin() as connection:
            row = connection.execute(
                text(
                    "SELECT document_id FROM research_document_versions "
                    "WHERE document_version_id = :document_version_id FOR UPDATE"
                ),
                {"document_version_id": document_version_id},
            ).first()
            if row is None:
                raise ResearchLibraryConflict(
                    f"document version {document_version_id!r} does not exist"
                )
            result = connection.execute(
                text(
                    "UPDATE research_document_versions SET status = :archived "
                    "WHERE document_version_id = :document_version_id AND status = :expected"
                ),
                {
                    "archived": DocumentVersionStatus.ARCHIVED.value,
                    "document_version_id": document_version_id,
                    "expected": expected_status.value,
                },
            )
            if result.rowcount != 1:
                raise ResearchLibraryConflict(
                    f"document version {document_version_id!r} is no longer {expected_status}"
                )
            connection.execute(
                text(
                    "UPDATE research_documents SET current_version_id = NULL "
                    "WHERE document_id = :document_id "
                    "AND current_version_id = :document_version_id"
                ),
                {"document_id": str(row[0]), "document_version_id": document_version_id},
            )
            archived = connection.execute(
                text(
                    f"SELECT {VERSION_COLUMNS} FROM research_document_versions "
                    "WHERE document_version_id = :document_version_id"
                ),
                {"document_version_id": document_version_id},
            ).first()
        assert archived is not None
        return _version_of(archived._mapping)

    @staticmethod
    def _load_version_by_upload_key(
        connection: Connection, upload_key: str
    ) -> ResearchDocumentVersion | None:
        row = connection.execute(
            text(
                f"SELECT {VERSION_COLUMNS} FROM research_document_versions "
                "WHERE upload_key = :upload_key"
            ),
            {"upload_key": upload_key},
        ).first()
        return None if row is None else _version_of(row._mapping)

    def save_version_metadata(
        self, version: ResearchDocumentVersion, *, expected_status: DocumentVersionStatus
    ) -> ResearchDocumentVersion:
        """写入解析与索引口径；状态不是 PROCESSING 时拒绝。

        条件里带 `status` 而不是只带 id：一个已经被取消或被别的 attempt 推进的版本，不该
        还能被这次 attempt 补上一行口径描述——那会让版本记录看起来像是当前这次跑出来的。

        `published_at` 用 `COALESCE(published_at, :published_at)`：列上已经有值时那个值
        优先。索引记录的 `published_at` 标量必须与这一列逐字相同，而流水线在写索引之前会
        先把它定下来（`_settle_published_at`）——这里保留"列优先"是为了让那次落库之外
        的调用方（比如直接激活一行的维护脚本）不会被顺手改掉一个已经公布的日期。
        """
        with _conflicts(), self._database.start().begin() as connection:
            result = connection.execute(
                text(
                    "UPDATE research_document_versions SET parser_version = :parser_version, "
                    "chunking_policy_version = :chunking_policy_version, "
                    "ocr_provider = :ocr_provider, ocr_model_version = :ocr_model_version, "
                    "embedding_provider = :embedding_provider, "
                    "embedding_model_version = :embedding_model_version, "
                    "index_generation = :index_generation, "
                    "expected_chunk_count = :expected_chunk_count, indexed_at = :indexed_at, "
                    "published_at = COALESCE(published_at, :published_at) "
                    "WHERE document_version_id = :document_version_id AND status = :expected"
                ),
                {
                    "document_version_id": version.document_version_id,
                    "parser_version": version.parser_version,
                    "chunking_policy_version": version.chunking_policy_version,
                    "ocr_provider": version.ocr_provider,
                    "ocr_model_version": version.ocr_model_version,
                    "embedding_provider": version.embedding_provider,
                    "embedding_model_version": version.embedding_model_version,
                    "index_generation": version.index_generation,
                    "expected_chunk_count": version.expected_chunk_count,
                    "indexed_at": _optional_stamp(version.indexed_at),
                    "published_at": _optional_stamp(version.published_at),
                    "expected": expected_status.value,
                },
            )
            if result.rowcount != 1:
                raise ResearchLibraryConflict(
                    f"document version {version.document_version_id!r} is no longer "
                    f"{expected_status}"
                )
        return version

    def get_original_asset_key(self, document_version_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                text(
                    "SELECT object_key FROM research_document_assets "
                    "WHERE document_version_id = :document_version_id "
                    "AND asset_role = :original AND deleted_at IS NULL "
                    "ORDER BY created_at LIMIT 1"
                ),
                {
                    "document_version_id": document_version_id,
                    "original": AssetRole.ORIGINAL.value,
                },
            ).first()
        return None if row is None else str(row[0])

    # --- 资产 ---

    def register_asset(self, asset: ResearchDocumentAsset) -> ResearchDocumentAsset:
        with _conflicts(), self._database.start().begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO research_document_assets (asset_id, document_id, "
                    "document_version_id, asset_role, object_key, content_type, byte_size, "
                    "sha256, page_number, scan_status, scan_detail, created_at, deleted_at) "
                    "VALUES (:asset_id, :document_id, :document_version_id, :asset_role, "
                    ":object_key, :content_type, :byte_size, :sha256, :page_number, "
                    ":scan_status, :scan_detail, :created_at, :deleted_at)"
                ),
                {
                    "asset_id": asset.asset_id,
                    "document_id": asset.document_id,
                    "document_version_id": asset.document_version_id,
                    "asset_role": asset.asset_role.value,
                    "object_key": asset.object_key,
                    "content_type": asset.content_type,
                    "byte_size": asset.byte_size,
                    "sha256": asset.sha256,
                    "page_number": asset.page_number,
                    "scan_status": asset.scan_status.value,
                    "scan_detail": asset.scan_detail,
                    "created_at": _stamp(asset.created_at),
                    "deleted_at": _optional_stamp(asset.deleted_at),
                },
            )
        return asset

    def list_asset_keys(self, document_version_id: str) -> tuple[str, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT object_key FROM research_document_assets "
                    "WHERE document_version_id = :document_version_id AND deleted_at IS NULL "
                    "ORDER BY created_at, asset_id"
                ),
                {"document_version_id": document_version_id},
            ).fetchall()
        return tuple(str(row[0]) for row in rows)

    # --- 切片 ---

    def append_chunks(self, chunks: Sequence[ResearchChunk]) -> None:
        if not chunks:
            return
        with _conflicts(), self._database.start().begin() as connection:
            highest = connection.execute(
                text(
                    "SELECT COALESCE(MAX(chunk_order), -1) FROM research_chunks "
                    "WHERE document_version_id = :document_version_id"
                ),
                {"document_version_id": chunks[0].document_version_id},
            ).scalar_one()
            for order, chunk in enumerate(chunks, start=int(highest) + 1):
                connection.execute(
                    text(
                        "INSERT INTO research_chunks (chunk_id, document_id, "
                        "document_version_id, parent_chunk_id, chunk_order, chunk_type, "
                        "content, content_hash, source_json, content_origin, confidence, "
                        "requires_verification, embedding_status, created_at) VALUES "
                        "(:chunk_id, :document_id, :document_version_id, :parent_chunk_id, "
                        ":chunk_order, :chunk_type, :content, :content_hash, "
                        "CAST(:source AS JSONB), :content_origin, :confidence, "
                        ":requires_verification, :embedding_status, :created_at)"
                    ),
                    {
                        "chunk_id": chunk.chunk_id,
                        "document_id": chunk.document_id,
                        "document_version_id": chunk.document_version_id,
                        "parent_chunk_id": chunk.parent_chunk_id,
                        "chunk_order": order,
                        "chunk_type": chunk.chunk_type.value,
                        "content": chunk.content,
                        "content_hash": chunk.content_hash,
                        "source": chunk.source.model_dump_json(),
                        "content_origin": chunk.content_origin.value,
                        "confidence": chunk.confidence,
                        "requires_verification": _flag(chunk.requires_verification),
                        "embedding_status": chunk.embedding_status.value,
                        "created_at": _stamp(chunk.created_at),
                    },
                )

    def get_chunk(self, chunk_id: str) -> ResearchChunk | None:
        with self._connect() as connection:
            row = connection.execute(
                text(f"SELECT {CHUNK_COLUMNS} FROM research_chunks WHERE chunk_id = :chunk_id"),
                {"chunk_id": chunk_id},
            ).first()
        return None if row is None else _chunk_of(row._mapping)

    def load_chunks(self, chunk_ids: Sequence[str]) -> dict[str, ResearchChunk]:
        """按 ID 批量取切片；查不到的 ID 安静地缺席，`filter_active_hits` 同理。"""
        if not chunk_ids:
            return {}
        with self._connect() as connection:
            rows = connection.execute(
                text(
                    f"SELECT {CHUNK_COLUMNS} FROM research_chunks "
                    "WHERE chunk_id = ANY(CAST(:ids AS TEXT[]))"
                ),
                {"ids": list(chunk_ids)},
            ).fetchall()
        chunks = [_chunk_of(row._mapping) for row in rows]
        return {chunk.chunk_id: chunk for chunk in chunks}

    def list_chunks(
        self, document_version_id: str, *, limit: int = 500
    ) -> tuple[ResearchChunk, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                text(
                    f"SELECT {CHUNK_COLUMNS} FROM research_chunks "
                    "WHERE document_version_id = :document_version_id "
                    "ORDER BY chunk_order LIMIT :limit"
                ),
                {"document_version_id": document_version_id, "limit": limit},
            ).fetchall()
        return tuple(_chunk_of(row._mapping) for row in rows)

    def count_chunks(self, document_version_id: str) -> int:
        with self._connect() as connection:
            return int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM research_chunks "
                        "WHERE document_version_id = :document_version_id"
                    ),
                    {"document_version_id": document_version_id},
                ).scalar_one()
            )

    def mark_chunks_embedded(self, chunk_ids: Sequence[str]) -> None:
        if not chunk_ids:
            return
        with self._database.start().begin() as connection:
            connection.execute(
                text(
                    "UPDATE research_chunks SET embedding_status = :embedded "
                    "WHERE chunk_id = ANY(CAST(:ids AS TEXT[]))"
                ),
                {"embedded": ChunkEmbeddingStatus.EMBEDDED.value, "ids": list(chunk_ids)},
            )

    # --- 摄取任务 ---

    def create_ingestion_job(self, job: IngestionJob) -> IngestionJob:
        with _conflicts(), self._database.start().begin() as connection:
            self._insert_job(connection, job)
        return job

    def get_ingestion_job(self, job_id: str) -> IngestionJob | None:
        with self._connect() as connection:
            return self._load_job(connection, job_id)

    def acquire_ingestion_job(
        self, job_id: str, *, worker_id: str, now: datetime, lease_seconds: int
    ) -> IngestionJob:
        """取得或接管租约；接管只在旧租约过期时发生，并产生新的 attempt。"""
        with _conflicts(), self._database.start().begin() as connection:
            job = self._load_job(connection, job_id, for_update=True)
            if job is None:
                raise ResearchLibraryConflict(f"ingestion job {job_id!r} does not exist")
            try:
                claimed = acquire_ingestion_lease(
                    job, now=now, worker_id=worker_id, lease_seconds=lease_seconds
                )
            except (IngestionLeaseLost, InvalidIngestionTransition) as error:
                raise ResearchLibraryConflict(str(error)) from error

            result = connection.execute(
                text(
                    "UPDATE research_ingestion_jobs SET attempt_id = :attempt_id, "
                    "worker_id = :worker_id, lease_expires_at = :lease_expires_at, "
                    "updated_at = :updated_at WHERE job_id = :job_id "
                    "AND status = :expected_status AND attempt_id = :expected_attempt "
                    "AND worker_id IS NOT DISTINCT FROM :expected_worker"
                ),
                {
                    "job_id": job_id,
                    "attempt_id": claimed.attempt_id,
                    "worker_id": claimed.worker_id,
                    "lease_expires_at": _optional_stamp(claimed.lease_expires_at),
                    "updated_at": _stamp(claimed.updated_at),
                    "expected_status": job.status.value,
                    "expected_attempt": job.attempt_id,
                    "expected_worker": job.worker_id,
                },
            )
            if result.rowcount != 1:
                raise ResearchLibraryConflict(
                    f"ingestion job {job_id!r} was leased by another worker first"
                )
        return claimed

    def save_ingestion_job(
        self, job: IngestionJob, *, expected_status: IngestionStatus, expected_attempt: int
    ) -> IngestionJob:
        """写入任务的新状态；旧状态或旧 attempt 已被别人替换时拒绝。"""
        with _conflicts(), self._database.start().begin() as connection:
            result = connection.execute(
                text(
                    "UPDATE research_ingestion_jobs SET status = :status, "
                    "attempt_id = :attempt_id, worker_id = :worker_id, "
                    "lease_expires_at = :lease_expires_at, failure_reason = :failure_reason, "
                    "updated_at = :updated_at WHERE job_id = :job_id "
                    "AND status = :expected_status AND attempt_id = :expected_attempt"
                ),
                {
                    "job_id": job.job_id,
                    "status": job.status.value,
                    "attempt_id": job.attempt_id,
                    "worker_id": job.worker_id,
                    "lease_expires_at": _optional_stamp(job.lease_expires_at),
                    "failure_reason": job.failure_reason,
                    "updated_at": _stamp(job.updated_at),
                    "expected_status": expected_status.value,
                    "expected_attempt": expected_attempt,
                },
            )
            if result.rowcount != 1:
                raise ResearchLibraryConflict(
                    f"ingestion job {job.job_id!r} is no longer "
                    f"{expected_status} at attempt {expected_attempt}"
                )
        return job

    def list_ingestion_jobs(
        self,
        *,
        document_id: str | None = None,
        document_version_id: str | None = None,
        limit: int = 100,
    ) -> tuple[IngestionJob, ...]:
        """按文档或版本取任务，最新的在前。两个条件都给时取交集。"""
        if document_id is None and document_version_id is None:
            raise ValueError(
                "listing every ingestion job of every document is not a query this "
                "port offers; name a document or a version"
            )
        clauses: list[str] = []
        parameters: dict[str, object] = {"limit": limit}
        if document_id is not None:
            clauses.append("document_id = :document_id")
            parameters["document_id"] = document_id
        if document_version_id is not None:
            clauses.append("document_version_id = :document_version_id")
            parameters["document_version_id"] = document_version_id
        with self._connect() as connection:
            rows = connection.execute(
                text(
                    f"SELECT {JOB_COLUMNS} FROM research_ingestion_jobs "
                    f"WHERE {' AND '.join(clauses)} "
                    "ORDER BY created_at DESC, job_id LIMIT :limit"
                ),
                parameters,
            ).fetchall()
        return tuple(_job_of(row._mapping) for row in rows)

    def requeue_ingestion_job(
        self, job_id: str, *, now: datetime, expected_status: IngestionStatus
    ) -> IngestionJob:
        """把失败的任务重排到队列开头；状态不是期望的那一个时拒绝。"""
        with _conflicts(), self._database.start().begin() as connection:
            job = self._load_job(connection, job_id, for_update=True)
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
            result = connection.execute(
                text(
                    "UPDATE research_ingestion_jobs SET status = :status, "
                    "attempt_id = :attempt_id, "
                    "worker_id = NULL, lease_expires_at = NULL, failure_reason = NULL, "
                    "updated_at = :updated_at WHERE job_id = :job_id "
                    "AND status = :expected_status AND attempt_id = :expected_attempt"
                ),
                {
                    "job_id": job_id,
                    "status": requeued.status.value,
                    "attempt_id": requeued.attempt_id,
                    "updated_at": _stamp(requeued.updated_at),
                    "expected_status": expected_status.value,
                    "expected_attempt": job.attempt_id,
                },
            )
            if result.rowcount != 1:
                raise ResearchLibraryConflict(
                    f"ingestion job {job_id!r} is no longer {expected_status}"
                )
        return requeued

    @staticmethod
    def _insert_job(connection: Connection, job: IngestionJob) -> None:
        connection.execute(
            text(
                "INSERT INTO research_ingestion_jobs (job_id, document_id, "
                "document_version_id, status, attempt_id, worker_id, lease_expires_at, "
                "max_attempts, failure_reason, created_at, updated_at) VALUES (:job_id, "
                ":document_id, :document_version_id, :status, :attempt_id, :worker_id, "
                ":lease_expires_at, :max_attempts, :failure_reason, :created_at, :updated_at)"
            ),
            {
                "job_id": job.job_id,
                "document_id": job.document_id,
                "document_version_id": job.document_version_id,
                "status": job.status.value,
                "attempt_id": job.attempt_id,
                "worker_id": job.worker_id,
                "lease_expires_at": _optional_stamp(job.lease_expires_at),
                "max_attempts": job.max_attempts,
                "failure_reason": job.failure_reason,
                "created_at": _stamp(job.created_at),
                "updated_at": _stamp(job.updated_at),
            },
        )

    def _load_job(
        self, connection: Connection, job_id: str, *, for_update: bool = False
    ) -> IngestionJob | None:
        lock = " FOR UPDATE" if for_update else ""
        row = connection.execute(
            text(f"SELECT {JOB_COLUMNS} FROM research_ingestion_jobs WHERE job_id = :job_id{lock}"),
            {"job_id": job_id},
        ).first()
        return None if row is None else _job_of(row._mapping)

    # --- 派生索引 outbox ---

    def enqueue_index_event(self, event: IndexOutboxEvent) -> IndexOutboxEvent:
        """登记索引变更意图；同一个 `event_id` 已经存在时原样返回既有那一行。

        正在被认领、或已经失败等待重试的事件一律不动（`DO UPDATE ... WHERE status = DONE`）：
        重放一次摄取不该把别人的认领抹掉，也不该抹掉失败原因。`DONE` 是唯一的例外，因为
        重新登记它是有意义的：`event_id` 由 generation 决定，重建一代索引登记的正是同一条
        意图，而那一代可能早就发布过、事件已经落成 `DONE`。不重新激活它，重建写回去的切片
        会永远停在 STAGED，复核会说"还没发布"——那是一个重写就能修好、却怎么也修不好的状态。
        """
        with _conflicts(), self._database.start().begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO research_index_outbox (event_id, document_version_id, "
                    "index_generation, operation, status, payload_json, attempt_count, "
                    "claimed_by, claimed_at, available_at, last_error, created_at) VALUES "
                    "(:event_id, :document_version_id, :index_generation, :operation, "
                    ":status, CAST(:payload AS JSONB), :attempt_count, :claimed_by, "
                    ":claimed_at, :available_at, :last_error, :created_at) "
                    "ON CONFLICT (event_id) DO UPDATE SET "
                    "status = EXCLUDED.status, attempt_count = EXCLUDED.attempt_count, "
                    "claimed_by = EXCLUDED.claimed_by, claimed_at = EXCLUDED.claimed_at, "
                    "available_at = EXCLUDED.available_at, last_error = EXCLUDED.last_error "
                    "WHERE research_index_outbox.status = :done"
                ),
                {
                    "event_id": event.event_id,
                    "document_version_id": event.document_version_id,
                    "index_generation": event.index_generation,
                    "operation": event.operation.value,
                    "status": event.status.value,
                    "payload": _dumps(event.payload),
                    "attempt_count": event.attempt_count,
                    "claimed_by": event.claimed_by,
                    "claimed_at": _optional_stamp(event.claimed_at),
                    "available_at": _stamp(event.available_at),
                    "last_error": event.last_error,
                    "created_at": _stamp(event.created_at),
                    "done": OutboxStatus.DONE.value,
                },
            )
            row = connection.execute(
                text(
                    f"SELECT {OUTBOX_COLUMNS} FROM research_index_outbox WHERE event_id = :event_id"
                ),
                {"event_id": event.event_id},
            ).first()
        assert row is not None
        return _outbox_of(row._mapping)

    def claim_outbox_events(
        self, *, worker_id: str, now: datetime, limit: int = 10
    ) -> tuple[IndexOutboxEvent, ...]:
        """认领可执行的事件；`SKIP LOCKED` 让并发 worker 直接跳过彼此而不是排队。"""
        stale_before = _stamp(now - timedelta(seconds=CLAIM_STALE_SECONDS))
        with _conflicts(), self._database.start().begin() as connection:
            rows = connection.execute(
                text(
                    f"SELECT {OUTBOX_COLUMNS} FROM research_index_outbox "
                    "WHERE available_at <= :now AND (status IN (:pending, :failed) "
                    "OR (status = :claimed AND claimed_at <= :stale_before)) "
                    "ORDER BY available_at, event_id LIMIT :limit FOR UPDATE SKIP LOCKED"
                ),
                {
                    "now": _stamp(now),
                    "pending": OutboxStatus.PENDING.value,
                    "failed": OutboxStatus.FAILED.value,
                    "claimed": OutboxStatus.CLAIMED.value,
                    "stale_before": stale_before,
                    "limit": limit,
                },
            ).fetchall()

            events: list[IndexOutboxEvent] = []
            for row in rows:
                claimed = _outbox_of(row._mapping).model_copy(
                    update={
                        "status": OutboxStatus.CLAIMED,
                        "claimed_by": worker_id,
                        "claimed_at": now,
                        "attempt_count": int(row._mapping["attempt_count"]) + 1,
                    }
                )
                connection.execute(
                    text(
                        "UPDATE research_index_outbox SET status = :status, "
                        "claimed_by = :claimed_by, claimed_at = :claimed_at, "
                        "attempt_count = :attempt_count WHERE event_id = :event_id"
                    ),
                    {
                        "event_id": claimed.event_id,
                        "status": claimed.status.value,
                        "claimed_by": claimed.claimed_by,
                        "claimed_at": _stamp(now),
                        "attempt_count": claimed.attempt_count,
                    },
                )
                events.append(claimed)
        return tuple(events)

    def finish_outbox_event(
        self, event_id: str, *, worker_id: str, now: datetime, error: str | None = None
    ) -> IndexOutboxEvent:
        """结束事件；失败时释放认领，使下一个 worker 可以重试。"""
        status = OutboxStatus.FAILED if error else OutboxStatus.DONE
        with _conflicts(), self._database.start().begin() as connection:
            result = connection.execute(
                text(
                    "UPDATE research_index_outbox SET status = :status, claimed_by = NULL, "
                    "claimed_at = NULL, last_error = :last_error, available_at = :available_at "
                    "WHERE event_id = :event_id AND status = :claimed "
                    "AND claimed_by = :worker_id"
                ),
                {
                    "event_id": event_id,
                    "status": status.value,
                    "last_error": error,
                    "available_at": _stamp(now),
                    "claimed": OutboxStatus.CLAIMED.value,
                    "worker_id": worker_id,
                },
            )
            if result.rowcount != 1:
                raise ResearchLibraryConflict(
                    f"index outbox event {event_id!r} is not claimed by {worker_id!r}"
                )
            row = connection.execute(
                text(
                    f"SELECT {OUTBOX_COLUMNS} FROM research_index_outbox WHERE event_id = :event_id"
                ),
                {"event_id": event_id},
            ).first()
        assert row is not None
        return _outbox_of(row._mapping)

    # --- 检索审计 ---

    def record_retrieval_audit(self, audit: RetrievalAuditRecord) -> None:
        """只追加：同一次检索的审计记录不允许被后来的结果覆盖。"""
        with _conflicts(), self._database.start().begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO research_retrieval_audits (retrieval_id, run_id, task_id, "
                    "attempt_id, role, question, query_fingerprint, filters_json, "
                    "corpus_generation, provider_versions_json, dense_candidates_json, "
                    "bm25_candidates_json, fused_candidates_json, reranked_candidates_json, "
                    "parent_expansions_json, claims_json, conflicts_json, "
                    "returned_evidence_json, duration_ms, provider_calls, input_tokens, "
                    "output_tokens, cost_cny, created_at) VALUES (:retrieval_id, :run_id, "
                    ":task_id, :attempt_id, :role, :question, :query_fingerprint, "
                    "CAST(:filters AS JSONB), :corpus_generation, "
                    "CAST(:provider_versions AS JSONB), CAST(:dense_candidates AS JSONB), "
                    "CAST(:bm25_candidates AS JSONB), CAST(:fused_candidates AS JSONB), "
                    "CAST(:reranked_candidates AS JSONB), CAST(:parent_expansions AS JSONB), "
                    "CAST(:claims AS JSONB), CAST(:conflicts AS JSONB), "
                    "CAST(:returned_evidence AS JSONB), :duration_ms, :provider_calls, "
                    ":input_tokens, :output_tokens, :cost_cny, :created_at)"
                ),
                {
                    "retrieval_id": audit.retrieval_id,
                    "run_id": audit.run_id,
                    "task_id": audit.task_id,
                    "attempt_id": audit.attempt_id,
                    "role": audit.role,
                    "question": audit.question,
                    "query_fingerprint": audit.query_fingerprint,
                    "filters": _dumps(audit.filters),
                    "corpus_generation": audit.corpus_generation,
                    "provider_versions": _dumps(audit.provider_versions),
                    "dense_candidates": _dumps(audit.dense_candidates),
                    "bm25_candidates": _dumps(audit.bm25_candidates),
                    "fused_candidates": _dumps(audit.fused_candidates),
                    "reranked_candidates": _dumps(audit.reranked_candidates),
                    "parent_expansions": _dumps(audit.parent_expansions),
                    "claims": _dumps(audit.claims),
                    "conflicts": _dumps(audit.conflicts),
                    "returned_evidence": _dumps(audit.returned_evidence),
                    "duration_ms": audit.duration_ms,
                    "provider_calls": audit.provider_calls,
                    "input_tokens": audit.input_tokens,
                    "output_tokens": audit.output_tokens,
                    "cost_cny": audit.cost_cny,
                    "created_at": _stamp(audit.created_at),
                },
            )

    def get_retrieval_audit(self, retrieval_id: str) -> RetrievalAuditRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                text(
                    f"SELECT {AUDIT_COLUMNS} FROM research_retrieval_audits "
                    "WHERE retrieval_id = :retrieval_id"
                ),
                {"retrieval_id": retrieval_id},
            ).first()
        return None if row is None else _audit_of(row._mapping)


def _document_of(values: RowMapping) -> ResearchDocument:
    return ResearchDocument.model_validate(
        {
            "document_id": values["document_id"],
            "title": values["title"],
            "document_type": DocumentType(values["document_type"]),
            "author": values["author"],
            "institution": values["institution"],
            "source_weight": Decimal(str(values["source_weight"])),
            "current_version_id": values["current_version_id"],
            "visibility_scope": values["visibility_scope"],
            "owner_id": values["owner_id"],
            "access_tags": tuple(_payload(values["access_tags_json"])),
            "created_at": _moment(values["created_at"]),
            "deleted_at": _optional_moment(values["deleted_at"]),
            "purge_after": _optional_moment(values["purge_after"]),
        }
    )


def _version_of(values: RowMapping) -> ResearchDocumentVersion:
    return ResearchDocumentVersion.model_validate(
        {
            "document_version_id": values["document_version_id"],
            "document_id": values["document_id"],
            "version_number": int(values["version_number"]),
            "status": DocumentVersionStatus(values["status"]),
            "published_at": _optional_moment(values["published_at"]),
            "effective_from": _optional_moment(values["effective_from"]),
            "effective_to": _optional_moment(values["effective_to"]),
            "uploaded_at": _moment(values["uploaded_at"]),
            "original_file_hash": values["original_file_hash"],
            "parser_version": values["parser_version"],
            "chunking_policy_version": values["chunking_policy_version"],
            "ocr_provider": values["ocr_provider"],
            "ocr_model_version": values["ocr_model_version"],
            "embedding_provider": values["embedding_provider"],
            "embedding_model_version": values["embedding_model_version"],
            "index_generation": values["index_generation"],
            "expected_chunk_count": values["expected_chunk_count"],
            "indexed_at": _optional_moment(values["indexed_at"]),
        }
    )


def _chunk_of(values: RowMapping) -> ResearchChunk:
    return ResearchChunk.model_validate(
        {
            "chunk_id": values["chunk_id"],
            "document_id": values["document_id"],
            "document_version_id": values["document_version_id"],
            "parent_chunk_id": values["parent_chunk_id"],
            "chunk_type": ChunkType(values["chunk_type"]),
            "content": values["content"],
            "content_hash": values["content_hash"],
            "source": SourceLocator.model_validate(_payload(values["source_json"])),
            "content_origin": ExtractionMethod(values["content_origin"]),
            "confidence": float(values["confidence"]),
            "requires_verification": bool(values["requires_verification"]),
            "embedding_status": ChunkEmbeddingStatus(values["embedding_status"]),
            "created_at": _moment(values["created_at"]),
        }
    )


def _job_of(values: RowMapping) -> IngestionJob:
    return IngestionJob.model_validate(
        {
            "job_id": values["job_id"],
            "document_id": values["document_id"],
            "document_version_id": values["document_version_id"],
            "status": IngestionStatus(values["status"]),
            "attempt_id": int(values["attempt_id"]),
            "worker_id": values["worker_id"],
            "lease_expires_at": _optional_moment(values["lease_expires_at"]),
            "max_attempts": int(values["max_attempts"]),
            "failure_reason": values["failure_reason"],
            "created_at": _moment(values["created_at"]),
            "updated_at": _moment(values["updated_at"]),
        }
    )


def _document_audit_of(values: RowMapping) -> DocumentAuditEntry:
    return DocumentAuditEntry.model_validate(
        {
            "audit_id": values["audit_id"],
            "document_id": values["document_id"],
            "document_version_id": values["document_version_id"],
            "action": DocumentAuditAction(values["action"]),
            "actor": values["actor"],
            "detail": values["detail"],
            "created_at": _moment(values["created_at"]),
        }
    )


def _outbox_of(values: RowMapping) -> IndexOutboxEvent:
    return IndexOutboxEvent.model_validate(
        {
            "event_id": values["event_id"],
            "document_version_id": values["document_version_id"],
            "index_generation": values["index_generation"],
            "operation": OutboxOperation(values["operation"]),
            "status": OutboxStatus(values["status"]),
            "payload": _payload(values["payload_json"]),
            "attempt_count": int(values["attempt_count"]),
            "claimed_by": values["claimed_by"],
            "claimed_at": _optional_moment(values["claimed_at"]),
            "available_at": _moment(values["available_at"]),
            "last_error": values["last_error"],
            "created_at": _moment(values["created_at"]),
        }
    )


def _audit_of(values: RowMapping) -> RetrievalAuditRecord:
    return RetrievalAuditRecord.model_validate(
        {
            "retrieval_id": values["retrieval_id"],
            "run_id": values["run_id"],
            "task_id": values["task_id"],
            "attempt_id": values["attempt_id"],
            "role": values["role"],
            "question": values["question"],
            "query_fingerprint": values["query_fingerprint"],
            "filters": _payload(values["filters_json"]),
            "corpus_generation": values["corpus_generation"],
            "provider_versions": _payload(values["provider_versions_json"]),
            "dense_candidates": _payload(values["dense_candidates_json"]),
            "bm25_candidates": _payload(values["bm25_candidates_json"]),
            "fused_candidates": _payload(values["fused_candidates_json"]),
            "reranked_candidates": _payload(values["reranked_candidates_json"]),
            "parent_expansions": _payload(values["parent_expansions_json"]),
            "claims": _payload(values["claims_json"]),
            "conflicts": _payload(values["conflicts_json"]),
            "returned_evidence": _payload(values["returned_evidence_json"]),
            "duration_ms": values["duration_ms"],
            "provider_calls": values["provider_calls"],
            "input_tokens": values["input_tokens"],
            "output_tokens": values["output_tokens"],
            "cost_cny": values["cost_cny"],
            "created_at": _moment(values["created_at"]),
        }
    )
