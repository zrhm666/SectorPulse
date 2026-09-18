"""资料库维护面：核对、重试、清理（规格 16.3、16.4、20.2）。

这一层要证明的是**判罚方向**：三个存储里只有 PostgreSQL 是事实来源，因此对不上的时候
永远是"派生物错了"，而报告要把这句话说清楚——缺什么、多什么、还有什么该被人看一眼。

维护面刻意不做三件事，测试各有一条守着它们：不自动补齐（补齐是一次有花费的重新嵌入）、
不把待兑现的删除意图报成不一致（那会让每次删除都在报告里留下一段注定消失的噪声）、
不允许一次没有署名的删除（`repair` 是唯一会动派生数据的开关）。

装配与 API 套件同一份（`backend/tests/research_library_stack.py`）：权威库、对象存储与向量
索引都是内存实现，真实的那部分语义（条件更新、并发认领）在真库套件里验。
"""

from __future__ import annotations

from datetime import timedelta
from io import BytesIO

import pytest
from sector_pulse.application.research_library.commands import (
    GovernanceRefused,
    UploadScanRejected,
    UploadTarget,
)
from sector_pulse.application.research_library.observability import MetricName
from sector_pulse.domain.research_library.audit import DocumentAuditAction
from sector_pulse.domain.research_library.models import (
    DocumentType,
    DocumentVersionStatus,
    ExtractionMethod,
    IngestionStatus,
)
from sector_pulse.infrastructure.research_library.assets.integrity import spool_to_disk
from sector_pulse.ports.research_assets import AssetError, AssetRef
from sector_pulse.ports.vector_index import ChunkType, VectorRecord

from backend.tests.research_library_stack import (
    BODY,
    EMBEDDING_DIMENSION,
    NOW,
    ResearchLibraryStack,
    build_research_library_stack,
)

ACTOR = "hanyu"
WORKER = "worker-maintenance"
RETENTION_DAYS = 30
MALWARE = b"@@MALWARE@@ not a report"


# --- 夹具 ---


def upload_document(
    stack: ResearchLibraryStack,
    *,
    body: bytes = BODY.encode("utf-8"),
    filename: str = "report.txt",
    title: str = "储能行业 2026 年中期策略",
):
    with spool_to_disk(BytesIO(body), max_bytes=stack.services.max_upload_bytes) as spooled:
        return stack.commands.upload(
            spooled=spooled,
            media_type="text/plain",
            filename=filename,
            target=UploadTarget.NEW_DOCUMENT,
            actor=ACTOR,
            title=title,
            document_type=DocumentType.REPORT,
        )


def publish(stack: ResearchLibraryStack, uploaded) -> str:
    """把一份上传推到底，返回版本 ID。"""
    job = stack.commands.run_ingestion(uploaded.job.job_id, worker_id=WORKER)
    assert job.status is IngestionStatus.PUBLISHED, job
    return uploaded.version.document_version_id


def a_published_document(stack: ResearchLibraryStack, **kwargs) -> tuple[str, str]:
    """一份已生效的文档：返回 (document_id, document_version_id)。"""
    uploaded = upload_document(stack, **kwargs)
    version_id = publish(stack, uploaded)
    return uploaded.document.document_id, version_id


def indexable_ids(stack: ResearchLibraryStack, version_id: str) -> list[str]:
    return [
        chunk.chunk_id
        for chunk in stack.repository.list_chunks(version_id)
        if chunk.parent_chunk_id
    ]


def orphan_record(stack: ResearchLibraryStack, version_id: str, *, chunk_id: str) -> VectorRecord:
    """一条**不该在这一代里**的记录。

    构造它的理由不是理论上的可能：换过切片口径之后，同一代里会留着上一批块留下的向量，
    而向量写入是 upsert、没有删除动作，所以它们会一直留着，直到有人显式清掉。
    """
    version = stack.repository.get_version(version_id)
    assert version is not None
    document = stack.repository.get_document(version.document_id)
    assert document is not None
    return VectorRecord(
        chunk_id=chunk_id,
        document_id=version.document_id,
        document_version_id=version_id,
        chunk_type=ChunkType.TEXT,
        document_type=document.document_type,
        institution=document.institution,
        content_origin=ExtractionMethod.NATIVE,
        content="上一套切片口径留下的正文。",
        dense_vector=(1.0,) * EMBEDDING_DIMENSION,
    )


# --- 干净的资料库 ---


