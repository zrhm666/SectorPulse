"""资料库的维护视图：把"三个存储之间对不上"变成一份可读的报告（规格 16.3、16.4、20.2）。

只有权威库（PostgreSQL）是事实来源，另外两个都是可重建的派生物。这意味着对不上的时候
判罚方向是确定的：Milvus 里多了或少了什么、MinIO 里少了或变了什么，都以权威库为准。
报告因此从权威库出发逐版本核对，而不是反过来。

三件刻意不做的事：

- **不自动补齐**。报告里"缺了多少向量"是一个事实，补它的动作是重新嵌入（有真实花费），
  因此 `repair=True` 只做删除类修复（多出来的那些）；补齐要用户显式重建（规格 16.3 把
  重建列为维护动作）。
- **不把清理混进核对**。物理清理有保留期与条件更新两道闸门，它是 `purge_expired` 的事；
  核对只回答"哪些已经可以清理了"。
- **不把待兑现的删除意图报成不一致**。归档与软删除都会写一条删除 generation 的意图，
  在它被兑现之前索引里当然还留着记录；把它报出来，等于每次删除都在报告里留下一段注定
  消失的噪声，而报告一旦开始说谎就不会再被读。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sector_pulse.application.research_library.commands import GovernanceRefused
from sector_pulse.domain.research_library.audit import (
    DocumentAuditAction,
    document_audit_entry,
)
from sector_pulse.domain.research_library.models import (
    DocumentVersionStatus,
    IndexOutboxEvent,
    IngestionStatus,
    Record,
    ResearchDocument,
    ResearchDocumentVersion,
)
from sector_pulse.ports.research_assets import AssetNotFound
from sector_pulse.storage.ports.research_library import ResearchLibraryConflict

if TYPE_CHECKING:  # pragma: no cover - 只为类型
    from sector_pulse.application.research_library.services import ResearchLibraryServices

#: 一次核对扫描多少份文档。核对是运维动作，不是在线路径；有上限是为了让它在资料库变大
#: 之后仍然跑得完，而上限本身写在报告里——"这份报告不全"因此是可读的。
DEFAULT_DOCUMENT_LIMIT = 500

#: 应该在派生索引里被服务到的版本状态。其余状态要么还没发布（PROCESSING 没有 generation，
#: FAILED 没通过复核），要么已经在删除队列上（ARCHIVED/DELETED/PURGED）。
SERVING_VERSION_STATUSES = frozenset(
    {DocumentVersionStatus.ACTIVE, DocumentVersionStatus.SUPERSEDED}
)

#: 还在等原件的版本状态。`ARCHIVED`/`DELETED`/`PURGED` 缺原件不是问题，是结果。
INCOMPLETE_VERSION_STATUSES = frozenset({DocumentVersionStatus.PROCESSING})

#: 失败的任务状态。它们出现在报告里不是因为它们错了，而是因为"有人该看一眼"。
FAILED_JOB_STATUSES = frozenset(
    {
        IngestionStatus.PERMANENT_FAILED,
        IngestionStatus.RETRYABLE_FAILED,
        IngestionStatus.CANCELLED,
    }
)


class AssetDiscrepancyKind(StrEnum):
    """原件与权威库对不上的两种方式。"""

    MISSING = "MISSING"
    HASH_MISMATCH = "HASH_MISMATCH"


class IndexGap(Record):
    """一个索引代里缺的、或多出来的向量。"""

    document_version_id: str
    index_generation: str
    expected_count: int
    present_count: int
    missing_ids: tuple[str, ...] = ()
    unexpected_ids: tuple[str, ...] = ()


class AssetDiscrepancy(Record):
    """一份原件与它登记的样子不一致。"""

    document_id: str
    document_version_id: str
    object_key: str
    kind: AssetDiscrepancyKind
    expected_sha256: str
    actual_sha256: str | None = None
    detail: str | None = None


class IncompleteVersion(Record):
    """版本缺了让它能被处理的那件东西（原件，或摄取任务）。"""

    document_id: str
    document_version_id: str
    status: DocumentVersionStatus
    reason: str


class FailedJob(Record):
    job_id: str
    document_id: str
    document_version_id: str
    status: IngestionStatus
    attempt_id: int
    failure_reason: str | None = None


class UnreadableVersion(Record):
    """权威库自己读不顺的版本（块数对不上、读不回来）。这是最严重的一类。"""

    document_id: str
    document_version_id: str
    detail: str


class PurgeCandidate(Record):
    """保留期已过的软删除文档：可以物理清理了。"""

    document_id: str
    purge_after: datetime


class ReconciliationReport(Record):
    """一次核对的结果。空报告是一份好的报告。"""

    corpus_generation: str
    document_limit: int
    checked_documents: int
    checked_versions: int
    repaired: bool = False
    orphans_removed: int = 0
    index_gaps: tuple[IndexGap, ...] = ()
    asset_discrepancies: tuple[AssetDiscrepancy, ...] = ()
    incomplete_versions: tuple[IncompleteVersion, ...] = ()
    failed_jobs: tuple[FailedJob, ...] = ()
    unreadable_versions: tuple[UnreadableVersion, ...] = ()
    purgeable: tuple[PurgeCandidate, ...] = ()

    @property
    def consistent(self) -> bool:
        """权威库与派生物之间没有对不上的地方。

        "缺原件/缺任务"算不一致：它们描述的是本该在处理的版本停在了半路。
        """
        return not (
            self.index_gaps
            or self.asset_discrepancies
            or self.incomplete_versions
            or self.unreadable_versions
        )


def _hash_matches(expected: str, actual: str) -> bool:
    """`original_file_hash` 带 `sha256:` 前缀，对象存储返回的是裸十六进制。

    只剥前缀：把"前缀不是算法名"当成"散列一样"，会让一份用别的算法算出来的散列假装通过
    核对，而两份不同算法的摘要出现在同一列里时，它们本来就不可比。
    """
    algorithm, separator, digest = expected.partition(":")
    if not separator:
        return expected == actual
    return algorithm == "sha256" and digest == actual


class ResearchLibraryMaintenance:
    """核对、重试与清理。"""

    def __init__(self, services: ResearchLibraryServices) -> None:
        self._services = services

    def _now(self, now: datetime | None) -> datetime:
        return self._services.clock() if now is None else now

    # --- 核对 ---

    def reconcile(
        self,
        *,
        now: datetime | None = None,
        repair: bool = False,
        document_limit: int = DEFAULT_DOCUMENT_LIMIT,
        actor: str | None = None,
    ) -> ReconciliationReport:
        """逐版本核对权威库与派生物（规格 16.3）。

        `repair=True` 时删掉多出来的向量（换过切片口径之后留在同一代里的那些），其余不动：
        补齐要向用户要一次重建，清理要向保留期要时间，两者都不该被一次"顺便核对"带走。

        删除是一次**有署名**的动作。校验放在这里而不只放在请求模型上：`repair` 这个开关
        将来也可能从命令行或计划任务上被拨动，而"谁删的"不能只在其中一条路径上有答案。
        """
        if repair and not (actor or "").strip():
            raise GovernanceRefused("repairing the derived index requires an actor")
        stamp = self._now(now)
        repository = self._services.repository
        documents = repository.list_documents(include_deleted=True, limit=document_limit)

        index_gaps: list[IndexGap] = []
        asset_discrepancies: list[AssetDiscrepancy] = []
        incomplete: list[IncompleteVersion] = []
        failed_jobs: list[FailedJob] = []
        unreadable: list[UnreadableVersion] = []
        purgeable: list[PurgeCandidate] = []
        orphans_removed = 0
        checked_versions = 0

        for document in documents:
            if document.purge_after is not None and document.purge_after <= stamp:
                purgeable.append(
                    PurgeCandidate(
                        document_id=document.document_id, purge_after=document.purge_after
                    )
                )
            versions = repository.list_versions(document.document_id)
            for version in versions:
                key = repository.get_original_asset_key(version.document_version_id)
                if key is None:
                    if version.status in INCOMPLETE_VERSION_STATUSES:
                        incomplete.append(
                            IncompleteVersion(
                                document_id=document.document_id,
                                document_version_id=version.document_version_id,
                                status=version.status,
                                reason="no registered original asset",
                            )
                        )
                else:
                    discrepancy = self._check_asset(document, version, key=key)
                    if discrepancy is not None:
                        asset_discrepancies.append(discrepancy)

                if (
                    version.status not in SERVING_VERSION_STATUSES
                    or version.index_generation is None
                ):
                    continue
                checked_versions += 1
                try:
                    expected = self._services.ingestion.indexable_chunk_ids(
                        version.document_version_id
                    )
                except Exception as error:
                    # 权威库自己读不顺：这一版既不能核对也不能重建，是最需要被看见的一类。
                    unreadable.append(
                        UnreadableVersion(
                            document_id=document.document_id,
                            document_version_id=version.document_version_id,
                            detail=str(error),
                        )
                    )
                    continue
                gap, removed = self._check_index(
                    version,
                    document_id=document.document_id,
                    expected=expected,
                    repair=repair,
                    actor=(actor or "").strip(),
                    now=stamp,
                )
                orphans_removed += removed
                if gap is not None:
                    index_gaps.append(gap)

            jobs = repository.list_ingestion_jobs(document_id=document.document_id, limit=100)
            for job in jobs:
                if job.status in FAILED_JOB_STATUSES:
                    failed_jobs.append(
                        FailedJob(
                            job_id=job.job_id,
                            document_id=job.document_id,
                            document_version_id=job.document_version_id,
                            status=job.status,
                            attempt_id=job.attempt_id,
                            failure_reason=job.failure_reason,
                        )
                    )
            with_jobs = {job.document_version_id for job in jobs}
            for version in versions:
                if (
                    version.status in INCOMPLETE_VERSION_STATUSES
                    and version.document_version_id not in with_jobs
                    and repository.get_original_asset_key(version.document_version_id) is not None
                ):
                    incomplete.append(
                        IncompleteVersion(
                            document_id=document.document_id,
                            document_version_id=version.document_version_id,
                            status=version.status,
                            reason=(
                                "no ingestion job: a refused upload, or an upload interrupted "
                                "before the job was created"
                            ),
                        )
                    )

        self._record_metrics(
            index_gaps=index_gaps, asset_discrepancies=asset_discrepancies, unreadable=unreadable
        )
        return ReconciliationReport(
            corpus_generation=self._services.corpus_generation(),
            document_limit=document_limit,
            checked_documents=len(documents),
            checked_versions=checked_versions,
            repaired=repair,
            orphans_removed=orphans_removed,
            index_gaps=tuple(index_gaps),
            asset_discrepancies=tuple(asset_discrepancies),
            incomplete_versions=tuple(incomplete),
            failed_jobs=tuple(failed_jobs),
            unreadable_versions=tuple(unreadable),
            purgeable=tuple(purgeable),
        )

    def _check_index(
        self,
        version: ResearchDocumentVersion,
        *,
        document_id: str,
        expected: Iterable[str],
        repair: bool,
        actor: str,
        now: datetime,
    ) -> tuple[IndexGap | None, int]:
        """核对一个 generation；`repair=True` 时删掉多出来的那些。

        只删"多出来的"：少的那些要靠重新嵌入补，而重新嵌入是一次有花费的动作。
        `unexpected_ids` 不是理论上的可能——换过切片口径之后，同一代里会留着上一批的块。

        删除写完立刻留一行审计。删掉的是派生数据（重建得回来），但"是谁在什么时候把手伸进
        索引里"这件事重建不回来；等到下次有人问起，那条向量已经不在了。

        修复之后**重新核对一次**，报告说的是这一趟结束时索引的样子。删完还报着"多出来
        一条"，会让一份修好的资料库读起来仍然是不一致的（`consistent` 为假），而"删了几条"
        已经由 `orphans_removed` 说了；重新核对还能如实说出没删掉的那些——删除是分批的，
        少删了却报成功，才是真正会让人误判的那种报告。
        """
        generation = version.index_generation or ""
        report = self._services.vector_index.verify(
            generation=generation, expected_ids=frozenset(expected)
        )
        removed = 0
        if repair and report.unexpected_ids:
            removed = self._services.vector_index.delete_records(
                generation=generation, chunk_ids=report.unexpected_ids
            )
            report = self._services.vector_index.verify(
                generation=generation, expected_ids=frozenset(expected)
            )
            if removed:
                self._services.repository.append_document_audit(
                    document_audit_entry(
                        document_id=document_id,
                        document_version_id=version.document_version_id,
                        action=DocumentAuditAction.REBUILD_INDEX,
                        actor=actor,
                        detail=(
                            f"reconcile removed {removed} unexpected vectors from generation "
                            f"{generation}"
                        ),
                        created_at=now,
                    )
                )
        if not report.missing_ids and not report.unexpected_ids:
            return None, removed
        return (
            IndexGap(
                document_version_id=version.document_version_id,
                index_generation=generation,
                expected_count=report.expected_count,
                present_count=report.present_count,
                missing_ids=report.missing_ids,
                unexpected_ids=report.unexpected_ids,
            ),
            removed,
        )

    def _check_asset(
        self, document: ResearchDocument, version: ResearchDocumentVersion, *, key: str
    ) -> AssetDiscrepancy | None:
        """核对原件：还在不在、还是不是当初那一份。"""
        try:
            reference = self._services.assets.stat(key)
        except AssetNotFound as error:
            return AssetDiscrepancy(
                document_id=document.document_id,
                document_version_id=version.document_version_id,
                object_key=key,
                kind=AssetDiscrepancyKind.MISSING,
                expected_sha256=version.original_file_hash,
                detail=str(error),
            )
        if _hash_matches(version.original_file_hash, reference.sha256):
            return None
        return AssetDiscrepancy(
            document_id=document.document_id,
            document_version_id=version.document_version_id,
            object_key=key,
            kind=AssetDiscrepancyKind.HASH_MISMATCH,
            expected_sha256=version.original_file_hash,
            actual_sha256=reference.sha256,
        )

    def _record_metrics(
        self,
        *,
        index_gaps: Sequence[IndexGap],
        asset_discrepancies: Sequence[AssetDiscrepancy],
        unreadable: Sequence[UnreadableVersion],
    ) -> None:
        """规格 20.2 的存储不一致信号。

        一个不一致是一**处**，因此这里把每一类各自的总数记成一个观测，而不是逐条记：
        逐条记会让这条时间序列的值取决于一次扫描里恰好有多少条记录，而它要回答的是
        "存储之间有没有在漂移"。
        """
        metrics = self._services.metrics
        drift = sum(len(gap.missing_ids) + len(gap.unexpected_ids) for gap in index_gaps)
        metrics.record_storage_inconsistency(store="milvus", table="research_chunks", count=drift)
        metrics.record_storage_inconsistency(
            store="minio", table="research_document_assets", count=len(asset_discrepancies)
        )
        metrics.record_storage_inconsistency(
            store="postgres", table="research_chunks", count=len(unreadable)
        )

    # --- 重试 ---

    def retry_outbox(
        self, *, worker_id: str, now: datetime | None = None, limit: int = 10
    ) -> tuple[IndexOutboxEvent, ...]:
        """兑现一批待办的派生索引意图。

        与 `run_ingestion` 同理，这是 worker 的动作，不记治理审计。它在这里的原因只有一个：
        运维要能在不重启服务的前提下把"该删的还没删"推完。
        """
        return self._services.outbox.run_once(worker_id=worker_id, now=self._now(now), limit=limit)

    # --- 清理 ---

    def purge_expired(
        self, *, actor: str, now: datetime | None = None, limit: int = 100
    ) -> tuple[str, ...]:
        """物理清理保留期已过的软删除文档（规格 16.3 第 5、6 步）。

        条件更新在仓库层：算好的"可以清理了"是待核对的声明，不是待执行的结论。两个进程
        同时拿着同一份过期快照清理时，第二个会撞上冲突——那被记成"没什么可做的"，因为
        它想要的结果已经发生了。
        """
        if not actor.strip():
            raise GovernanceRefused("a purge must name the actor who performed it")
        stamp = self._now(now)
        purged: list[str] = []
        for candidate in self.reconcile(now=stamp, document_limit=limit).purgeable:
            audit = document_audit_entry(
                document_id=candidate.document_id,
                action=DocumentAuditAction.PURGE,
                actor=actor.strip(),
                detail=f"purged after the retention window ended at {candidate.purge_after}",
                created_at=stamp,
            )
            try:
                self._services.repository.purge_document(
                    candidate.document_id, now=stamp, audit=audit
                )
            except ResearchLibraryConflict:
                continue
            purged.append(candidate.document_id)
        return tuple(purged)


__all__ = [
    "AssetDiscrepancy",
    "AssetDiscrepancyKind",
    "FailedJob",
    "IncompleteVersion",
    "IndexGap",
    "PurgeCandidate",
    "ReconciliationReport",
    "ResearchLibraryMaintenance",
    "UnreadableVersion",
]
