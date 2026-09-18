"""摄取协调器：把一份原件变成一版可检索、且已在权威库中生效的文档。

规格 7.2 与 10 规定的两条纪律，是这个模块的全部内容：

1. **先落库，再做副作用。** 每一段推进都先写进 `research_ingestion_jobs`，然后才去解析、
   切片、调用 Provider、写索引。进程可能死在任意两行代码之间，而重启后唯一能依赖的只有
   权威库里已经写下的东西。
2. **可见性最后确认。** 向量写进哪一代、那一代有没有发布、发布之后是否复核通过——只有
   这些都成立，版本才会被 `activate_version` 变成 ACTIVE，而这一步是条件写入：如果期间
   有人取消了这一版，它会失败而不是覆盖。

阶段里保留 `NORMALIZING` 是因为状态机已经声明了它（`INGESTION_TRANSITIONS`）；真正的
规范化在 `ResearchParsePipeline.parse` 里随解析一起完成，因此这一段只留下一条可观测的
边界，没有额外副作用。跳过它会让"这份文档现在到了哪一步"在某几种输入下无从回答。

**重放安全是设计出来的，不是碰巧的。** 每个阶段都能在同一个版本上重跑：切片按内容的
幂等 ID 追加、向量按代写入、发布是可重复的标量更新、生效是条件写入。因此"接不上就从头再
来一遍"始终是一个正确选项——而这正是崩溃恢复唯一能依靠的东西。
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from sector_pulse.application.research_library.chunking import (
    ChunkingPolicy,
    StructuralChunker,
)
from sector_pulse.application.research_library.indexing import IndexOutboxWorker
from sector_pulse.application.research_library.parsing import ResearchParsePipeline
from sector_pulse.domain.research_library.ingestion import (
    RESUMABLE_INGESTION_STAGES,
    InvalidIngestionTransition,
    transition_ingestion,
)
from sector_pulse.domain.research_library.models import (
    DocumentVersionStatus,
    IndexOutboxEvent,
    IngestionJob,
    IngestionStatus,
    OutboxOperation,
    ResearchChunk,
    ResearchDocument,
    ResearchDocumentVersion,
)
from sector_pulse.ports.research_assets import ResearchAssetStore
from sector_pulse.ports.research_models import (
    EmbeddingProvider,
    ParsedDocument,
    ParseError,
    ParseSource,
    ProviderError,
)
from sector_pulse.ports.vector_index import IndexVerification, VectorIndex, VectorRecord
from sector_pulse.storage.ports.research_library import (
    ResearchLibraryConflict,
    ResearchLibraryRepositoryPort,
)

#: 一次 `run` 的租约长度。取得租约之后的所有写入都带条件，因此这个数字只需覆盖一次正常
#: 处理时长；它太长只会让崩溃后的接管变慢。
DEFAULT_LEASE_SECONDS = 300

#: 一次提交给 Provider 的切片条数。整篇文档一次提交会在长文档上撞到请求体上限，逐条提交
#: 又会把一次摄取变成几百次往返。
DEFAULT_EMBEDDING_BATCH_SIZE = 64

#: 阶段顺序。`RESUMABLE_INGESTION_STAGES` 是它的子集，这里只是把它排成一条线。
_STAGE_ORDER: tuple[IngestionStatus, ...] = (
    IngestionStatus.VALIDATING,
    IngestionStatus.PARSING,
    IngestionStatus.NORMALIZING,
    IngestionStatus.CHUNKING,
    IngestionStatus.EMBEDDING,
    IngestionStatus.INDEXING,
    IngestionStatus.VERIFYING,
)


class UnrecoverableIngestionError(RuntimeError):
    """重跑多少遍都不会有不同结果的问题。

    单独成类，是因为它与"这次调用没成"必须区分开——后者重试有意义，前者只是在浪费一次
    完整的重跑。
    """


class RetriableIngestionError(RuntimeError):
    """再跑一遍就有机会成的问题：还差一步没做完，而这一步是重入的。

    "那一代还没发布"属于这一类，而不是失败：发布意图可能正躺在 Outbox 里等一个 worker。
    把它当成终态，等于让 outbox 机制在它唯一该起作用的场景里失去意义。
    """


def generation_for(
    version: ResearchDocumentVersion,
    *,
    provider: str,
    model_version: str,
    dimension: int,
) -> str:
    """索引代的名字：由版本、原件内容与嵌入口径共同决定。

    刻意不含 attempt 或时间戳。同一份内容、同一套嵌入口径重跑多少次都落在同一代上，于是
    "重跑"就是字面意义上的重跑：同一批主键、同一批向量、同一个发布结果。换一个嵌入模型
    会得到新一代，旧的那一代因此能继续服务到新的那一代复核通过为止（规格 16.2）。
    """
    material = "|".join(
        [
            version.document_version_id,
            version.original_file_hash,
            provider,
            model_version,
            str(dimension),
        ]
    )
    return f"gen_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def classify_failure(error: BaseException) -> IngestionStatus:
    """把异常翻译成"再跑一次有没有意义"。

    唯一重要的区分是：`ParseError` 描述的是**这份文件**，`ProviderError` 描述的是**这次
    调用**。前者重跑一百遍还是同一份文件；后者自带 `retriable`。
    """
    if isinstance(error, (UnrecoverableIngestionError, ParseError)):
        return IngestionStatus.PERMANENT_FAILED
    if isinstance(error, RetriableIngestionError):
        return IngestionStatus.RETRYABLE_FAILED
    if isinstance(error, ProviderError):
        return (
            IngestionStatus.RETRYABLE_FAILED
            if error.retriable
            else IngestionStatus.PERMANENT_FAILED
        )
    return IngestionStatus.RETRYABLE_FAILED


@dataclass
class _PipelineState:
    """一次 `run` 期间在阶段之间传递的东西。不写库的中间结果放这里。"""

    document: ResearchDocument
    version: ResearchDocumentVersion
    parsed: ParsedDocument | None = None
    records: tuple[VectorRecord, ...] = ()
    generation: str | None = None
    provider: str | None = None
    model_version: str | None = None


class ResearchIngestionCoordinator:
    """推进一个摄取任务，直到它落在一个终态上。"""

    def __init__(
        self,
        *,
        repository: ResearchLibraryRepositoryPort,
        assets: ResearchAssetStore,
        parse_pipeline: ResearchParsePipeline,
        chunker: StructuralChunker,
        embedding: EmbeddingProvider,
        vector_index: VectorIndex,
        outbox: IndexOutboxWorker,
        chunking_policy: ChunkingPolicy | None = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        embedding_batch_size: int = DEFAULT_EMBEDDING_BATCH_SIZE,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if embedding_batch_size <= 0:
            raise ValueError("embedding_batch_size must be positive")
        self._repository = repository
        self._assets = assets
        self._parse_pipeline = parse_pipeline
        self._chunker = chunker
        self._embedding = embedding
        self._vector_index = vector_index
        self._outbox = outbox
        self._policy = chunking_policy if chunking_policy is not None else ChunkingPolicy()
        self._lease_seconds = lease_seconds
        self._batch_size = embedding_batch_size

    # --- 入口 ---

    def rebuild_index(
        self, document_version_id: str, *, worker_id: str, now: datetime
    ) -> IndexVerification:
        """按权威切片重建一版的派生索引（规格 16.3、16.4）。

        只做"把库里已有的块重新嵌一遍、写进它们所属的那一代、发布、复核"。**不重新解析、
        不重新切片**：切片由内容与切片口径决定，换一套口径会产出另一批 `chunk_id`，那是换一代
        派生数据而不是重建这一代，而 `_chunk` 已经明确拒绝在条数对不上时覆盖库里躺着的块。

        这一条同时覆盖两种情形，因为它们做的是同一件事：

        - **索引丢了**：保留期内 Milvus 实体被删掉（规格 16.3 第 4 步），按同样的嵌入口径
          重跑会落回**同一个 generation**（`generation_for` 刻意不含时间与 attempt），于是
          重建就是字面意义上的重建。
        - **换了嵌入模型**：`chunk_id` 不变而 `generation_for` 的输入变了，于是嵌入写进新
          一代；复核通过之后版本才指向它。旧的 generation 在此之前一直照常服务（规格 16.2）。

        未通过的复核照旧抛出：这一代里多出来的记录（`unexpected_ids`）不是重写能修好的，
        它要先由维护任务清掉（`delete_records`）——把这一步自动做掉，等于让"索引里出现了
        不该有的东西"这件事不再被任何人看见。
        """
        version = self._repository.get_version(document_version_id)
        if version is None:
            raise UnrecoverableIngestionError(
                f"document version {document_version_id!r} does not exist"
            )
        if version.status not in (
            DocumentVersionStatus.ACTIVE,
            DocumentVersionStatus.SUPERSEDED,
        ):
            raise UnrecoverableIngestionError(
                f"document version {document_version_id!r} is {version.status}; only a version "
                f"that has been published before can have its index rebuilt"
            )
        document = self._repository.get_document(version.document_id)
        if document is None:
            raise UnrecoverableIngestionError(
                f"document {version.document_id!r} of version {document_version_id!r} is gone"
            )

        state = _PipelineState(document=document, version=version)
        records, generation = self._embed_indexable(state)
        expected = self._indexable_ids(document_version_id)
        self._vector_index.stage(generation=generation, records=records)
        # 意图先落库、再兑现，与摄取路径同一条规则：死在这两行之间时，留在库里的那条待办
        # 就是恢复的全部依据。event_id 由 generation 决定，因此重建登记的还是同一个意图。
        self._repository.enqueue_index_event(
            IndexOutboxEvent(
                event_id=f"idx_{generation}_{OutboxOperation.PUBLISH_GENERATION.value}",
                document_version_id=document_version_id,
                index_generation=generation,
                operation=OutboxOperation.PUBLISH_GENERATION,
                available_at=now,
                created_at=now,
            )
        )
        self._outbox.run_once(worker_id=worker_id, now=now)

        report = self._vector_index.verify(generation=generation, expected_ids=expected)
        self._require_verified(report, document_version_id)

        if version.index_generation != generation:
            self._repository.save_version_metadata(
                version.model_copy(
                    update={
                        "index_generation": generation,
                        "expected_chunk_count": len(expected),
                        "indexed_at": now,
                        "embedding_provider": state.provider,
                        "embedding_model_version": state.model_version,
                    }
                ),
                expected_status=version.status,
            )
        return report

    def run(self, job_id: str, worker_id: str, now: datetime) -> IngestionJob:
        """推进任务一次，返回它结束时的样子（不一定是终态）。

        所有"被并发者抢先"的情形都在这里收敛成一个结果：**返回权威库里的当前状态**。
        输掉竞争不是错误，把它写成失败才是——那会让一个正在被别人正常处理的任务莫名其妙
        地变成失败。
        """
        try:
            job = self._repository.acquire_ingestion_job(
                job_id, worker_id=worker_id, now=now, lease_seconds=self._lease_seconds
            )
        except ResearchLibraryConflict as error:
            return self._current_state(job_id, error)

        try:
            return self._advance(job, worker_id=worker_id, now=now)
        except ResearchLibraryConflict as error:
            return self._current_state(job_id, error)
        except Exception as error:
            # 失败必须写在任务**当前**所在的那一段上，而不是它开始的那一段：状态机只允许
            # 从当前状态出发的迁移，拿一个过期的状态去写，写出来的只会是一条冲突。
            return self._record_failure(self._latest(job), error, worker_id=worker_id, now=now)

    # --- 阶段推进 ---

    def _advance(self, job: IngestionJob, *, worker_id: str, now: datetime) -> IngestionJob:
        entry = (
            job.status if job.status in RESUMABLE_INGESTION_STAGES else IngestionStatus.VALIDATING
        )
        # 先进第一段、再打开文档：这样"读不到文档"这个失败也发生在某一段之内，因而是一条
        # 状态机允许的失败迁移，而不是一个卡在 RECEIVED 上的任务。
        if job.status is not entry:
            job = self._persist(job, entry, worker_id=worker_id, now=now)
        state = self._open(job)
        # 日期必须在**任何**派生数据之前定下来：切片行先于索引记录落库，而索引记录一旦生成
        # 就带着那个标量（规格 17）。放在这里而不是 `_index` 里，是因为 `_embed` 阶段就把记录
        # 建好并缓存在 `state.records` 上了。
        self._settle_published_at(state, now=now)

        for stage in _STAGE_ORDER[_STAGE_ORDER.index(entry) :]:
            # 先落库、再做副作用：这一步之后无论死在哪里，"任务在哪一段"都是可读的。
            if job.status is not stage:
                job = self._persist(job, stage, worker_id=worker_id, now=now)
            if stage is IngestionStatus.VERIFYING:
                return self._publish_and_activate(job, state, worker_id=worker_id, now=now)
            self._work(stage, state, worker_id=worker_id, now=now)

        raise AssertionError("the stage order must end in VERIFYING")

    def indexable_chunk_ids(self, document_version_id: str) -> frozenset[str]:
        """这一版**应该**出现在派生索引里的切片 ID（规格 8：父块只做上下文，不进向量）。

        公开出来是因为维护流程必须拿**同一个**定义去核对索引。各写一份"哪些块该进索引"
        的判断，两份漂移的那一天，核对报告会说索引缺了它本来就不该有的东西——而一份开始
        误报的报告会立刻失去全部价值。
        """
        return self._indexable_ids(document_version_id)

    def _open(self, job: IngestionJob) -> _PipelineState:
        document = self._repository.get_document(job.document_id)
        if document is None:
            raise UnrecoverableIngestionError(
                f"document {job.document_id!r} does not exist; the ingestion job outlived "
                f"the document it belongs to"
            )
        if document.deleted_at is not None:
            # 软删除之后不再推进：检索侧已经读不到它（可见性由权威库决定），而继续跑完会
            # 把一批向量写进索引，服务一份谁也看不到的文档。恢复之后用户可以重试这个任务，
            # 那正是"重试"这个动作存在的意义。
            raise UnrecoverableIngestionError(
                f"document {job.document_id!r} is soft-deleted; restore it and retry this job "
                f"instead of ingesting it"
            )
        version = self._repository.get_version(job.document_version_id)
        if version is None:
            raise UnrecoverableIngestionError(
                f"document version {job.document_version_id!r} does not exist"
            )
        return _PipelineState(document=document, version=version)

    def _work(
        self,
        stage: IngestionStatus,
        state: _PipelineState,
        *,
        worker_id: str,
        now: datetime,
    ) -> None:
        if stage is IngestionStatus.VALIDATING:
            self._validate(state)
        elif stage is IngestionStatus.PARSING:
            self._parse(state)
        elif stage is IngestionStatus.NORMALIZING:
            # 规范化在 `parse` 里随解析一起做完了（见模块文档）。这一段没有副作用。
            return
        elif stage is IngestionStatus.CHUNKING:
            self._chunk(state, now=now)
        elif stage is IngestionStatus.EMBEDDING:
            self._embed(state)
        elif stage is IngestionStatus.INDEXING:
            self._index(state, worker_id=worker_id, now=now)

    def _validate(self, state: _PipelineState) -> None:
        if state.version.status is not DocumentVersionStatus.PROCESSING:
            raise UnrecoverableIngestionError(
                f"document version {state.version.document_version_id!r} is "
                f"{state.version.status}, not PROCESSING"
            )
        key = self._repository.get_original_asset_key(state.version.document_version_id)
        if key is None:
            raise UnrecoverableIngestionError(
                f"document version {state.version.document_version_id!r} has no registered "
                f"original; without one there is nothing to parse"
            )
        try:
            self._assets.stat(key)
        except Exception as error:
            # 原件读不到同样是终态：重跑一百遍也不会凭空多出一份。
            raise UnrecoverableIngestionError(
                f"the original of {state.version.document_version_id!r} is not readable: {error}"
            ) from error

    def _parse(self, state: _PipelineState) -> None:
        key = self._repository.get_original_asset_key(state.version.document_version_id)
        if key is None:
            raise UnrecoverableIngestionError("the original disappeared between stages")
        reference = self._assets.stat(key)
        with self._assets.open(key) as handle:
            content = handle.read()
        state.parsed = self._parse_pipeline.parse(
            ParseSource(
                media_type=reference.content_type,
                content=content,
                filename=reference.metadata.filename,
            )
        )

    def _chunk(self, state: _PipelineState, *, now: datetime) -> None:
        """切出父块与子块并落库。

        切片本身总是重跑一遍（便宜、且确定），但**只有库里没有块时才写**：`chunk_id` 是
        主键，重放时再插一遍会直接撞键。条数对不上说明库里躺着的是别的东西，那种情况必须
        说出来而不是覆盖。
        """
        if state.parsed is None:
            self._parse(state)
        assert state.parsed is not None  # implied by _parse
        version_id = state.version.document_version_id
        chunks = self._chunker.chunk(
            state.parsed,
            self._policy,
            document_id=state.document.document_id,
            document_version_id=version_id,
            created_at=now,
        )
        stored = self._repository.count_chunks(version_id)
        if stored and stored != len(chunks):
            raise UnrecoverableIngestionError(
                f"document version {version_id!r} already holds {stored} chunks but chunking "
                f"it again produces {len(chunks)}; the stored chunks did not come from this "
                f"chunking policy"
            )
        if not stored:
            self._repository.append_chunks(chunks)
        # 口径比可见性先落库，且每次都要带上之前写过的取值：这个方法写的是整组元数据列，
        # 少带一个就等于把那一个抹掉。
        state.version = self._repository.save_version_metadata(
            state.version.model_copy(
                update={
                    "parser_version": state.parsed.parser_version,
                    "chunking_policy_version": self._policy.version,
                    "ocr_provider": state.parsed.ocr_provider,
                    "ocr_model_version": state.parsed.ocr_model_version,
                }
            ),
            expected_status=DocumentVersionStatus.PROCESSING,
        )

    def _embed(self, state: _PipelineState) -> None:
        records, generation = self._embed_indexable(state)
        state.records = records
        state.generation = generation
        state.version = self._repository.save_version_metadata(
            state.version.model_copy(
                update={
                    "embedding_provider": state.provider,
                    "embedding_model_version": state.model_version,
                    "index_generation": generation,
                    "expected_chunk_count": len(records),
                }
            ),
            expected_status=DocumentVersionStatus.PROCESSING,
        )

    def _settle_published_at(self, state: _PipelineState, *, now: datetime) -> None:
        """把这一版的发布日期定在最前面，任何派生数据之前（规格 17）。

        索引记录里的 `published_at` 是检索期要用的标量，因此它必须与权威库里的那一列**逐字
        相同**：重建一版时会把记录按同样的字段再算一遍，两处对不上就会被索引拒绝（"同一个
        ID 送来了不同内容"），而 Milvus 那边更糟——它会安静地按新值覆盖。

        未声明日期的版本，权威库在生效那一刻才用 `now` 补上（`activate_version` 的
        `COALESCE(published_at, now)`），而这里的 `now` 是生效时刻的墙上时钟，两边不可能对上。
        所以要在写第一份派生数据之前先把日期落到库里，顺带让那条 COALESCE 变成一句空操作。
        """
        version = state.version
        if version.published_at is not None:
            return
        if version.status is not DocumentVersionStatus.PROCESSING:
            # 已经不在处理中的版本，它的发布日期不是这一次能定的：生效过的版本早在生效时
            # 就有了，而被取消的版本不会再进索引。
            return
        settled = version.effective_from or now
        state.version = self._repository.save_version_metadata(
            version.model_copy(update={"published_at": settled}),
            expected_status=DocumentVersionStatus.PROCESSING,
        )

    def _index(self, state: _PipelineState, *, worker_id: str, now: datetime) -> None:
        generation = state.generation or state.version.index_generation
        if generation is None:
            raise UnrecoverableIngestionError(
                f"the index generation of {state.version.document_version_id!r} was never recorded"
            )
        expected = self._indexable_ids(state.version.document_version_id)
        if not self._vector_index.verify(generation=generation, expected_ids=expected).is_complete:
            # 已经完整落进这一代的就不再写第二遍——这是崩溃后从 INDEXING 接管时省下来的
            # 那件事。`verify` 比的是切片 ID 集合，而切片 ID 里含内容哈希与切片口径，
            # 因此"集合齐了"同时意味着"内容没变"。
            records = state.records
            if not records:
                records, _ = self._embed_indexable(state)
            self._vector_index.stage(generation=generation, records=records)

        # 意图先落库、再兑现。死在这两行之间时，留在库里的那条待办就是恢复的全部依据。
        self._repository.enqueue_index_event(
            IndexOutboxEvent(
                event_id=f"idx_{generation}_{OutboxOperation.PUBLISH_GENERATION.value}",
                document_version_id=state.version.document_version_id,
                index_generation=generation,
                operation=OutboxOperation.PUBLISH_GENERATION,
                available_at=now,
                created_at=now,
            )
        )
        self._outbox.run_once(worker_id=worker_id, now=now)

    def _publish_and_activate(
        self, job: IngestionJob, state: _PipelineState, *, worker_id: str, now: datetime
    ) -> IngestionJob:
        """复核、生效、推进到 PUBLISHED。

        复核是这里唯一有意义的门槛：Milvus 说"发布成功"和 Milvus 里真的有这一版的每一条
        切片，是两件事。数量或 ID 对不上时版本保持 PROCESSING，等下一次尝试。
        """
        version_id = state.version.document_version_id
        generation = state.generation or state.version.index_generation
        if generation is None:
            raise UnrecoverableIngestionError(
                f"document version {version_id!r} reached VERIFYING without a generation"
            )
        self._require_verified(
            self._vector_index.verify(
                generation=generation, expected_ids=self._indexable_ids(version_id)
            ),
            version_id,
        )

        if state.version.status is DocumentVersionStatus.ACTIVE:
            # 上一次尝试已经把版本生效了，只是没来得及把任务推进到终态。
            return self._persist(job, IngestionStatus.PUBLISHED, worker_id=worker_id, now=now)
        if state.version.status is not DocumentVersionStatus.PROCESSING:
            raise UnrecoverableIngestionError(
                f"document version {version_id!r} is {state.version.status}; it can no longer "
                f"be activated, so this ingestion can never finish"
            )
        state.version = self._repository.save_version_metadata(
            state.version.model_copy(update={"indexed_at": now}),
            expected_status=DocumentVersionStatus.PROCESSING,
        )
        # 条件写入：期间有人取消或取代了这一版，这里会失败而不是把它硬拉成 ACTIVE。
        self._repository.activate_version(
            version_id, expected_status=DocumentVersionStatus.PROCESSING
        )
        return self._persist(job, IngestionStatus.PUBLISHED, worker_id=worker_id, now=now)

    @staticmethod
    def _require_verified(report: IndexVerification, version_id: str) -> None:
        """复核这一代能不能拿去生效。

        分类的标准只有一条：**重跑能不能修好它**。少了几条可以再写一遍补上，没发布可以等
        Outbox 兑现或重新登记；可多出来的那几条补不上——写入是 upsert，没有删除动作，多
        出来的记录会永远留在这一代里。那种情况必须停下来，让一个人看。
        """
        if report.unexpected_ids:
            raise UnrecoverableIngestionError(
                f"generation {report.generation!r} of {version_id!r} holds "
                f"{len(report.unexpected_ids)} record(s) that do not belong to this version; "
                f"they cannot be removed by writing again, so publishing them would put "
                f"content of unknown provenance behind this version's citations"
            )
        if not report.published:
            raise RetriableIngestionError(
                f"generation {report.generation!r} of {version_id!r} is staged but not "
                f"published yet; the publish intent belongs in the outbox"
            )
        if report.missing_ids or not report.is_complete:
            raise RetriableIngestionError(
                f"the index of {version_id!r} does not match the chunks written to the "
                f"authority store: expected {report.expected_count}, found "
                f"{report.present_count}, missing {len(report.missing_ids)}"
            )
        if report.dimension is None or report.dimension <= 0:
            raise RetriableIngestionError(
                f"generation {report.generation!r} reports no usable vector dimension"
            )

    # --- 嵌入 ---

    def _embed_indexable(self, state: _PipelineState) -> tuple[tuple[VectorRecord, ...], str]:
        """把子块嵌成向量记录，并给出它们所属的索引代。

        父块不进来（规格 8）：它只用来展开上下文，不参与向量召回。
        """
        chunks = self._indexable_chunks(state.version.document_version_id)
        if not chunks:
            raise UnrecoverableIngestionError(
                f"document version {state.version.document_version_id!r} produced no "
                f"indexable chunk"
            )
        vectors, provider, model_version, dimension = self._vectors_for(chunks)
        state.provider = provider
        state.model_version = model_version
        generation = generation_for(
            state.version,
            provider=provider,
            model_version=model_version,
            dimension=dimension,
        )
        records = tuple(
            self._record(state, chunk, vector)
            for chunk, vector in zip(chunks, vectors, strict=True)
        )
        return records, generation

    def _indexable_chunks(self, version_id: str) -> tuple[ResearchChunk, ...]:
        total = self._repository.count_chunks(version_id)
        # 显式要全部：`list_chunks` 的默认上限是 500，更长的文档会被静默截断，而 `verify`
        # 会对着被截断的那一批说"齐了"。
        stored = self._repository.list_chunks(version_id, limit=max(total, 1))
        if len(stored) != total:
            raise UnrecoverableIngestionError(
                f"document version {version_id!r} reports {total} chunks but only "
                f"{len(stored)} could be read back"
            )
        return tuple(chunk for chunk in stored if chunk.parent_chunk_id is not None)

    def _indexable_ids(self, version_id: str) -> frozenset[str]:
        return frozenset(chunk.chunk_id for chunk in self._indexable_chunks(version_id))

    def _vectors_for(
        self, chunks: Sequence[ResearchChunk]
    ) -> tuple[tuple[tuple[float, ...], ...], str, str, int]:
        vectors: list[tuple[float, ...]] = []
        provider: str | None = None
        model_version: str | None = None
        dimension: int | None = None
        for start in range(0, len(chunks), self._batch_size):
            batch = self._embedding.embed(
                [chunk.content for chunk in chunks[start : start + self._batch_size]]
            )
            if dimension is None:
                provider, model_version, dimension = (
                    batch.provider,
                    batch.model_version,
                    batch.dimension,
                )
            elif (batch.provider, batch.model_version, batch.dimension) != (
                provider,
                model_version,
                dimension,
            ):
                # 两个批次落在不同的向量空间里，"同一个索引"就没有意义了。
                raise UnrecoverableIngestionError(
                    f"the embedding provider changed its identity mid-document: "
                    f"{provider}/{model_version}/{dimension} then "
                    f"{batch.provider}/{batch.model_version}/{batch.dimension}"
                )
            vectors.extend(batch.vectors)
        assert provider is not None and model_version is not None and dimension is not None
        if len(vectors) != len(chunks):
            raise UnrecoverableIngestionError(
                f"the embedding provider returned {len(vectors)} vectors for {len(chunks)} chunks"
            )
        return tuple(vectors), provider, model_version, dimension

    @staticmethod
    def _record(
        state: _PipelineState, chunk: ResearchChunk, vector: tuple[float, ...]
    ) -> VectorRecord:
        document = state.document
        return VectorRecord(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            document_version_id=chunk.document_version_id,
            parent_chunk_id=chunk.parent_chunk_id,
            chunk_type=chunk.chunk_type,
            document_type=document.document_type,
            institution=document.institution,
            # 上传时登记的发布日期优先，没有就用生效起始时间；两者都没有时 `_settle_published_at`
            # 早在第一段之前就补上了，因此这里读到的一定是权威库里的那一列。
            published_at=state.version.published_at or state.version.effective_from,
            effective_from=_day(state.version.effective_from),
            effective_to=_day(state.version.effective_to),
            source_weight=float(document.source_weight),
            content_origin=chunk.content_origin,
            confidence=chunk.confidence,
            requires_verification=chunk.requires_verification,
            content=chunk.content,
            dense_vector=vector,
        )

    # --- 落库与失败 ---

    def _persist(
        self,
        job: IngestionJob,
        target: IngestionStatus,
        *,
        worker_id: str,
        now: datetime,
        reason: str | None = None,
    ) -> IngestionJob:
        moved = transition_ingestion(job, target, now, worker_id, job.attempt_id, reason=reason)
        return self._repository.save_ingestion_job(
            moved, expected_status=job.status, expected_attempt=job.attempt_id
        )

    def _record_failure(
        self, job: IngestionJob, error: BaseException, *, worker_id: str, now: datetime
    ) -> IngestionJob:
        status = classify_failure(error)
        reason = f"{type(error).__name__}: {error}"
        if status is IngestionStatus.RETRYABLE_FAILED and job.attempt_id >= job.max_attempts:
            # 用尽次数的任务留在可重试状态，只会让它在队列里永远转圈。
            status = IngestionStatus.PERMANENT_FAILED
            reason = f"no attempt left after {job.max_attempts}: {reason}"
        try:
            return self._persist(job, status, worker_id=worker_id, now=now, reason=reason)
        except (ResearchLibraryConflict, InvalidIngestionTransition) as write_error:
            return self._current_state(job.job_id, write_error)

    def _current_state(self, job_id: str, error: BaseException) -> IngestionJob:
        current = self._repository.get_ingestion_job(job_id)
        if current is None:
            raise error
        return current

    def _latest(self, job: IngestionJob) -> IngestionJob:
        """权威库里的当前样子。失败分类必须基于它，而不是本次尝试开始时的快照。"""
        current = self._repository.get_ingestion_job(job.job_id)
        return job if current is None else current


def _day(moment: datetime | None) -> date | None:
    return None if moment is None else moment.date()
