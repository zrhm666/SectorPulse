"""摄取流水线的端到端性质，全部离线运行。

这里要证明的不是"某一步调用了某个方法"，而是只有整条链路跑起来才能观察到的性质：半途
写坏的索引不可见、崩溃后靠落库的意图恢复、迟到的 attempt 写不进任何东西、重放不产生
第二份结果、新版本构建期间旧版本照常服务。

假实现是有意选择的：内存权威库 + 内存资产库 + 内存向量索引 + Fixture Provider。同一批
性质在真实 PostgreSQL / Milvus 上还要再跑一遍，见
`test_research_index_publication.py`——那里覆盖的是内存实现覆盖不了的并发语义。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest
from sector_pulse.application.research_library.chunking import (
    ChunkingPolicy,
    StructuralChunker,
)
from sector_pulse.application.research_library.indexing import (
    IndexOutboxWorker,
    filter_active_hits,
)
from sector_pulse.application.research_library.ingestion import ResearchIngestionCoordinator
from sector_pulse.application.research_library.parsing import ResearchParsePipeline
from sector_pulse.domain.research_library.models import (
    ChunkType,
    DocumentType,
    DocumentVersionStatus,
    ExtractionMethod,
    IndexOutboxEvent,
    IngestionJob,
    IngestionStatus,
    OutboxOperation,
    OutboxStatus,
    ResearchDocument,
    ResearchDocumentVersion,
)
from sector_pulse.infrastructure.research_library.assets.memory import (
    InMemoryResearchAssetStore,
)
from sector_pulse.infrastructure.research_library.parsing.text import TextDocumentParser
from sector_pulse.infrastructure.research_library.providers.fixture import (
    FixtureEmbeddingProvider,
)
from sector_pulse.infrastructure.research_library.vector.memory import InMemoryVectorIndex
from sector_pulse.ports.research_assets import AssetMetadata, AssetRole
from sector_pulse.ports.research_models import (
    DocumentParser,
    EmbeddingBatch,
    EmbeddingProvider,
    ParsedDocument,
    ParseSource,
    ProviderError,
    ProviderRejected,
    ProviderUnavailable,
    UnsupportedMediaType,
)
from sector_pulse.ports.vector_index import (
    HybridQuery,
    IndexRecordConflict,
    IndexVerification,
    VectorHit,
    VectorIndex,
    VectorIndexError,
    VectorRecord,
)
from sector_pulse.storage.ports.research_library import ResearchLibraryConflict

from backend.tests.research_library_fakes import (
    InMemoryResearchLibraryRepository,
    new_ingestion_job,
)

NOW = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
PUBLISHED_AT = datetime(2026, 2, 20, tzinfo=UTC)
LEASE_SECONDS = 300

#: 刻意调小的切片预算。规格 8 的默认值（子块 300–500 token）会把下面这份测试正文整篇装进
#: 一个子块，于是"写了一半"、"少一条"、"多一条"这些情形根本没有发生的余地——测试会通过，
#: 但通过的原因是什么都没验证。调小之后同一篇正文切出多个子块，这些情形才是真的。
TEST_POLICY = ChunkingPolicy(
    child_min_tokens=20,
    child_target_tokens=30,
    child_soft_cap_tokens=60,
    child_overlap_tokens=5,
    parent_target_tokens=120,
    parent_max_tokens=240,
)

#: 检索探针用的嵌入口径。必须与被测链路的嵌入口径一致，否则探针向量与索引里的向量不在
#: 同一个空间里。
EMBEDDING_DIMENSION = 32

DOCUMENT_ID = "doc_storage_2026"
VERSION_ID = "ver_storage_2026_01"
JOB_ID = "job_storage_2026_01"
WORKER = "worker-1"
ORIGINAL_KEY = "original/doc_storage_2026/ver_storage_2026_01/report.txt"

BODY = """储能行业 2026 年中期策略

需求侧

2026 年上半年全球储能新增装机同比增长四成。国内大储招标量创下历史新高。
海外需求同样强劲，欧洲与中东的订单占比明显提升。

供给侧

