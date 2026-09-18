"""一条离线可跑的资料库装配，供 API 与维护接口的测试使用。

与 `test_research_ingestion_pipeline.py` 里那个 `_Harness` 的关系是刻意的：那个夹具测的是
摄取流水线内部的性质，因此自己在内存里摆好文档、版本与任务；这里搭的是**接线层**那一份
`ResearchLibraryServices`——命令、查询、维护三件服务共用同一组假存储，唯一的不同是权威库、
对象存储与向量索引都是内存实现。API 测试要验的是"端点与命令之间的那层翻译"，因此它需要
的正是真实接线对象，而不是它的替身。

`MutableClock` 是这份装配里唯一不是"照搬生产实现"的部分：保留期、租约、认领过期全都以
时间为输入，用墙上时钟测这些就等于让测试在边界上偶发失败。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sector_pulse.application.research_library.cache import CorpusGeneration
from sector_pulse.application.research_library.chunking import ChunkingPolicy, StructuralChunker
from sector_pulse.application.research_library.indexing import IndexOutboxWorker
from sector_pulse.application.research_library.ingestion import ResearchIngestionCoordinator
from sector_pulse.application.research_library.observability import MetricsRegistry
from sector_pulse.application.research_library.parsing import ResearchParsePipeline
from sector_pulse.application.research_library.retrieval import ResearchRetrievalService
from sector_pulse.application.research_library.services import ResearchLibraryServices
from sector_pulse.config.rag_settings import RagSettings
from sector_pulse.infrastructure.research_library.assets.memory import (
    InMemoryResearchAssetStore,
)
from sector_pulse.infrastructure.research_library.assets.scanner import (
    ContentMarkerScanner,
    NullScanner,
)
from sector_pulse.infrastructure.research_library.parsing import build_parse_pipeline
from sector_pulse.infrastructure.research_library.providers.fixture import (
    FixtureEmbeddingProvider,
    FixtureRerankerProvider,
)
from sector_pulse.infrastructure.research_library.vector.memory import InMemoryVectorIndex
from sector_pulse.ports.research_assets import DEFAULT_MAX_ASSET_BYTES, FileSafetyScanner
from sector_pulse.ports.research_models import EmbeddingProvider, RerankerProvider

from backend.tests.research_library_fakes import InMemoryResearchLibraryRepository

if TYPE_CHECKING:  # pragma: no cover - 只为类型
    from sector_pulse.application.research_library.commands import (
        ResearchLibraryCommands,
        ResearchLibraryQueries,
    )
    from sector_pulse.application.research_library.maintenance import (
        ResearchLibraryMaintenance,
    )

NOW = datetime(2026, 9, 18, 4, 0, tzinfo=UTC)

#: 与检索探针共用一个维度。换维度等于换向量空间，探针与被测链路必须一致。
EMBEDDING_DIMENSION = 32

#: 刻意调小的切片预算，理由与 `test_research_ingestion_pipeline.py` 相同：默认预算会把
#: 一份测试正文整篇装进一个子块，"少一条/多一条向量"这类情形就没有发生的余地。
TEST_POLICY = ChunkingPolicy(
    child_min_tokens=20,
    child_target_tokens=30,
    child_soft_cap_tokens=60,
    child_overlap_tokens=5,
    parent_target_tokens=120,
    parent_max_tokens=240,
)

#: 上传门禁测试用的上限。小到"多写一个字节就超限"，大到足够装下一份正常正文。
SMALL_UPLOAD_LIMIT = 4096


@dataclass
class MutableClock:
    """可推进的时钟。默认停在 `NOW`，测试自己决定时间往哪走。"""

    now: datetime = NOW

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float = 0, **kwargs: float) -> datetime:
        self.now = self.now + timedelta(seconds=seconds, **kwargs)
        return self.now


@dataclass
class ResearchLibraryStack:
    """一组共享存储的服务对象，以及便于断言的那几个存储本身。"""

    repository: InMemoryResearchLibraryRepository
    assets: InMemoryResearchAssetStore
    vector_index: InMemoryVectorIndex
    embedding: EmbeddingProvider
    clock: MutableClock
    metrics: MetricsRegistry
    services: ResearchLibraryServices

    @property
    def commands(self) -> ResearchLibraryCommands:
        return self.services.commands

    @property
    def queries(self) -> ResearchLibraryQueries:
        return self.services.queries

    @property
    def maintenance(self) -> ResearchLibraryMaintenance:
        return self.services.maintenance


def build_research_library_stack(
    *,
    scanner: FileSafetyScanner | None = None,
    max_upload_bytes: int = DEFAULT_MAX_ASSET_BYTES,
    settings: RagSettings | None = None,
    clock: MutableClock | None = None,
    embedding: EmbeddingProvider | None = None,
    reranker: RerankerProvider | None = None,
    corpus_scan_limit: int = 100,
    parse_pipeline: ResearchParsePipeline | None = None,
) -> ResearchLibraryStack:
    """装配一条离线的资料库链路。

    默认扫描器是 `ContentMarkerScanner`，而**不是**生产默认的 `NullScanner`：上传路径上
    有一条"被判定为恶意"的分支，用 `NullScanner` 永远走不到它，那条分支就会在离线套件里
    一直是绿的，直到第一次接上真实扫描器。

    `parse_pipeline` 默认是 `build_parse_pipeline()` 的那一套（PDF/Markdown/TXT、无 OCR）。
    传一个带 OCR 的流水线进来，是为了让扫描页真的读得出字：没有它就测不到"OCR 出来的
    内容一样能被检索到"，那条路径会在离线套件里一直缺席。
    """
    repository = InMemoryResearchLibraryRepository()
    chosen_scanner = scanner if scanner is not None else ContentMarkerScanner()
    assets = InMemoryResearchAssetStore(
        scanner=chosen_scanner, max_asset_bytes=DEFAULT_MAX_ASSET_BYTES
    )
    vector_index = InMemoryVectorIndex()
    chosen_embedding = (
        embedding
        if embedding is not None
        else FixtureEmbeddingProvider(dimension=EMBEDDING_DIMENSION)
    )
    chosen_reranker = reranker if reranker is not None else FixtureRerankerProvider()
    chosen_clock = clock if clock is not None else MutableClock()
    chosen_settings = settings if settings is not None else RagSettings()
    chosen_pipeline = parse_pipeline if parse_pipeline is not None else build_parse_pipeline()
    metrics = MetricsRegistry()

    outbox = IndexOutboxWorker(repository=repository, vector_index=vector_index)
    coordinator = ResearchIngestionCoordinator(
        repository=repository,
        assets=assets,
        parse_pipeline=chosen_pipeline,
        chunker=StructuralChunker(),
        embedding=chosen_embedding,
        vector_index=vector_index,
        outbox=outbox,
        chunking_policy=TEST_POLICY,
    )
    generation = CorpusGeneration(repository, scan_limit=corpus_scan_limit)
    retrieval = ResearchRetrievalService(
        repository=repository,
        vector_index=vector_index,
        embedding_provider=chosen_embedding,
        reranker=chosen_reranker,
        settings=chosen_settings,
        corpus_generation=generation,
        clock=chosen_clock,
    )
    services = ResearchLibraryServices(
        repository=repository,
        assets=assets,
        vector_index=vector_index,
        settings=chosen_settings,
        parse_pipeline=chosen_pipeline,
        ingestion=coordinator,
        outbox=outbox,
        embedding=chosen_embedding,
        retrieval=retrieval,
        corpus_generation=generation,
        clock=chosen_clock,
        metrics=metrics,
        max_upload_bytes=max_upload_bytes,
    )
    return ResearchLibraryStack(
        repository=repository,
        assets=assets,
        vector_index=vector_index,
        embedding=chosen_embedding,
        clock=chosen_clock,
        metrics=metrics,
        services=services,
    )


def null_scanner_stack(**kwargs) -> ResearchLibraryStack:
    """一个"没有接扫描器"的装配：结论是 NOT_SCANNED，而不是假定干净。"""
    return build_research_library_stack(scanner=NullScanner(), **kwargs)


#: 一份能被 `TextDocumentParser` 读出来、并且切得出多个子块的正文。
BODY = """储能行业 2026 年中期策略

需求侧

2026 年上半年全球储能新增装机同比增长四成。国内大储招标量创下历史新高。
海外需求同样强劲，欧洲与中东的订单占比明显提升。

供给侧

电芯价格继续下行，二线厂商的产能利用率承压。头部厂商的海外产能开始释放。
"""


__all__ = [
    "BODY",
    "EMBEDDING_DIMENSION",
    "MutableClock",
    "NOW",
    "ResearchLibraryStack",
    "SMALL_UPLOAD_LIMIT",
    "TEST_POLICY",
    "build_research_library_stack",
    "null_scanner_stack",
]
