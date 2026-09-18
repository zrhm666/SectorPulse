"""可见性闸门在真实 PostgreSQL 上的收敛行为。

`test_research_ingestion_pipeline.py` 用内存权威库把逻辑跑了一遍；这里跑的是同一套逻辑
落在真库上的那一半——**内存实现结构上无法复现的部分**：

- 条件写入的原子性：`save_version_metadata` 只写到状态还是它以为的那个版本；一处写全的
  那组列，第二次写入会不会把第一次写下的东西抹掉；
- `activate_version` 在**一个事务里**让新版本生效、旧版本失效；
- `enqueue_index_event` 的 `ON CONFLICT (event_id) DO NOTHING` 在真约束下确实幂等；
- 一条完整链路（协调器 + Outbox worker + 向量索引）落库之后，读回来的东西确实是那副
  样子，而不是内存里那份影子说是。

只跑真库：这套用例里的每一条都建立在"约束真的存在、事务真的原子"之上，用内存实现重写
一遍只会得到一批更弱的同义反复。没有配置专用测试库时整体跳过。
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import uuid4

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
from sector_pulse.ports.vector_index import (
    HybridQuery,
    IndexVerification,
    VectorHit,
    VectorIndex,
    VectorIndexError,
    VectorRecord,
)
from sector_pulse.storage.ports.research_library import ResearchLibraryConflict
from sector_pulse.storage.postgres.database import PostgresDatabase
from sector_pulse.storage.postgres.research_library.repository import (
    PostgresResearchLibraryRepository,
)
from sqlalchemy import text

pytestmark = pytest.mark.postgres

NOW = datetime.fromisoformat("2026-09-18T02:00:00+00:00")
LATER = NOW + timedelta(minutes=10)
LEASE_SECONDS = 300
EMBEDDING_DIMENSION = 32

BODY = """储能行业 2026 年中期策略

需求侧

2026 年上半年全球储能新增装机同比增长四成。国内大储招标量创下历史新高。
海外需求同样强劲，欧洲与中东的订单占比明显提升。

供给侧