def test_a_healthy_library_reconciles_clean():
    """一份好的报告是空的：没有缺的、没有多的、没有该被看一眼的。"""
    stack = build_research_library_stack()
    document_id, version_id = a_published_document(stack)

    report = stack.maintenance.reconcile(now=stack.clock())

    assert report.consistent
    assert report.index_gaps == ()
    assert report.asset_discrepancies == ()
    assert report.incomplete_versions == ()
    assert report.unreadable_versions == ()
    assert report.failed_jobs == ()
    assert report.purgeable == ()
    assert report.checked_documents == 1
    assert report.checked_versions == 1
    assert report.corpus_generation
    assert report.repaired is False
    assert report.orphans_removed == 0


def test_the_report_says_how_much_it_looked_at():
    """上限写在报告里：一份不全的报告必须是可读的，而不是看起来像全部。"""
    stack = build_research_library_stack()
    a_published_document(stack)

    report = stack.maintenance.reconcile(now=stack.clock(), document_limit=1)

    assert report.document_limit == 1


# --- 索引对不上 ---


def test_reconcile_reports_the_vectors_the_index_is_missing():
    """索引里少了向量：报出来，而且**不**替用户补——补齐是一次有花费的重新嵌入。"""
    stack = build_research_library_stack()
    _, version_id = a_published_document(stack)
    chunk_ids = indexable_ids(stack, version_id)
    assert len(chunk_ids) >= 2, "夹具正文必须切得出多个子块"
    version = stack.repository.get_version(version_id)
    assert version is not None and version.index_generation is not None
    stack.vector_index.delete_records(generation=version.index_generation, chunk_ids=chunk_ids[:1])

    report = stack.maintenance.reconcile(now=stack.clock())

    assert not report.consistent
    assert len(report.index_gaps) == 1
    gap = report.index_gaps[0]
    assert gap.document_version_id == version_id
    assert gap.index_generation == version.index_generation
    assert gap.missing_ids == (chunk_ids[0],)
    assert gap.unexpected_ids == ()
    assert gap.present_count == gap.expected_count - 1

    repaired = stack.maintenance.reconcile(now=stack.clock(), repair=True, actor=ACTOR)

    assert repaired.orphans_removed == 0
    assert [gap.missing_ids for gap in repaired.index_gaps] == [(chunk_ids[0],)]


def test_reconcile_reports_vectors_that_do_not_belong_to_the_version():
    """索引里多了向量：同样只报出来。多出来的那些重写补不上，只能删。"""
    stack = build_research_library_stack()
    _, version_id = a_published_document(stack)
    version = stack.repository.get_version(version_id)
    assert version is not None and version.index_generation is not None
    stack.vector_index.stage(
        generation=version.index_generation,
        records=(orphan_record(stack, version_id, chunk_id="chunk_from_another_policy"),),
    )

    report = stack.maintenance.reconcile(now=stack.clock())

    assert not report.consistent
    assert [gap.unexpected_ids for gap in report.index_gaps] == [("chunk_from_another_policy",)]
    assert report.orphans_removed == 0
    # 没有 repair 就一个字节都不动：删掉的是派生数据，但"谁删的"重建不回来。
    assert stack.vector_index.verify(
        generation=version.index_generation,
        expected_ids=frozenset(indexable_ids(stack, version_id)),
    ).unexpected_ids == ("chunk_from_another_policy",)


def test_repairing_removes_the_orphans_and_leaves_a_signed_audit_row():
    stack = build_research_library_stack()
    document_id, version_id = a_published_document(stack)
    version = stack.repository.get_version(version_id)
    assert version is not None and version.index_generation is not None
    stack.vector_index.stage(
        generation=version.index_generation,
        records=(orphan_record(stack, version_id, chunk_id="chunk_orphan_1"),),
    )
    stack.clock.advance(seconds=600)

    report = stack.maintenance.reconcile(
        now=stack.clock(), repair=True, actor=ACTOR, document_limit=10
    )

    assert report.repaired is True
    assert report.orphans_removed == 1
    assert report.index_gaps == ()
    assert report.consistent
    assert (
        stack.vector_index.verify(
            generation=version.index_generation,
            expected_ids=frozenset(indexable_ids(stack, version_id)),
        ).unexpected_ids
        == ()
    )
    entry = stack.repository.list_document_audit(document_id)[-1]
    assert entry.action is DocumentAuditAction.REBUILD_INDEX
    assert entry.actor == ACTOR
    assert entry.created_at == NOW + timedelta(seconds=600)
    assert entry.document_version_id == version_id
    assert "1" in entry.detail