电芯价格继续下行，二线厂商的产能利用率承压。头部厂商的海外产能开始释放。
"""


# --- 可控的向量索引 ---


class _ControllableVectorIndex:
    """按测试需要在写入或发布上做手脚的向量索引。

    规格 10 要求"写了一半的索引不可见"。真实 Milvus 断在半路时留下的是一批没有发布的
    实体，这里照做：把前缀真的交给底层写进去，然后抛异常——如果实现依赖"整批都写成功了"
    这个没有保证的前提，这个夹具会立刻揭穿它。
    """

    def __init__(self, inner: VectorIndex) -> None:
        self._inner = inner
        self.fail_after: int | None = None
        self.fail_publish = False
        self.drop_first_record = False
        self.inject_stray = False
        #: 维护任务调用过 `delete_records` 的记录，供"孤立向量被谁清掉了"的断言使用。
        self.deleted_records: list[tuple[str, tuple[str, ...]]] = []

    def stage(self, *, generation: str, records: Sequence[VectorRecord]) -> None:
        if self.drop_first_record and len(records) > 1:
            self.drop_first_record = False
            records = records[1:]
        if self.inject_stray and records:
            self.inject_stray = False
            records = (*records, records[0].model_copy(update={"chunk_id": "chunk_stray"}))
        if self.fail_after is not None and self.fail_after < len(records):
            self._inner.stage(generation=generation, records=records[: self.fail_after])
            raise IndexRecordConflict(
                f"the vector write was cut off after {self.fail_after} records"
            )
        self._inner.stage(generation=generation, records=records)

    def publish(self, *, generation: str) -> None:
        if self.fail_publish:
            raise VectorIndexError("the index is unreachable")
        self._inner.publish(generation=generation)

    def verify(self, *, generation: str, expected_ids: set[str]) -> IndexVerification:
        return self._inner.verify(generation=generation, expected_ids=expected_ids)

    def hybrid_search(self, query: HybridQuery) -> tuple[VectorHit, ...]:
        return self._inner.hybrid_search(query)

    def delete_generation(self, *, generation: str) -> None:
        self._inner.delete_generation(generation=generation)

    def delete_records(self, *, generation: str, chunk_ids: Sequence[str]) -> int:
        self.deleted_records.append((generation, tuple(chunk_ids)))
        return self._inner.delete_records(generation=generation, chunk_ids=chunk_ids)


# --- 可控的 Provider ---


class _AlwaysFailingEmbedding:
    def __init__(self, error: ProviderError) -> None:
        self.error = error
        self.calls = 0

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
        self.calls += 1
        raise self.error


class _FlakyEmbedding:
    """第一次调用失败、之后成功的 embedding：用来验证"可重试"真的能重试成功。"""

    def __init__(self, inner: EmbeddingProvider) -> None:
        self._inner = inner
        self.error: ProviderError | None = ProviderUnavailable("the embedding service is down")

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
        if self.error is not None:
            raise self.error
        return self._inner.embed(texts)


class _BrokenParser:
    """总是拒绝这份文件的解析器：验证失败分类，而不是让流水线去猜格式。"""

    name = "broken"
    media_types = frozenset({"text/plain"})

    def __init__(self, error: Exception) -> None:
        self.error = error

    def parse(self, source: ParseSource) -> ParsedDocument:
        raise self.error


# --- 装配 ---


class _Harness:
    """一条离线可跑的完整摄取与检索链路。"""

    def __init__(
        self,
        *,
        parsers: Sequence[DocumentParser] | None = None,
        embedding: EmbeddingProvider | None = None,
    ) -> None:
        self.repository = InMemoryResearchLibraryRepository()
        self.assets = InMemoryResearchAssetStore()
        self.index = _ControllableVectorIndex(InMemoryVectorIndex())
        self.embedding: EmbeddingProvider = (
            embedding
            if embedding is not None
            else FixtureEmbeddingProvider(dimension=EMBEDDING_DIMENSION)
        )
        # 检索用的探针单独一份：被测链路的 embedding 可能被故意弄坏，而"弄坏之后还看得见
        # 什么"正是要观察的东西——用同一个坏掉的 provider 去查，只会得到它自己的异常。
        self.probe = FixtureEmbeddingProvider(dimension=EMBEDDING_DIMENSION)
        self.parse_pipeline = ResearchParsePipeline(
            parsers=tuple(parsers) if parsers is not None else (TextDocumentParser(),)
        )
        self.worker = IndexOutboxWorker(repository=self.repository, vector_index=self.index)
        self.coordinator = ResearchIngestionCoordinator(
            repository=self.repository,
            assets=self.assets,
            parse_pipeline=self.parse_pipeline,
            chunker=StructuralChunker(),
            embedding=self.embedding,
            vector_index=self.index,
            outbox=self.worker,
            chunking_policy=TEST_POLICY,
            lease_seconds=LEASE_SECONDS,
        )

    # --- 文档 ---

    def add_document(
        self,
        *,
        document_id: str = DOCUMENT_ID,
        version_id: str = VERSION_ID,
        job_id: str = JOB_ID,
        body: str = BODY,
        media_type: str = "text/plain",
        max_attempts: int = 3,
    ) -> ResearchDocumentVersion:
        self.repository.create_document(
            ResearchDocument(
                document_id=document_id,
                title="储能行业 2026 年中期策略",
                document_type=DocumentType.REPORT,
                institution="测试研究院",
                created_at=NOW,
            )
        )
        version = ResearchDocumentVersion(
            document_version_id=version_id,
            document_id=document_id,
            version_number=1,
            uploaded_at=NOW,
            published_at=PUBLISHED_AT,
            original_file_hash="a" * 64,
        )
        self._store_original(
            version_id=version_id,
            key=ORIGINAL_KEY,
            body=body,
            media_type=media_type,
        )
        stored = self.repository.create_version(version)
        self.repository.register_original_asset(version_id, ORIGINAL_KEY)
        self.repository.create_ingestion_job(
            new_ingestion_job(
                document_id=document_id,
                document_version_id=version_id,
                created_at=NOW,
                max_attempts=max_attempts,
            ).model_copy(update={"job_id": job_id})
        )
        return stored

    def add_revision(
        self,
        *,
        version_id: str,
        version_number: int,
        job_id: str,
        body: str = BODY + "\n本期新增：中东订单占比继续提升。\n",
    ) -> ResearchDocumentVersion:
        """同一份文档的下一版。"""
        key = f"original/{DOCUMENT_ID}/{version_id}/report.txt"
        self._store_original(version_id=version_id, key=key, body=body)
        stored = self.repository.create_version(
            ResearchDocumentVersion(
                document_version_id=version_id,
                document_id=DOCUMENT_ID,
                version_number=version_number,
                uploaded_at=NOW,
                published_at=PUBLISHED_AT,
                original_file_hash=f"{version_number}" * 64,
            )
        )
        self.repository.register_original_asset(version_id, key)
        self.repository.create_ingestion_job(
            new_ingestion_job(
                document_id=DOCUMENT_ID,
                document_version_id=version_id,
                created_at=NOW,
            ).model_copy(update={"job_id": job_id})
        )
        return stored

    def _store_original(
        self,
        *,
        version_id: str,
        key: str,
        body: str,
        media_type: str = "text/plain",
    ) -> None:
        self.assets.put(
            key=key,
            content=BytesIO(body.encode("utf-8")),
            metadata=AssetMetadata(
                content_type=media_type,
                asset_role=AssetRole.ORIGINAL,
                document_id=DOCUMENT_ID,
                document_version_id=version_id,
            ),
        )

    # --- 运行与观察 ---

    def run(
        self, *, job_id: str = JOB_ID, now: datetime = NOW, worker: str = WORKER
    ) -> IngestionJob:
        return self.coordinator.run(job_id, worker_id=worker, now=now)

    def search(self, question: str) -> tuple[str, ...]:
        """测试用检索：权威复核之后仍然可见的切片 ID。

        `filter_active_hits` 是生产代码，这里刻意调用它而不是绕开——"Milvus 里出现过的
        东西是否真的可见"正是要观察的性质，绕开它等于把被检验的那一层替换掉。
        """
        vector = self.probe.embed([question]).vectors[0]
        hits = self.index.hybrid_search(HybridQuery(query_text=question, dense_vector=vector))
        return tuple(hit.chunk_id for hit in filter_active_hits(hits, repository=self.repository))

    def version(self, version_id: str = VERSION_ID) -> ResearchDocumentVersion:
        stored = self.repository.get_version(version_id)
        assert stored is not None
        return stored

    def job(self, job_id: str = JOB_ID) -> IngestionJob:
        stored = self.repository.get_ingestion_job(job_id)
        assert stored is not None
        return stored

    def events(self):
        return self.repository.list_outbox_events()

    def generation_of(self, version_id: str = VERSION_ID) -> str:
        generation = self.version(version_id).index_generation
        assert generation is not None, "the version never recorded the generation it was built in"
        return generation

    def indexable_ids(self, version_id: str = VERSION_ID) -> set[str]:
        """进索引的是子块；父块只用来展开上下文（规格 8）。"""
        return {
            chunk.chunk_id
            for chunk in self.repository.list_chunks(version_id)
            if chunk.parent_chunk_id is not None
        }


@pytest.fixture
def harness() -> _Harness:
    return _Harness()


# --- 1. 成功 ---


def test_a_healthy_document_ends_up_active_and_searchable(harness: _Harness) -> None:
    harness.add_document()

    job = harness.run()

    assert job.status is IngestionStatus.PUBLISHED
    version = harness.version()
    assert version.status is DocumentVersionStatus.ACTIVE
    assert version.parser_version is not None
    assert version.chunking_policy_version is not None
    assert version.embedding_provider is not None
    assert version.embedding_model_version is not None
    assert version.indexed_at is not None
    assert harness.repository.list_chunks(VERSION_ID)
    document = harness.repository.get_document(DOCUMENT_ID)
    assert document is not None
    assert document.current_version_id == VERSION_ID
    assert harness.search("储能装机增长")


def test_only_child_chunks_are_vectorised(harness: _Harness) -> None:
    """父块是拿来展开上下文的，不参与向量召回；把它也塞进索引只会挤占 Top-K。"""
    harness.add_document()

    harness.run()

    expected = harness.indexable_ids()
    children = [
        chunk
        for chunk in harness.repository.list_chunks(VERSION_ID)
        if chunk.parent_chunk_id is not None
    ]
    assert children
    assert len(children) < len(harness.repository.list_chunks(VERSION_ID))
    assert harness.version().expected_chunk_count == len(children)
    verification = harness.index.verify(generation=harness.generation_of(), expected_ids=expected)
    assert verification.is_complete
    assert verification.published


def test_the_indexed_record_carries_the_metadata_the_filters_need(harness: _Harness) -> None:
    """过滤在 Milvus 里执行，因此这些取值必须真的写进了索引，而不是留在旁边某处。"""
    harness.add_document()

    harness.run()

    hits = harness.index.hybrid_search(
        HybridQuery(
            query_text="储能",
            dense_vector=harness.embedding.embed(["储能"]).vectors[0],
        )
    )
    assert hits
    assert hits[0].document_type is DocumentType.REPORT
    assert hits[0].content.strip()


# --- 2. 解析失败是终态 ---


def test_an_unsupported_document_fails_permanently() -> None:
    broken = _Harness(parsers=(_BrokenParser(UnsupportedMediaType("no parser here")),))
    broken.add_document()

    job = broken.run()

    assert job.status is IngestionStatus.PERMANENT_FAILED
    assert "no parser here" in (job.failure_reason or "")
    assert broken.version().status is DocumentVersionStatus.PROCESSING
    assert broken.search("储能") == ()


def test_a_document_without_a_registered_original_fails_permanently(harness: _Harness) -> None:
    """没有原件的版本不该被当成"空文档"成功走完，那会让一份空索引看起来是完整的。"""
    harness.add_document()
    empty = InMemoryResearchLibraryRepository()
    empty.create_document(
        ResearchDocument(
            document_id="doc_orphan",
            title="没有原件",
            document_type=DocumentType.REPORT,
            created_at=NOW,
        )
    )
    empty.create_version(
        ResearchDocumentVersion(
            document_version_id="ver_orphan",
            document_id="doc_orphan",
            version_number=1,
            uploaded_at=NOW,
            original_file_hash="b" * 64,
        )
    )
    empty.create_ingestion_job(
        new_ingestion_job(
            document_id="doc_orphan",
            document_version_id="ver_orphan",
            created_at=NOW,
        ).model_copy(update={"job_id": "job_orphan"})
    )
    orphan = ResearchIngestionCoordinator(
        repository=empty,
        assets=harness.assets,
        parse_pipeline=harness.parse_pipeline,
        chunker=StructuralChunker(),
        embedding=harness.embedding,
        vector_index=harness.index,
        outbox=IndexOutboxWorker(repository=empty, vector_index=harness.index),
        lease_seconds=LEASE_SECONDS,
    )

    job = orphan.run("job_orphan", worker_id=WORKER, now=NOW)

    assert job.status is IngestionStatus.PERMANENT_FAILED


# --- 3. Provider 失败 ---


def test_a_retriable_provider_failure_stays_retryable() -> None:
    broken = _Harness(embedding=_AlwaysFailingEmbedding(ProviderUnavailable("down")))
    broken.add_document()

    job = broken.run()

    assert job.status is IngestionStatus.RETRYABLE_FAILED
    assert broken.version().status is DocumentVersionStatus.PROCESSING
    assert broken.search("储能") == ()
    # 一条索引意图都没有登记，因为失败发生在 `_embed`，`_index` 还没轮到——所以"没有被标成
    # DONE 的事件"是**空列表上恒真**的一句话，它对任何实现都成立，包括一个把事件错误地标成
    # DONE 的实现。写明是空的，加上上一行派生索引里查不到东西，才等于"什么都没发布"。
    assert broken.events() == ()


def test_a_rejected_provider_call_fails_permanently() -> None:
    """`ProviderRejected` 说的是"这个请求本身不对"，重试只会把同一个错误再问一遍。"""
    broken = _Harness(embedding=_AlwaysFailingEmbedding(ProviderRejected("bad batch")))
    broken.add_document()

    assert broken.run().status is IngestionStatus.PERMANENT_FAILED


def test_retrying_after_a_provider_failure_succeeds() -> None:
    """可重试失败必须真的能重试成功，否则这个状态只是一个更好看的死胡同。"""
    flaky = _FlakyEmbedding(FixtureEmbeddingProvider(dimension=32))
    harness = _Harness(embedding=flaky)
    harness.add_document()

    assert harness.run().status is IngestionStatus.RETRYABLE_FAILED

    flaky.error = None
    second = harness.run(now=NOW + timedelta(seconds=1))

    assert second.status is IngestionStatus.PUBLISHED
    assert harness.version().status is DocumentVersionStatus.ACTIVE
    assert harness.search("储能装机增长")


def test_attempts_are_exhausted_into_a_permanent_failure() -> None:
    """`max_attempts` 用尽后还留在可重试状态，只会让任务在队列里永远转圈。"""
    broken = _Harness(embedding=_AlwaysFailingEmbedding(ProviderUnavailable("down")))
    broken.add_document(max_attempts=1)

    job = broken.run()

    assert job.status is IngestionStatus.PERMANENT_FAILED
    assert "attempt" in (job.failure_reason or "").lower()


# --- 4. 半途写坏的索引不可见 ---


def test_a_partially_written_index_is_never_visible(harness: _Harness) -> None:
    harness.index.fail_after = 1
    harness.add_document()

    job = harness.run()

    assert job.status is not IngestionStatus.PUBLISHED
    assert harness.version().status is DocumentVersionStatus.PROCESSING
    assert harness.search("储能") == ()
    # 承上：这一代里确实躺着写了一半的记录，否则这个测试什么都没证明。
    report = harness.index.verify(generation=harness.generation_of(), expected_ids=set())
    assert report.present_count == 1
    assert not report.published


def test_a_half_written_generation_stays_invisible_after_a_successful_retry(
    harness: _Harness,
) -> None:
    """写了一半之后重试成功：旧的那一半不能借着新一代的发布一起露出来。"""
    harness.index.fail_after = 1
    harness.add_document()
    harness.run()
    assert harness.version().status is DocumentVersionStatus.PROCESSING

    harness.index.fail_after = None
    harness.run(now=NOW + timedelta(seconds=1))

    assert harness.version().status is DocumentVersionStatus.ACTIVE
    assert harness.search("储能装机增长")
    assert set(harness.search("储能装机增长")) == harness.indexable_ids()


# --- 5. 崩溃与恢复 ---


def test_a_publish_failure_leaves_a_durable_intent_that_another_worker_finishes(
    harness: _Harness,
) -> None:
    """规格 10：可见性由 PostgreSQL 最终确认，因此"要做的事"必须先落库。

    进程在登记发布意图之后、兑现之前消失时，恢复靠的不是猜测，而是那条留在可认领状态的
    待办：另一个 worker 接手它，索引就追上了权威状态。
    """
    harness.index.fail_publish = True
    harness.add_document()

    job = harness.run()

    assert job.status is not IngestionStatus.PUBLISHED
    assert harness.version().status is DocumentVersionStatus.PROCESSING
    failed = [event for event in harness.events() if event.status is OutboxStatus.FAILED]
    assert len(failed) == 1
    assert failed[0].last_error
    assert not harness.index.verify(
        generation=harness.generation_of(), expected_ids=harness.indexable_ids()
    ).published

    harness.index.fail_publish = False
    finished = harness.worker.run_once(worker_id="worker-2", now=NOW + timedelta(seconds=5))

    assert [event.status for event in finished] == [OutboxStatus.DONE]
    assert harness.index.verify(
        generation=harness.generation_of(), expected_ids=harness.indexable_ids()
    ).published

    assert harness.run(now=NOW + timedelta(seconds=6)).status is IngestionStatus.PUBLISHED
    assert harness.version().status is DocumentVersionStatus.ACTIVE


def test_a_stale_claim_is_reclaimable_only_after_it_goes_stale(harness: _Harness) -> None:
    """一个认领后崩掉的 worker 不能把事件永久扣住，但也不能立刻被抢走。"""
    harness.add_document()
    harness.repository.enqueue_index_event(
        IndexOutboxEvent(
            event_id="idx_orphan",
            document_version_id=VERSION_ID,
            index_generation="gen_orphan",
            operation=OutboxOperation.PUBLISH_GENERATION,
            available_at=NOW,
            created_at=NOW,
        )
    )
    event = harness.repository.claim_outbox_events(worker_id="dead-worker", now=NOW)[0]
    assert event.status is OutboxStatus.CLAIMED

    assert harness.repository.claim_outbox_events(worker_id="worker-2", now=NOW) == ()
    reclaimed = harness.repository.claim_outbox_events(
        worker_id="worker-2", now=NOW + timedelta(seconds=301)
    )

    assert [held.event_id for held in reclaimed] == [event.event_id]
    assert reclaimed[0].attempt_count == 2


def test_re_enqueuing_a_settled_intent_re_arms_it_and_leaves_the_others_alone(
    harness: _Harness,
) -> None:
    """同一条意图再登记一次：兑现过的重新要一次，没兑现的一律原样。

    重建索引登记的 `event_id` 与摄取时那一条相同（规格 16.3），而那一代可能已经发布过、
    事件已经落成 `DONE`。此时不重新登记，重建写回去的切片就永远停在 STAGED。反过来，
    `CLAIMED` / `FAILED` 的行必须原样返回：重新登记不等于把别人的认领抹掉。
    """
    harness.add_document()

    def intent(event_id: str, generation: str) -> IndexOutboxEvent:
        return IndexOutboxEvent(
            event_id=event_id,
            document_version_id=VERSION_ID,
            index_generation=generation,
            operation=OutboxOperation.PUBLISH_GENERATION,
            available_at=NOW,
            created_at=NOW,
        )

    settled = intent("idx_settled", "gen_settled")
    harness.repository.enqueue_index_event(settled)
    harness.repository.claim_outbox_events(worker_id="worker-1", now=NOW)
    harness.repository.finish_outbox_event(settled.event_id, worker_id="worker-1", now=NOW)

    rearmed = harness.repository.enqueue_index_event(settled)

    assert rearmed.status is OutboxStatus.PENDING
    assert rearmed.attempt_count == 0
    assert rearmed.claimed_by is None
    reclaimed = harness.repository.claim_outbox_events(worker_id="worker-2", now=NOW)
    assert [held.event_id for held in reclaimed] == [settled.event_id]

    claimed = intent("idx_claimed", "gen_claimed")
    harness.repository.enqueue_index_event(claimed)
    harness.repository.claim_outbox_events(worker_id="worker-3", now=NOW)
    still_claimed = harness.repository.enqueue_index_event(claimed)
    assert still_claimed.status is OutboxStatus.CLAIMED
    assert still_claimed.claimed_by == "worker-3"

    harness.repository.finish_outbox_event(
        claimed.event_id, worker_id="worker-3", now=NOW, error="milvus refused the upsert"
    )
    still_failed = harness.repository.enqueue_index_event(claimed)
    assert still_failed.status is OutboxStatus.FAILED
    assert still_failed.last_error == "milvus refused the upsert"


# --- 6/7/8. 租约、接管、取消、迟到的 attempt ---


def test_an_expired_lease_is_taken_over_by_a_new_attempt(harness: _Harness) -> None:
    harness.add_document()
    first = harness.repository.acquire_ingestion_job(
        JOB_ID, worker_id="worker-1", now=NOW, lease_seconds=LEASE_SECONDS
    )

    second = harness.repository.acquire_ingestion_job(
        JOB_ID,
        worker_id="worker-2",
        now=NOW + timedelta(seconds=LEASE_SECONDS + 1),
        lease_seconds=LEASE_SECONDS,
    )

    assert first.attempt_id == 1
    assert second.attempt_id == 2
    assert second.worker_id == "worker-2"


def test_a_live_lease_cannot_be_stolen(harness: _Harness) -> None:
    harness.add_document()
    harness.repository.acquire_ingestion_job(
        JOB_ID, worker_id="worker-1", now=NOW, lease_seconds=LEASE_SECONDS
    )

    with pytest.raises(ResearchLibraryConflict):
        harness.repository.acquire_ingestion_job(
            JOB_ID, worker_id="worker-2", now=NOW + timedelta(seconds=1), lease_seconds=100
        )


def test_a_cancelled_job_is_never_worked_on(harness: _Harness) -> None:
    harness.add_document()
    harness.repository.save_ingestion_job(
        harness.job().model_copy(update={"status": IngestionStatus.CANCELLED, "updated_at": NOW}),
        expected_status=IngestionStatus.RECEIVED,
        expected_attempt=0,
    )

    returned = harness.run()

    assert returned.status is IngestionStatus.CANCELLED
    assert harness.version().status is DocumentVersionStatus.PROCESSING
    assert harness.repository.list_chunks(VERSION_ID) == ()
    assert harness.search("储能") == ()


def test_a_late_attempt_cannot_write_anything(harness: _Harness) -> None:
    """旧 attempt 的迟到结果必须在权威库里被拒，而不是靠调用方自觉（规格 19）。"""
    harness.add_document()
    stale = harness.repository.acquire_ingestion_job(
        JOB_ID, worker_id="worker-1", now=NOW, lease_seconds=LEASE_SECONDS
    )
    harness.repository.acquire_ingestion_job(
        JOB_ID,
        worker_id="worker-2",
        now=NOW + timedelta(seconds=LEASE_SECONDS + 1),
        lease_seconds=LEASE_SECONDS,
    )

    with pytest.raises(ResearchLibraryConflict):
        harness.repository.save_ingestion_job(
            stale.model_copy(update={"status": IngestionStatus.PARSING, "updated_at": NOW}),
            expected_status=stale.status,
            expected_attempt=stale.attempt_id,
        )


def test_a_stale_worker_stops_instead_of_failing_the_job(harness: _Harness) -> None:
    """被接管的 worker 回来收尾时，不能把已经属于别人的任务写成失败。"""
    harness.add_document()
    harness.repository.acquire_ingestion_job(
        JOB_ID, worker_id="worker-1", now=NOW, lease_seconds=LEASE_SECONDS
    )
    taken_over = harness.repository.acquire_ingestion_job(
        JOB_ID,
        worker_id="worker-2",
        now=NOW + timedelta(seconds=LEASE_SECONDS + 1),
        lease_seconds=LEASE_SECONDS,
    )

    returned = harness.run(now=NOW + timedelta(seconds=LEASE_SECONDS + 2))

    # 这一次 run 用的就是 worker-1 的身份——也就是**那个租约已经被 worker-2 拿走的** worker，
    # 因为 `WORKER` 是 "worker-1"，而 `run` 默认用它。它抢不到租约，于是整条路径收敛成
    # 返回权威库里的现状。所以这里要断言的是"一个字都没写"：租约还在 worker-2 手上、attempt
    # 没有前进、状态停在接管者留下的那一段、而且没有被判成失败——后者正是这个用例的名字。
    assert returned.worker_id == "worker-2"
    assert returned.attempt_id == taken_over.attempt_id
    assert returned.status is taken_over.status
    assert returned.failure_reason is None


# --- 9. 幂等重放 ---


def test_rerunning_a_finished_job_changes_nothing(harness: _Harness) -> None:
    harness.add_document()
    harness.run()

    before = harness.search("储能装机增长")
    chunks = harness.repository.list_chunks(VERSION_ID)

    returned = harness.run(now=NOW + timedelta(seconds=30))

    assert returned.status is IngestionStatus.PUBLISHED
    assert harness.version().status is DocumentVersionStatus.ACTIVE
    assert harness.repository.list_chunks(VERSION_ID) == chunks
    assert harness.search("储能装机增长") == before


def test_replaying_a_crashed_attempt_does_not_duplicate_chunks(harness: _Harness) -> None:
    """`chunk_id` 是主键：重放时再插一遍会直接撞键，所以追加必须是可重入的。"""
    harness.index.fail_after = 0
    harness.add_document()

    harness.run()
    first = harness.repository.list_chunks(VERSION_ID)
    assert first

    harness.index.fail_after = None
    harness.run(now=NOW + timedelta(seconds=1))

    assert harness.repository.list_chunks(VERSION_ID) == first
    assert harness.version().status is DocumentVersionStatus.ACTIVE


# --- 10. 数量 / ID 不匹配 ---


def test_a_missing_vector_blocks_publication(harness: _Harness) -> None:
    """索引里少一条就等于这份文档少一段内容，而报告不会告诉你它少了哪一段。"""
    harness.index.drop_first_record = True
    harness.add_document()

    job = harness.run()

    assert job.status is not IngestionStatus.PUBLISHED
    assert harness.version().status is DocumentVersionStatus.PROCESSING
    assert harness.search("储能") == ()


def test_an_extra_vector_blocks_publication(harness: _Harness) -> None:
    """多一条同样致命：那一代里混进了不属于这一版的内容，放出去就是来源错误的证据。"""
    harness.index.inject_stray = True
    harness.add_document()

    job = harness.run()

    assert job.status is not IngestionStatus.PUBLISHED
    assert harness.version().status is DocumentVersionStatus.PROCESSING


# --- 11. 新版本构建期间旧版本照常服务 ---


def test_the_old_version_keeps_serving_while_the_new_one_fails_to_build(
    harness: _Harness,
) -> None:
    harness.add_document()
    harness.run()
    old_hits = harness.search("储能装机增长")
    assert old_hits

    harness.add_revision(version_id="ver_storage_2026_02", version_number=2, job_id="job_rev_02")
    harness.index.fail_after = 1
    harness.run(job_id="job_rev_02", now=NOW + timedelta(seconds=60))

    assert harness.version("ver_storage_2026_02").status is DocumentVersionStatus.PROCESSING
    assert harness.version(VERSION_ID).status is DocumentVersionStatus.ACTIVE
    assert harness.search("储能装机增长") == old_hits


def test_activating_a_new_version_supersedes_the_previous_one(harness: _Harness) -> None:
    harness.add_document()
    harness.run()

    harness.add_revision(version_id="ver_storage_2026_02", version_number=2, job_id="job_rev_02")
    harness.run(job_id="job_rev_02", now=NOW + timedelta(seconds=60))

    assert harness.version("ver_storage_2026_02").status is DocumentVersionStatus.ACTIVE
    assert harness.version(VERSION_ID).status is DocumentVersionStatus.SUPERSEDED
    document = harness.repository.get_document(DOCUMENT_ID)
    assert document is not None
    assert document.current_version_id == "ver_storage_2026_02"


def test_a_hit_from_a_superseded_version_is_dropped_before_it_is_used(
    harness: _Harness,
) -> None:
    """规格 10：Milvus 的 `index_state` 只减少无效候选，可见性最终由 PostgreSQL 复核。"""
    harness.add_document()
    harness.run()
    stale = harness.search("储能装机增长")
    assert stale

    harness.add_revision(version_id="ver_storage_2026_02", version_number=2, job_id="job_rev_02")
    harness.run(job_id="job_rev_02", now=NOW + timedelta(seconds=60))
    fresh = harness.search("储能装机增长")

    assert fresh
    assert set(fresh).isdisjoint(stale)


def test_an_unknown_version_is_not_active(harness: _Harness) -> None:
    """查不到状态与"不是 ACTIVE"必须都导致丢弃：默认放行是最坏的一种默认。"""
    hits = (_hit("chunk_x", "ver_never_seen"), _hit("chunk_y", VERSION_ID))

    assert filter_active_hits(hits, repository=harness.repository) == ()


def test_filter_active_hits_batches_the_status_lookup(harness: _Harness) -> None:
    """每次检索都要复核一遍候选，逐条查库会让这一步变成瓶颈。"""
    harness.add_document()
    harness.run()

    calls: list[list[str]] = []
    original = harness.repository.load_version_statuses

    def counted(document_version_ids: Sequence[str]) -> dict[str, DocumentVersionStatus]:
        calls.append(list(document_version_ids))
        return original(document_version_ids)

    harness.repository.load_version_statuses = counted  # type: ignore[method-assign]

    hits = tuple(_hit(f"chunk_{index}", VERSION_ID) for index in range(5))

    assert len(filter_active_hits(hits, repository=harness.repository)) == 5
    assert len(calls) == 1
    assert len(calls[0]) == 5


def _hit(chunk_id: str, document_version_id: str) -> VectorHit:
    return VectorHit(
        chunk_id=chunk_id,
        document_id=DOCUMENT_ID,
        document_version_id=document_version_id,
        chunk_type=ChunkType.TEXT,
        document_type=DocumentType.REPORT,
        content="储能需求同比增长。",
        content_origin=ExtractionMethod.NATIVE,
        requires_verification=False,
        fused_score=0.5,
    )