电芯价格继续下行，二线厂商的产能利用率承压。头部厂商的海外产能开始释放。
"""

#: 与内存版本同一份调小的预算，理由见 `test_research_ingestion_pipeline.py`：用规格默认值
#: 整篇正文会装进一个子块，"写了一半"、"少一条"这些情形就没有发生的余地。
TEST_POLICY = ChunkingPolicy(
    child_min_tokens=20,
    child_target_tokens=30,
    child_soft_cap_tokens=60,
    child_overlap_tokens=5,
    parent_target_tokens=120,
    parent_max_tokens=240,
)

RESEARCH_TABLES = (
    "internal_research_evidence_sources",
    "internal_research_evidence",
    "research_conflict_decisions",
    "research_retrieval_audits",
    "research_index_outbox",
    "research_ingestion_jobs",
    "research_chunks",
    "research_document_assets",
    "research_document_versions",
    "research_documents",
)


def _dedicated_test_url() -> str:
    url = os.environ.get("SECTOR_PULSE_DATABASE_URL", "")
    if not url:
        pytest.skip("no dedicated _test PostgreSQL database is configured")
    return url


@pytest.fixture(scope="module")
def database() -> PostgresDatabase:
    instance = PostgresDatabase(_dedicated_test_url())
    try:
        instance.initialize()
        yield instance
    finally:
        instance.close()


@pytest.fixture
def repo(database: PostgresDatabase) -> PostgresResearchLibraryRepository:
    """An empty research library: every case starts from the same known state."""
    repository = PostgresResearchLibraryRepository(database)
    with database.start().begin() as connection:
        connection.exec_driver_sql(
            f"TRUNCATE {', '.join(RESEARCH_TABLES)} RESTART IDENTITY CASCADE"
        )
    return repository


@pytest.fixture
def mint() -> Callable[[str], str]:
    """A per-call unique suffix, so cases never collide inside a shared database."""

    def _mint(prefix: str) -> str:
        return f"{prefix}_{uuid4().hex[:12]}"

    return _mint


class Registered:
    """一份刚登记好、等着被摄取的资料。"""

    def __init__(
        self,
        *,
        document: ResearchDocument,
        version: ResearchDocumentVersion,
        job: IngestionJob,
        original_key: str,
    ) -> None:
        self.document = document
        self.version = version
        self.job = job
        self.original_key = original_key


@pytest.fixture
def registered(
    database: PostgresDatabase,
    repo: PostgresResearchLibraryRepository,
    mint: Callable[[str], str],
) -> Callable[..., Registered]:
    """登记一份文档、一版、一个任务和一份原件。"""

    def _register(
        *,
        document_id: str | None = None,
        version_id: str | None = None,
        job_id: str | None = None,
        version_number: int = 1,
        uploaded_at: datetime = NOW,
    ) -> Registered:
        """登记一版。带 `document_id` 时是给已有文档加一版，不重新建文档。"""
        if document_id is None:
            document = repo.create_document(
                ResearchDocument(
                    document_id=mint("doc"),
                    title="储能行业 2026 年中期策略",
                    document_type=DocumentType.REPORT,
                    institution="测试研究院",
                    created_at=NOW,
                )
            )
        else:
            existing = repo.get_document(document_id)
            assert existing is not None, f"document {document_id!r} was never created"
            document = existing
        version = repo.create_version(
            ResearchDocumentVersion(
                document_version_id=version_id or mint("docv"),
                document_id=document.document_id,
                version_number=version_number,
                uploaded_at=uploaded_at,
                published_at=datetime(2026, 2, 20, tzinfo=UTC),
                original_file_hash=f"{version_number:0<64}"[:64],
            )
        )
        job = repo.create_ingestion_job(
            IngestionJob(
                job_id=job_id or mint("job"),
                document_id=document.document_id,
                document_version_id=version.document_version_id,
                created_at=uploaded_at,
                updated_at=uploaded_at,
            )
        )
        key = f"original/{document.document_id}/{version.document_version_id}/report.txt"
        _insert_original_row(
            database,
            document_id=document.document_id,
            document_version_id=version.document_version_id,
            object_key=key,
            byte_size=len(BODY.encode("utf-8")),
        )
        return Registered(document=document, version=version, job=job, original_key=key)

    return _register


def _insert_original_row(
    database: PostgresDatabase,
    *,
    document_id: str,
    document_version_id: str,
    object_key: str,
    byte_size: int,
) -> None:
    """把原件登记进 `research_document_assets`。

    没有走仓储方法，因为现在还没有：登记原件属于上传命令（Task 18）。这里直接写同一张
    表，好让 `get_original_asset_key` 有东西可读——这里测的是读取，不是写入。
    """
    with database.start().begin() as connection:
        connection.execute(
            text(
                "INSERT INTO research_document_assets (asset_id, document_id, "
                "document_version_id, asset_role, object_key, content_type, byte_size, "
                "sha256, scan_status, created_at) VALUES (:asset_id, :document_id, "
                ":document_version_id, :asset_role, :object_key, :content_type, :byte_size, "
                ":sha256, :scan_status, :created_at)"
            ),
            {
                "asset_id": f"asset_{uuid4().hex[:12]}",
                "document_id": document_id,
                "document_version_id": document_version_id,
                "asset_role": AssetRole.ORIGINAL.value,
                "object_key": object_key,
                "content_type": "text/plain",
                "byte_size": byte_size,
                "sha256": "a" * 64,
                # Task 4：没有扫描器时如实写 NOT_SCANNED，不冒充干净文件。
                "scan_status": "NOT_SCANNED",
                "created_at": NOW.isoformat(),
            },
        )


class _UnpublishableIndex:
    """发布可以按开关失败的向量索引。"""

    def __init__(self, inner: VectorIndex) -> None:
        self._inner = inner
        self.fail_publish = False

    def stage(self, *, generation: str, records: Sequence[VectorRecord]) -> None:
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
        return self._inner.delete_records(generation=generation, chunk_ids=chunk_ids)


class _Pipeline:
    """真库上的完整链路：协调器写权威库，worker 推派生索引。"""

    def __init__(self, repo: PostgresResearchLibraryRepository) -> None:
        self.repository = repo
        self.assets = InMemoryResearchAssetStore()
        self.index = _UnpublishableIndex(InMemoryVectorIndex())
        # 检索探针单独一份：它是把问题变成同一个空间里一个向量的工具，与被测链路的嵌入器
        # 无关。
        self.probe = FixtureEmbeddingProvider(dimension=EMBEDDING_DIMENSION)
        self.worker = IndexOutboxWorker(repository=repo, vector_index=self.index)
        self.coordinator = ResearchIngestionCoordinator(
            repository=repo,
            assets=self.assets,
            parse_pipeline=ResearchParsePipeline(parsers=(TextDocumentParser(),)),
            chunker=StructuralChunker(),
            embedding=FixtureEmbeddingProvider(dimension=EMBEDDING_DIMENSION),
            vector_index=self.index,
            outbox=self.worker,
            chunking_policy=TEST_POLICY,
            lease_seconds=LEASE_SECONDS,
        )

    def store_body(self, registered: Registered, body: str = BODY) -> None:
        self.assets.put(
            key=registered.original_key,
            content=BytesIO(body.encode("utf-8")),
            metadata=AssetMetadata(
                content_type="text/plain",
                asset_role=AssetRole.ORIGINAL,
                document_id=registered.document.document_id,
                document_version_id=registered.version.document_version_id,
            ),
        )

    def run(
        self, registered: Registered, *, now: datetime = NOW, worker: str = "worker-1"
    ) -> IngestionJob:
        return self.coordinator.run(registered.job.job_id, worker_id=worker, now=now)

    def search(self, question: str) -> tuple[str, ...]:
        """仍然可见的切片 ID：向量命中之后再问权威库谁还是 ACTIVE。"""
        hits = self.index.hybrid_search(
            HybridQuery(
                query_text=question,
                dense_vector=self.probe.embed([question]).vectors[0],
            )
        )
        return tuple(hit.chunk_id for hit in filter_active_hits(hits, repository=self.repository))

    def outbox_statuses(self, registered: Registered) -> list[str]:
        # 直接读一行：端口只需要认领与结束，这里要断言的是那一行到底长什么样。
        with self.repository._database.start().connect() as connection:
            return [
                str(value)
                for value in connection.execute(
                    text(
                        "SELECT status FROM research_index_outbox WHERE "
                        "document_version_id = :document_version_id ORDER BY event_id"
                    ),
                    {"document_version_id": registered.version.document_version_id},
                ).scalars()
            ]


@pytest.fixture
def pipeline(repo: PostgresResearchLibraryRepository) -> _Pipeline:
    return _Pipeline(repo)


# --- `save_version_metadata` ---


def test_version_metadata_round_trips(repo, registered) -> None:
    held = registered()

    repo.save_version_metadata(
        held.version.model_copy(
            update={
                "parser_version": "parse-pipeline-v1",
                "chunking_policy_version": "chunking-policy-v2",
                "embedding_provider": "fixture",
                "embedding_model_version": "fixture-embedding-v1",
                "index_generation": "gen_round_trip",
                "expected_chunk_count": 5,
            }
        ),
        expected_status=DocumentVersionStatus.PROCESSING,
    )

    read_back = repo.get_version(held.version.document_version_id)
    assert read_back is not None
    assert read_back.parser_version == "parse-pipeline-v1"
    assert read_back.chunking_policy_version == "chunking-policy-v2"
    assert read_back.embedding_provider == "fixture"
    assert read_back.embedding_model_version == "fixture-embedding-v1"
    assert read_back.index_generation == "gen_round_trip"
    assert read_back.expected_chunk_count == 5
    # 记住口径不等于对外可见：`indexed_at` 由可见性闸门写，不由这次写入捎带。
    assert read_back.indexed_at is None
    assert read_back.status is DocumentVersionStatus.PROCESSING


def _complete_metadata(version: ResearchDocumentVersion, *, now: datetime = NOW):
    """把一版写成"可以被生效"的样子：规格 10 要求 ACTIVE 记得自己来自哪一代索引。"""
    return version.model_copy(
        update={
            "parser_version": "parse-pipeline-v1",
            "chunking_policy_version": "chunking-policy-v2",
            "embedding_provider": "fixture",
            "embedding_model_version": "fixture-embedding-v1",
            "index_generation": "gen_under_test",
            "expected_chunk_count": 2,
            "indexed_at": now,
        }
    )


def test_metadata_writes_are_refused_once_the_version_moved_on(repo, registered) -> None:
    """状态闸门：一个已经被别的 attempt 推进的版本，不该还能被补上一行口径描述。"""
    held = registered()
    version_id = held.version.document_version_id
    repo.save_version_metadata(
        _complete_metadata(held.version), expected_status=DocumentVersionStatus.PROCESSING
    )
    repo.activate_version(version_id, expected_status=DocumentVersionStatus.PROCESSING)

    with pytest.raises(ResearchLibraryConflict):
        repo.save_version_metadata(
            held.version.model_copy(update={"index_generation": "gen_too_late"}),
            expected_status=DocumentVersionStatus.PROCESSING,
        )

    read_back = repo.get_version(version_id)
    assert read_back is not None
    assert read_back.index_generation == "gen_under_test"


def test_the_schema_refuses_to_activate_a_version_without_index_provenance(
    repo, registered
) -> None:
    """规格 10 落在表结构上：ACTIVE 必须记得自己来自哪一代索引。

    这一条约束是"可见性无法与索引核对"这件事的最后一道闸门——所以它必须在数据库里，而
    不是只在某个调用点。一条忘记先写口径的生效路径，在这里会被顶回去，而不是安静地留下
    一个说不清出处的 ACTIVE 版本。
    """
    held = registered()

    with pytest.raises(ResearchLibraryConflict):
        repo.activate_version(
            held.version.document_version_id,
            expected_status=DocumentVersionStatus.PROCESSING,
        )

    read_back = repo.get_version(held.version.document_version_id)
    assert read_back is not None
    assert read_back.status is DocumentVersionStatus.PROCESSING


def test_a_second_metadata_write_does_not_erase_the_first(repo, registered) -> None:
    """这组列是一次写全的：第二次写入少带了哪个，哪个就会被 `NULL` 覆盖。

    解析阶段写下解析口径，嵌入阶段只新增嵌入口径与代名；如果嵌入阶段把解析口径一起抹成
    空，一个建好的索引就再也说不清自己是从哪一批切片、用哪个解析器出来的。
    """
    held = registered()
    version_id = held.version.document_version_id
    first = repo.save_version_metadata(
        held.version.model_copy(
            update={"parser_version": "parse-pipeline-v1", "chunking_policy_version": "cp-v2"}
        ),
        expected_status=DocumentVersionStatus.PROCESSING,
    )

    repo.save_version_metadata(
        first.model_copy(update={"embedding_provider": "fixture", "index_generation": "gen_two"}),
        expected_status=DocumentVersionStatus.PROCESSING,
    )

    read_back = repo.get_version(version_id)
    assert read_back is not None
    assert read_back.parser_version == "parse-pipeline-v1"
    assert read_back.chunking_policy_version == "cp-v2"
    assert read_back.embedding_provider == "fixture"
    assert read_back.index_generation == "gen_two"


# --- 原件对象键 ---


def test_an_unregistered_version_has_no_original_key(repo, registered) -> None:
    held = registered()

    assert repo.get_original_asset_key("docv_never_seen") is None
    assert repo.get_original_asset_key(held.version.document_version_id) == held.original_key


def test_a_deleted_original_is_not_returned(database: PostgresDatabase, repo, registered) -> None:
    """`deleted_at` 非空的资产是"曾经有过"，不是"现在能读"。"""
    held = registered()
    with database.start().begin() as connection:
        connection.execute(
            text(
                "UPDATE research_document_assets SET deleted_at = :deleted_at "
                "WHERE object_key = :object_key"
            ),
            {"deleted_at": NOW.isoformat(), "object_key": held.original_key},
        )

    assert repo.get_original_asset_key(held.version.document_version_id) is None


# --- Outbox 登记的幂等性 ---


def _event(version_id: str, generation: str) -> IndexOutboxEvent:
    return IndexOutboxEvent(
        event_id=f"idx_{version_id}_{OutboxOperation.PUBLISH_GENERATION.value}",
        document_version_id=version_id,
        index_generation=generation,
        operation=OutboxOperation.PUBLISH_GENERATION,
        available_at=NOW,
        created_at=NOW,
    )


def test_enqueuing_the_same_intent_three_times_leaves_one_row(
    database: PostgresDatabase, repo, registered
) -> None:
    held = registered()
    event = _event(held.version.document_version_id, "gen_once")

    repo.enqueue_index_event(event)
    repo.enqueue_index_event(event)
    repo.enqueue_index_event(event)

    with database.start().connect() as connection:
        rows = connection.execute(
            text("SELECT count(*) FROM research_index_outbox WHERE event_id = :event_id"),
            {"event_id": event.event_id},
        ).scalar_one()
    assert int(rows) == 1


def test_re_enqueuing_returns_the_stored_row_without_resetting_it(
    database: PostgresDatabase, repo, registered
) -> None:
    """重新登记一个意图不该把别人的认领抹掉，也不该把失败原因抹掉。

    用 `DO UPDATE` 实现幂等会在真库上悄悄通过"行数还是 1"的断言，却把状态打回 PENDING；
    这一条断言的是那一行**原样**回来。
    """
    held = registered()
    event = _event(held.version.document_version_id, "gen_claimed")
    repo.enqueue_index_event(event)
    claimed = repo.claim_outbox_events(worker_id="worker-1", now=NOW)
    assert [item.status for item in claimed] == [OutboxStatus.CLAIMED]
    repo.finish_outbox_event(
        event.event_id, worker_id="worker-1", now=NOW, error="the index is unreachable"
    )

    returned = repo.enqueue_index_event(event)

    assert returned.status is OutboxStatus.FAILED
    assert returned.attempt_count == 1
    assert returned.last_error == "the index is unreachable"
    with database.start().connect() as connection:
        stored = connection.execute(
            text(
                "SELECT status, attempt_count, last_error, claimed_by "
                "FROM research_index_outbox WHERE event_id = :event_id"
            ),
            {"event_id": event.event_id},
        ).first()
    assert stored is not None
    assert stored._mapping["status"] == OutboxStatus.FAILED.value
    assert stored._mapping["attempt_count"] == 1
    assert stored._mapping["last_error"] == "the index is unreachable"
    assert stored._mapping["claimed_by"] is None


def test_re_enqueuing_a_finished_intent_re_arms_it_for_the_rebuild(
    database: PostgresDatabase, repo, registered
) -> None:
    """已经兑现过的意图，再登记一次就是**重新要一次**，不是重复。

    重建一代索引做的是同一件事（同一个 `event_id`），而那一代可能已经被发布过、事件也已经
    落成 `DONE`。此时库里那条"发布意图"已经没有了：不重新登记，重建写回去的切片会一直停在
    STAGED，复核就永远说"还没发布"。所以 `DONE` 是"原样返回"的唯一例外——它既没有被谁认领，
    也没有失败原因要保留。
    """
    held = registered()
    event = _event(held.version.document_version_id, "gen_done")
    repo.enqueue_index_event(event)
    repo.claim_outbox_events(worker_id="worker-1", now=NOW)
    assert (
        repo.finish_outbox_event(event.event_id, worker_id="worker-1", now=NOW).status
        is OutboxStatus.DONE
    )

    returned = repo.enqueue_index_event(event)

    assert returned.status is OutboxStatus.PENDING
    assert returned.attempt_count == 0
    assert returned.claimed_by is None
    assert returned.claimed_at is None
    reclaimed = repo.claim_outbox_events(worker_id="worker-2", now=NOW + timedelta(seconds=5))
    assert [item.event_id for item in reclaimed] == [event.event_id]
    assert reclaimed[0].claimed_by == "worker-2"


# --- 真库上的完整链路 ---


def test_a_document_ingests_to_active_against_a_real_database(
    pipeline: _Pipeline, repo, registered
) -> None:
    held = registered()
    pipeline.store_body(held)

    returned = pipeline.run(held)

    assert returned.status is IngestionStatus.PUBLISHED
    stored = repo.get_version(held.version.document_version_id)
    assert stored is not None
    assert stored.status is DocumentVersionStatus.ACTIVE
    assert stored.parser_version is not None
    assert stored.chunking_policy_version is not None
    assert stored.embedding_provider is not None
    assert stored.embedding_model_version is not None
    assert stored.index_generation is not None
    assert stored.indexed_at is not None

    chunks = repo.list_chunks(held.version.document_version_id)
    children = [chunk for chunk in chunks if chunk.parent_chunk_id is not None]
    # 预期块数记的是**进索引的**那些（规格 8：父块只用于展开上下文）。
    assert stored.expected_chunk_count == len(children)
    # 少于两块时，"写了一半"与"少一条"这类情形根本没有发生的余地，整条链路会以一个空转的
    # 方式通过。
    assert len(children) > 1, "the fixture must produce more than one indexable chunk"
    assert pipeline.outbox_statuses(held) == [OutboxStatus.DONE.value]

    document = repo.get_document(held.document.document_id)
    assert document is not None
    assert document.current_version_id == held.version.document_version_id
    assert pipeline.search("储能装机增长")


def test_a_new_version_supersedes_the_old_one_in_one_activation(
    pipeline: _Pipeline, repo, registered
) -> None:
    """新版本构建期间旧版本照常服务；切换发生在一次激活里，不是两次。"""
    first = registered()
    pipeline.store_body(first)
    pipeline.run(first)
    old_hits = pipeline.search("储能装机增长")
    assert old_hits

    second = registered(
        document_id=first.document.document_id,
        version_number=2,
        uploaded_at=LATER,
    )
    pipeline.store_body(second, body=BODY + "\n本期新增：中东订单占比继续提升。\n")
    pipeline.run(second, now=LATER)

    activated = repo.get_version(second.version.document_version_id)
    superseded = repo.get_version(first.version.document_version_id)
    assert activated is not None
    assert superseded is not None
    assert activated.status is DocumentVersionStatus.ACTIVE
    assert superseded.status is DocumentVersionStatus.SUPERSEDED
    document = repo.get_document(first.document.document_id)
    assert document is not None
    assert document.current_version_id == second.version.document_version_id
    # 旧版本的切片可能还在 Milvus 里，但它已经不可见了。
    fresh = pipeline.search("储能装机增长")
    assert fresh
    assert set(fresh).isdisjoint(old_hits)


def test_a_failed_publication_is_recovered_by_another_worker(
    pipeline: _Pipeline, repo, registered
) -> None:
    """崩溃恢复在真库上的样子：意图停在可认领状态，另一个 worker 接手做完。"""
    held = registered()
    pipeline.store_body(held)
    pipeline.index.fail_publish = True

    failed = pipeline.run(held)

    assert failed.status is IngestionStatus.RETRYABLE_FAILED
    assert pipeline.outbox_statuses(held) == [OutboxStatus.FAILED.value]
    assert pipeline.search("储能装机增长") == ()
    unpublished = repo.get_version(held.version.document_version_id)
    assert unpublished is not None
    assert unpublished.status is DocumentVersionStatus.PROCESSING

    # 派生侧的失败与权威侧的重试是两条独立的时钟：可重试失败**保留**租约（那是退避），
    # 而 Outbox 里的失败事件下一秒就能被任何 worker 认领。所以这里由另一个 worker 直接把
    # 发布做完——版本仍然是 PROCESSING，它还没有被"生效"。
    pipeline.index.fail_publish = False
    finished = pipeline.worker.run_once(worker_id="worker-2", now=NOW + timedelta(seconds=5))

    assert [event.status for event in finished] == [OutboxStatus.DONE]
    still_unpublished = repo.get_version(held.version.document_version_id)
    assert still_unpublished is not None
    assert still_unpublished.status is DocumentVersionStatus.PROCESSING

    retry_at = NOW + timedelta(seconds=LEASE_SECONDS + 1)
    recovered = pipeline.run(held, now=retry_at, worker="worker-2")
    assert recovered.status is IngestionStatus.PUBLISHED
    assert recovered.attempt_id == 2
    published = repo.get_version(held.version.document_version_id)
    assert published is not None
    assert published.status is DocumentVersionStatus.ACTIVE
    assert pipeline.search("储能装机增长")


def test_two_workers_cannot_hold_the_same_lease(repo, registered) -> None:
    """规格 19：接管只在租约确实过期时发生。"""
    held = registered()
    repo.acquire_ingestion_job(
        held.job.job_id, worker_id="worker-1", now=NOW, lease_seconds=LEASE_SECONDS
    )

    with pytest.raises(ResearchLibraryConflict):
        repo.acquire_ingestion_job(
            held.job.job_id,
            worker_id="worker-2",
            now=NOW + timedelta(seconds=1),
            lease_seconds=60,
        )

    taken = repo.acquire_ingestion_job(
        held.job.job_id,
        worker_id="worker-2",
        now=NOW + timedelta(seconds=LEASE_SECONDS + 1),
        lease_seconds=60,
    )
    assert taken.worker_id == "worker-2"
    assert taken.attempt_id == 2


def test_a_chunk_of_a_version_that_stopped_being_active_is_filtered_out(
    pipeline: _Pipeline, repo, registered
) -> None:
    """`filter_active_hits` 问的是真库里的状态，而不是内存里的一份影子。"""
    held = registered()
    pipeline.store_body(held)
    pipeline.run(held)
    assert pipeline.search("储能装机增长")

    # 把版本直接改成 ARCHIVED：没有别的路能让一个 ACTIVE 版本停止可见，而这正是这里
    # 要观察的输入。
    with repo._database.start().begin() as connection:
        connection.execute(
            text(
                "UPDATE research_document_versions SET status = :archived "
                "WHERE document_version_id = :document_version_id"
            ),
            {
                "archived": DocumentVersionStatus.ARCHIVED.value,
                "document_version_id": held.version.document_version_id,
            },
        )

    assert pipeline.search("储能装机增长") == ()


def _hit(chunk_id: str, document_version_id: str) -> VectorHit:
    return VectorHit(
        chunk_id=chunk_id,
        document_id="doc_any",
        document_version_id=document_version_id,
        chunk_type=ChunkType.TEXT,
        document_type=DocumentType.REPORT,
        content="储能需求同比增长。",
        content_origin=ExtractionMethod.NATIVE,
        requires_verification=False,
        fused_score=0.5,
    )


def test_filter_active_hits_keeps_every_hit_of_an_active_version(repo, registered) -> None:
    """批量复核：一次查询覆盖所有候选版本，而不是每条命中查一次。"""
    held = registered()
    repo.save_version_metadata(
        _complete_metadata(held.version), expected_status=DocumentVersionStatus.PROCESSING
    )
    repo.activate_version(
        held.version.document_version_id, expected_status=DocumentVersionStatus.PROCESSING
    )
    hits = tuple(_hit(f"chunk_{index}", held.version.document_version_id) for index in range(4))

    kept = filter_active_hits(hits, repository=repo)

    assert [hit.chunk_id for hit in kept] == [hit.chunk_id for hit in hits]
    assert filter_active_hits((), repository=repo) == ()