def test_repairing_without_an_actor_is_refused():
    """删除是一次有署名的动作。校验在服务里，不只在请求模型上。"""
    stack = build_research_library_stack()
    a_published_document(stack)

    # 抛的是 `GovernanceRefused`，不是裸 `ValueError`。这条拒绝和 `commands._require_actor`
    # 管的是同一条规则，从前它两边各是各的类型，于是"你没给名字"在 `purge` 上以一个可重试的
    # 500 回答——一个重试多少次都不会成功的请求，却被告知可以重试。现在两边同型，路由把它
    # 翻成 409 `GOVERNANCE_REFUSED`（端到端那一半在 test_research_library_api.py）。
    with pytest.raises(GovernanceRefused, match="actor"):
        stack.maintenance.reconcile(now=stack.clock(), repair=True)
    with pytest.raises(GovernanceRefused, match="actor"):
        stack.maintenance.reconcile(now=stack.clock(), repair=True, actor="   ")


def test_a_clean_repair_writes_no_audit_row():
    """没删掉任何东西就不留痕：一条什么都没改变的审计行会把真正的那几行埋掉。"""
    stack = build_research_library_stack()
    document_id, _ = a_published_document(stack)
    before = len(stack.repository.list_document_audit(document_id))

    report = stack.maintenance.reconcile(now=stack.clock(), repair=True, actor=ACTOR)

    assert report.orphans_removed == 0
    assert len(stack.repository.list_document_audit(document_id)) == before


def test_reconcile_reports_a_version_the_authority_store_cannot_read_back():
    """权威库自己读不顺：这一版既不能核对也不能重建，是最需要被看见的一类。"""
    stack = build_research_library_stack()
    document_id, version_id = a_published_document(stack)
    original = stack.repository.count_chunks

    def lying(document_version_id: str) -> int:
        return original(document_version_id) + 1

    stack.repository.count_chunks = lying  # type: ignore[method-assign]

    report = stack.maintenance.reconcile(now=stack.clock())

    assert not report.consistent
    assert [item.document_version_id for item in report.unreadable_versions] == [version_id]
    assert report.unreadable_versions[0].document_id == document_id
    assert report.unreadable_versions[0].detail


def test_reconcile_counts_the_drift_as_a_storage_inconsistency():
    """规格 20.2 的信号按"处"记，而不是逐条记：它回答的是"有没有在漂移"。"""
    stack = build_research_library_stack()
    _, version_id = a_published_document(stack)
    version = stack.repository.get_version(version_id)
    assert version is not None and version.index_generation is not None
    stack.vector_index.delete_records(
        generation=version.index_generation, chunk_ids=indexable_ids(stack, version_id)[:1]
    )

    stack.maintenance.reconcile(now=stack.clock())

    assert (
        stack.metrics.total(
            MetricName.STORAGE_INCONSISTENCIES, store="milvus", table="research_chunks"
        )
        == 1
    )
    assert (
        stack.metrics.total(
            MetricName.STORAGE_INCONSISTENCIES, store="minio", table="research_document_assets"
        )
        == 0
    )


# --- 原件对不上 ---


def test_reconcile_reports_an_original_that_is_gone():
    stack = build_research_library_stack()
    document_id, version_id = a_published_document(stack)
    key = stack.repository.get_original_asset_key(version_id)
    assert key is not None
    stack.assets.delete(key)

    report = stack.maintenance.reconcile(now=stack.clock())

    assert not report.consistent
    assert len(report.asset_discrepancies) == 1
    discrepancy = report.asset_discrepancies[0]
    assert discrepancy.document_id == document_id
    assert discrepancy.document_version_id == version_id
    assert discrepancy.kind.value == "MISSING"
    assert discrepancy.object_key == key
    assert discrepancy.expected_sha256.startswith("sha256:")


def test_reconcile_reports_an_original_that_is_no_longer_the_same_object(monkeypatch):
    """同一个键底下换了另一份字节：核对的是"还是不是当初那一份"，不只是"在不在"。"""
    stack = build_research_library_stack()
    _, version_id = a_published_document(stack)
    original = stack.assets.stat

    def drifted(key: str) -> AssetRef:
        return original(key).model_copy(update={"sha256": "0" * 64})

    monkeypatch.setattr(stack.assets, "stat", drifted)

    report = stack.maintenance.reconcile(now=stack.clock())

    assert len(report.asset_discrepancies) == 1
    discrepancy = report.asset_discrepancies[0]
    assert discrepancy.document_version_id == version_id
    assert discrepancy.kind.value == "HASH_MISMATCH"
    assert discrepancy.actual_sha256 == "0" * 64
    assert discrepancy.expected_sha256 != discrepancy.actual_sha256


