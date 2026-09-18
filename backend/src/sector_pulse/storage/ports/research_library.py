"""内部研究资料库权威存储的端口。

规格 4：PostgreSQL 是唯一权威状态源，MinIO 与 Milvus 只是可替换的派生侧。因此这个
端口只描述“权威状态怎么读写”，不出现任何对象键、向量或 collection 概念——那些属于
`ResearchAssetStore` 与 `VectorIndex` 各自的端口。

并发约定：所有会改变所有权或状态的方法都必须带上调用方认为当前成立的前置条件
（状态、attempt、worker），条件不成立时抛 `ResearchLibraryConflict` 而不是覆盖。
解析“当前该由谁写”是领域层的职责，这里只负责让那个判断在数据库里原子成立。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from sector_pulse.domain.research_library.audit import DocumentAuditEntry
from sector_pulse.domain.research_library.models import (
    DocumentVersionStatus,
    IndexOutboxEvent,
    IngestionJob,
    IngestionStatus,
    ResearchChunk,
    ResearchDocument,
    ResearchDocumentVersion,
)
from sector_pulse.domain.research_library.retrieval import (
    AcceptedEvidenceClaim,
    RetrievalAuditRecord,
)
from sector_pulse.ports.research_assets import ResearchDocumentAsset


class ResearchLibraryConflict(RuntimeError):
    """前置条件在数据库中已不成立：这次写入输给了一个并发的写入者。"""


@runtime_checkable
class AcceptedEvidenceRepositoryPort(Protocol):
    """已接纳内部证据的读取端。

    写入方是 `AcceptInternalEvidenceService`，它写的是权威库里的两张证据表；这里读的是同一
    批行。之所以单独立一个端口，而不是加在 `ResearchLibraryRepositoryPort` 上：那个端口描述的
    是"资料库怎么被治理"（文档、版本、切片、摄取），而这里要回答的是"这一份 Artifact 里的
    事实还站不站得住"——它同时要看证据行和这些行所引版本的当前状态，两者都在同一个权威库里，
    也都不属于治理动作。
    """

    def get_accepted_evidence(
        self, artifact_references: Sequence[str]
    ) -> tuple[AcceptedEvidenceClaim, ...]:
        """按 Artifact 引用取回其中被接纳的事实，未知引用不出现在结果里。

        批量而不是逐条：一次审校要把整个 run 的证据一次读齐，逐条查询会把一次检查变成几十次
        往返。返回顺序按 Artifact 引用与写入顺序稳定，便于审计比对。
        """
        ...

    def load_active_version_ids(
        self, document_version_ids: Sequence[str]
    ) -> frozenset[str]:
        """这些版本里当前仍然生效的那些。

        与 `ResearchLibraryRepositoryPort.load_version_statuses` 读的是同一张表，但回答的问题
        不同：这里只回答"还能不能引用"。查不到的版本 id 一律**不在**结果里——证明不了一份证据
        还站得住的时候，引用它就是不该做的事。
        """
        ...


@runtime_checkable
class ResearchLibraryRepositoryPort(Protocol):
    # --- 文档 ---

    def create_document(self, document: ResearchDocument) -> ResearchDocument: ...

    def get_document(self, document_id: str) -> ResearchDocument | None: ...

    def list_documents(
        self, *, include_deleted: bool = False, limit: int = 100
    ) -> tuple[ResearchDocument, ...]: ...

    def set_current_version(self, document_id: str, document_version_id: str) -> None: ...

    def soft_delete_document(
        self, document_id: str, *, now: datetime, retention_days: int
    ) -> ResearchDocument: ...

    def restore_document(self, document_id: str, *, now: datetime) -> ResearchDocument: ...

    def set_source_weight(
        self, document_id: str, *, source_weight: Decimal
    ) -> ResearchDocument:
        """改来源权重（规格 17）。

        规格 17 把"来源权重变更"列为必须推进 `corpus_generation` 的事件之一，而世代是由
        文档行算出来的（`cache.CorpusGeneration`），因此改权重必须是**这一行的写入**，不能
        是某个旁路表里的一条覆盖。软删除的文档拒绝：保留期内它可以被恢复，而恢复后的权重
        必须是删除前的那一个，否则"恢复"就不是恢复。

        返回更新后的文档；文档不存在或已软删除时抛 `ResearchLibraryConflict`。
        """
        ...

    # --- 清理与审计 ---

    def purge_document(
        self, document_id: str, *, now: datetime, audit: DocumentAuditEntry
    ) -> ResearchDocument:
        """物理清理一份软删除且保留期已过的文档（规格 16.3 第 5、6 步）。

        条件写在同一条语句里：`deleted_at IS NOT NULL AND purge_after IS NOT NULL AND
        purge_after <= :now`。调用方算出的"可以清理了"是**待核对的声明**，不是待执行的结论——
        两个线程拿着同一份过期快照各自清理一次，第二次必须失败而不是再清一遍。

        同一个事务里做四件事：删掉权威切片正文、把版本置为 `PURGED`、把资产行标记为已删除、
        写下那条不含正文的审计记录。审计必须与清理同一次事务，否则"清理成功但没留下痕迹"
        是一种可能的中间状态，而规格 16.3 明确要求留下痕迹。
        """
        ...

    def append_document_audit(self, entry: DocumentAuditEntry) -> DocumentAuditEntry:
        """记下一次治理动作。同一 `audit_id` 写两次是冲突，不是幂等重放。

        审计要回答的是"发生过几次"，因此内容相同的两次动作是两行；用 `ON CONFLICT DO
        NOTHING` 处理重复写入，会把第二次动作悄悄变成第一次的重复。
        """
        ...

    def list_document_audit(
        self, document_id: str, *, limit: int = 100
    ) -> tuple[DocumentAuditEntry, ...]:
        """一份文档的治理痕迹，按时间与 ID 稳定排序。"""
        ...

    # --- 文档版本 ---

    def create_version(
        self, version: ResearchDocumentVersion, *, upload_key: str | None = None
    ) -> ResearchDocumentVersion: ...

    def get_version(self, document_version_id: str) -> ResearchDocumentVersion | None: ...

    def list_versions(self, document_id: str) -> tuple[ResearchDocumentVersion, ...]: ...

    def load_version_statuses(
        self, document_version_ids: Sequence[str]
    ) -> dict[str, DocumentVersionStatus]: ...

    def activate_version(
        self, document_version_id: str, *, expected_status: DocumentVersionStatus
    ) -> None: ...

    def archive_version(
        self, document_version_id: str, *, expected_status: DocumentVersionStatus
    ) -> ResearchDocumentVersion:
        """归档一版：状态置 `ARCHIVED`，文档不再指向它（规格 16.4 的"失效向量"）。

        与 `activate_version` 同一种形态——条件更新，前置条件不成立就冲突。状态只能从
        ACTIVE 或 SUPERSEDED 归档：一个还在 PROCESSING 的版本有正在跑的摄取任务，归档它
        等于让那次任务在发布时撞上一个它没有预期过的状态；`DELETED`/`PURGED` 的版本已经
        不在可用集合里，归档它们只是把两个终态混在一起。

        归档**不删向量**：Milvus 的删除是一条 outbox 意图，由调用方登记。写在这里就等于
        让一次数据库写入偷偷依赖另一个存储可用。
        """
        ...

    def requeue_ingestion_job(
        self, job_id: str, *, now: datetime, expected_status: IngestionStatus
    ) -> IngestionJob:
        """把一个失败的任务重新放回队列开头（`requeue_ingestion` 的持久化）。

        `expected_status` 是调用方读到的那一个：期间任务被并发者推进过时，这次重排必须
        失败而不是覆盖掉别人的结果。
        """
        ...

    def save_version_metadata(
        self, version: ResearchDocumentVersion, *, expected_status: DocumentVersionStatus
    ) -> ResearchDocumentVersion:
        """写入解析与索引口径（解析器版本、切片口径、嵌入模型、generation、预期块数）。

        单独成一个方法，是因为这些字段在摄取过程中才会确定，而它们必须**先于**可见性写入：
        `activate_version` 只改状态，一个记不住自己是哪一批索引出来的版本，在重建或追责时
        无法回答任何问题。状态不在这个方法里——把两者合成一个写入，就等于让"记住口径"和
        "对外可见"之间没有中间态。
        """
        ...

    # --- 原件 ---

    def get_original_asset_key(self, document_version_id: str) -> str | None:
        """这一版原件的对象键，没有登记时返回 `None`。

        只返回键而不是资产描述：内容类型与散列由 `ResearchAssetStore.stat` 给出，那是唯一
        知道对象实际是什么的地方。权威库回答的是"原件存在哪里"。
        """
        ...

    # --- 资产 ---

    def register_asset(self, asset: ResearchDocumentAsset) -> ResearchDocumentAsset:
        """登记一份资产（原件、页面图、表格结构、图表裁剪）。

        键与散列由调用方给，但它们不是让这里照抄的：`object_key` 的唯一约束保证同一份资产
        不会被两条记录指向不同的内容，而"这份资产就是原件的证据"要用
        `ResearchAssetStore.stat` 的回答去核对（维护任务做这件事）。
        """
        ...

    def list_asset_keys(self, document_version_id: str) -> tuple[str, ...]:
        """这一版名下**尚未删除**的资产键，按登记顺序。

        清理流程先取这份清单再去删对象：它在删数据库行之前拿到键，因此一次中断留下的
        最多是"行还在、对象已删"，而反过来（行没了、对象还在）会让对象永远没人再提起。
        """
        ...

    # --- 切片 ---

    def append_chunks(self, chunks: Sequence[ResearchChunk]) -> None: ...

    def get_chunk(self, chunk_id: str) -> ResearchChunk | None: ...

    def load_chunks(self, chunk_ids: Sequence[str]) -> dict[str, ResearchChunk]:
        """按 ID 批量取切片，查不到的 ID 不出现在结果里。

        与 `load_version_statuses` 同一个理由：检索的每一步复核都要在一批候选上跑，
        逐条查询会把一次检索变成几百次往返。返回的是切片而不只是正文，因为检索需要的是
        切片保留的原文定位（页码、章节路径），那是索引里没有的东西。
        """
        ...

    def list_chunks(
        self, document_version_id: str, *, limit: int = 500
    ) -> tuple[ResearchChunk, ...]: ...

    def count_chunks(self, document_version_id: str) -> int: ...

    def mark_chunks_embedded(self, chunk_ids: Sequence[str]) -> None: ...

    # --- 摄取任务 ---

    def create_ingestion_job(self, job: IngestionJob) -> IngestionJob: ...

    def get_ingestion_job(self, job_id: str) -> IngestionJob | None: ...

    def acquire_ingestion_job(
        self, job_id: str, *, worker_id: str, now: datetime, lease_seconds: int
    ) -> IngestionJob: ...

    def save_ingestion_job(
        self, job: IngestionJob, *, expected_status: IngestionStatus, expected_attempt: int
    ) -> IngestionJob: ...

    def list_ingestion_jobs(
        self,
        *,
        document_id: str | None = None,
        document_version_id: str | None = None,
        limit: int = 100,
    ) -> tuple[IngestionJob, ...]:
        """按文档或版本取摄取任务，最新的在前。

        维护任务据它找"长期没落地的任务"（规格 16.4），文档详情据它并列出一版试过几次。
        """
        ...

    # --- 派生索引 outbox ---

    def enqueue_index_event(self, event: IndexOutboxEvent) -> IndexOutboxEvent:
        """登记一个索引变更意图；同一个 `event_id` 登记两次是同一件事，不是两次。

        幂等由 `event_id` 承担，因此调用方可以用一个由内容决定的名字（"这一代要发布"）来
        登记它：重放一次摄取、换一个 worker 重跑，写下的都还是同一个意图，Outbox 不会因为
        有人重试就变成一份重试次数记录。已存在的那一行原样返回，**不重置它的状态**——一个
        正在被认领或已经失败的事件不会因为有人又登记了一次而回到 PENDING。
        """
        ...

    def claim_outbox_events(
        self, *, worker_id: str, now: datetime, limit: int = 10
    ) -> tuple[IndexOutboxEvent, ...]: ...

    def finish_outbox_event(
        self, event_id: str, *, worker_id: str, now: datetime, error: str | None = None
    ) -> IndexOutboxEvent: ...

    # --- 检索审计 ---

    def record_retrieval_audit(self, audit: RetrievalAuditRecord) -> None: ...

    def get_retrieval_audit(self, retrieval_id: str) -> RetrievalAuditRecord | None: ...