def test_an_archived_version_is_not_reported_as_a_storage_problem():
    """归档会登记删掉那一代向量的意图；意图还没兑现不是存储错了。"""
    stack = build_research_library_stack()
    document_id, version_id = a_published_document(stack)
    stack.commands.archive_version(document_id, version_id, actor=ACTOR, now=stack.clock())

    report = stack.maintenance.reconcile(now=stack.clock())

    assert report.asset_discrepancies == ()
    assert report.index_gaps == ()
    assert report.checked_versions == 0


# --- 半路的版本与失败的任务 ---


def test_a_refused_upload_is_reported_as_a_version_without_a_job():
    """被扫描器拒掉的上传：版本行在、原件在（隔离证据）、**没有**摄取任务。它该被看见。"""
    stack = build_research_library_stack()
    with pytest.raises(UploadScanRejected):
        upload_document(stack, body=MALWARE, filename="payload.txt")

    report = stack.maintenance.reconcile(now=stack.clock())

    assert not report.consistent
    assert len(report.incomplete_versions) == 1
    assert report.incomplete_versions[0].reason == (
        "no ingestion job: a refused upload, or an upload interrupted before the job was created"
    )
    assert report.incomplete_versions[0].status is DocumentVersionStatus.PROCESSING
    assert report.asset_discrepancies == ()
    assert report.index_gaps == ()


def test_a_version_whose_original_never_arrived_is_reported_as_incomplete(monkeypatch):
    """对象存储写失败时版本行已经在了：那一版没有原件、没有任务，停在半路，该被看见。"""
    stack = build_research_library_stack()

    def unreachable(**_kwargs):
        raise AssetError("the object store is unreachable")

    monkeypatch.setattr(stack.assets, "put", unreachable)
    with pytest.raises(AssetError):
        upload_document(stack)

    report = stack.maintenance.reconcile(now=stack.clock())

    assert not report.consistent
    assert [item.reason for item in report.incomplete_versions] == ["no registered original asset"]
    assert report.incomplete_versions[0].status is DocumentVersionStatus.PROCESSING
    assert report.asset_discrepancies == ()


def test_a_failed_job_is_reported_even_though_it_is_not_a_storage_problem():
    """失败任务出现在报告里不是因为存储错了，而是因为"有人该看一眼"。"""
    stack = build_research_library_stack()
    uploaded = upload_document(stack)
    job = stack.repository.get_ingestion_job(uploaded.job.job_id)
    assert job is not None
    stack.repository.save_ingestion_job(
        job.model_copy(
            update={
                "status": IngestionStatus.PERMANENT_FAILED,
                "failure_reason": "the embedding provider refused every request",
            }
        ),
        expected_status=job.status,
        expected_attempt=job.attempt_id,
    )

    report = stack.maintenance.reconcile(now=stack.clock())

    assert [item.job_id for item in report.failed_jobs] == [uploaded.job.job_id]
    assert report.failed_jobs[0].status is IngestionStatus.PERMANENT_FAILED
    assert report.failed_jobs[0].failure_reason
    assert report.index_gaps == ()


# --- 清理 ---


def test_a_soft_deleted_document_becomes_purgeable_after_its_retention_window():
    stack = build_research_library_stack()
    document_id, _ = a_published_document(stack)
    stack.commands.soft_delete(document_id, actor=ACTOR, now=stack.clock())

    fresh = stack.maintenance.reconcile(now=stack.clock())

    assert fresh.purgeable == ()

    stack.clock.advance(days=RETENTION_DAYS + 1)
    expired = stack.maintenance.reconcile(now=stack.clock())

    assert [item.document_id for item in expired.purgeable] == [document_id]
    assert expired.purgeable[0].purge_after == NOW + timedelta(days=RETENTION_DAYS)


def test_a_pending_delete_intent_is_not_reported_as_index_drift():
    """删除意图还没兑现时索引里当然还留着记录。把它报成不一致，报告就开始说谎。"""
    stack = build_research_library_stack()
    document_id, _ = a_published_document(stack)
    stack.commands.soft_delete(document_id, actor=ACTOR, now=stack.clock())

    report = stack.maintenance.reconcile(now=stack.clock())

    assert report.index_gaps == ()
    assert report.asset_discrepancies == ()
    assert report.purgeable == ()


def test_purging_removes_only_the_documents_past_their_retention_window():
    stack = build_research_library_stack()
    expired_id, expired_version = a_published_document(stack, title="已经过期的报告")
    fresh_id, fresh_version = a_published_document(stack, title="还在保留期里的报告")
    stack.commands.soft_delete(expired_id, actor=ACTOR, now=stack.clock())
    stack.clock.advance(days=RETENTION_DAYS + 1)
    stack.commands.soft_delete(fresh_id, actor=ACTOR, now=stack.clock())

    purged = stack.maintenance.purge_expired(actor=ACTOR, now=stack.clock())

    assert purged == (expired_id,)
    expired = stack.repository.get_version(expired_version)
    assert expired is not None and expired.status is DocumentVersionStatus.PURGED
    assert stack.repository.count_chunks(expired_version) == 0
    assert stack.repository.list_chunks(expired_version) == ()
    fresh = stack.repository.get_version(fresh_version)
    assert fresh is not None and fresh.status is DocumentVersionStatus.ACTIVE
    assert stack.repository.count_chunks(fresh_version) > 0


def test_a_purge_leaves_a_signed_audit_row_and_no_chunks():
    stack = build_research_library_stack()
    document_id, version_id = a_published_document(stack)
    stack.commands.soft_delete(document_id, actor=ACTOR, now=stack.clock())
    stack.clock.advance(days=RETENTION_DAYS + 1)

    assert stack.maintenance.purge_expired(actor=ACTOR, now=stack.clock()) == (document_id,)

    audit = stack.repository.list_document_audit(document_id)
    purge = [entry for entry in audit if entry.action is DocumentAuditAction.PURGE]
    assert len(purge) == 1
    assert purge[0].actor == ACTOR
    assert "retention" in purge[0].detail
    assert stack.repository.count_chunks(version_id) == 0
    # 文档行留着（不含正文的审计记录仍然可读），但它不再指向任何一版。
    purged = stack.repository.get_document(document_id)
    assert purged is not None
    assert purged.current_version_id is None


def test_a_purge_must_name_its_actor():
    stack = build_research_library_stack()
    with pytest.raises(GovernanceRefused, match="actor"):
        stack.maintenance.purge_expired(actor="  ", now=stack.clock())


# --- 重试 Outbox ---


def test_retrying_the_outbox_settles_the_delete_intent_of_a_soft_deleted_document():
    stack = build_research_library_stack()
    document_id, version_id = a_published_document(stack)
    version = stack.repository.get_version(version_id)
    assert version is not None and version.index_generation is not None
    stack.commands.soft_delete(document_id, actor=ACTOR, now=stack.clock())

    settled = stack.maintenance.retry_outbox(worker_id=WORKER, now=stack.clock())

    assert [event.document_version_id for event in settled] == [version_id]
    assert (
        stack.vector_index.verify(
            generation=version.index_generation, expected_ids=frozenset()
        ).present_count
        == 0
    )


def test_retrying_the_outbox_is_idempotent():
    """没有待办时的一次重试是空操作，不是错误——运维会定时敲它。"""
    stack = build_research_library_stack()
    a_published_document(stack)

    assert stack.maintenance.retry_outbox(worker_id=WORKER, now=stack.clock()) == ()
    assert stack.maintenance.retry_outbox(worker_id=WORKER, now=stack.clock()) == ()


def test_an_oldest_first_scan_stays_bounded():
    """核对是运维动作，不是在线路径：它必须能在资料库变大之后仍然跑得完。"""
    stack = build_research_library_stack()
    for index in range(3):
        a_published_document(stack, title=f"第 {index} 份报告")

    report = stack.maintenance.reconcile(now=stack.clock(), document_limit=2)

    assert report.checked_documents == 2
    assert report.document_limit == 2


def test_the_scan_reports_a_version_whose_index_generation_is_not_the_stored_one():
    """版本指向的这一代就是核对的那一代：核对不接受"另一代里是齐的"。"""
    stack = build_research_library_stack()
    _, version_id = a_published_document(stack)
    version = stack.repository.get_version(version_id)
    assert version is not None and version.index_generation is not None
    stack.vector_index.stage(
        generation="gen_not_the_one_this_version_points_at",
        records=(orphan_record(stack, version_id, chunk_id="chunk_elsewhere"),),
    )

    report = stack.maintenance.reconcile(now=stack.clock())

    assert report.index_gaps == ()
    assert report.checked_versions == 1


def test_the_scan_reports_a_version_that_has_no_index_generation():
    """没发布过的版本没有 generation，因此它不在核对面里（它由 failed_jobs 那条线负责）。"""
    stack = build_research_library_stack()
    upload_document(stack)

    report = stack.maintenance.reconcile(now=stack.clock())

    assert report.checked_versions == 0
    assert report.index_gaps == ()
    assert report.failed_jobs == ()
