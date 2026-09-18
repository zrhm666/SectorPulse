"""真实资源上的资料库装配，Task 20 的 Step 5 与 Step 6 共用。

这里装的是**生产那一套**：PostgreSQL 权威库、MinIO 对象存储、Milvus 派生索引，加上 HTTP 上的
真实 Provider。它之所以在测试目录里，是因为仓库还没有生产装配器（E138）：Task 18 的 Files
清单里没有它，而 Task 20 的 Step 6 必须跑通一次真实链路。与其让端到端测试自己拼一遍，不如把
拼法放在这里——两处各拼一次的后果，是"冒烟测试连的那个端点"与"端到端连的那个端点"会慢慢
变成两个不同的东西，而没有任何一条测试会发现这件事。

三条规则写在这里，因为它们对两个调用方都必须同时成立：

1. **资源名必须以 `_test` 或 `-test` 结尾**，判定由 `dedicated_resources` 做，且发生在客户端
   存在之前；一个不是测试资源的 bucket 只可能是生产数据。
2. **可选的 SDK 缺失是 skip 而不是 fail**：`minio` 与 `pymilvus` 属于 `rag` extra。
3. **Provider 端点没有配置就不跑**，并在原因里点名缺的是哪个环境变量。

**已知的接线缺口（与 E138 同一条）：** 每类 Provider 的端点参数（base URL 与 key）在配置层
还没有归属，这里取仓库里唯一那处已配置的 OpenAI 兼容端点
（`SECTOR_PULSE_LLM_BASE_URL` / `SECTOR_PULSE_LLM_API_KEY`）；模型与 provider 名则读
`SECTOR_PULSE_RAG_<KIND>_PROVIDER` / `_MODEL`，那是 `load_rag_settings` 真的会读的键。
装配器落地时端点应当有自己的键，届时这里跟着改。
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import SecretStr
from sector_pulse.application.research_library.cache import CorpusGeneration
from sector_pulse.application.research_library.chunking import StructuralChunker
from sector_pulse.application.research_library.indexing import IndexOutboxWorker
from sector_pulse.application.research_library.ingestion import ResearchIngestionCoordinator
from sector_pulse.application.research_library.observability import MetricsRegistry
from sector_pulse.application.research_library.retrieval import ResearchRetrievalService
from sector_pulse.application.research_library.services import ResearchLibraryServices
from sector_pulse.config.rag_settings import PROVIDER_ENV_PREFIXES, RagSettings, load_rag_settings
from sector_pulse.infrastructure.research_library.assets.scanner import build_scanner
from sector_pulse.infrastructure.research_library.parsing import build_parse_pipeline
from sector_pulse.infrastructure.research_library.providers.openai_compatible import (
    OpenAICompatibleEmbeddingProvider,
    OpenAICompatibleNliProvider,
    OpenAICompatibleOcrProvider,
    OpenAICompatibleRerankerProvider,
    OpenAICompatibleVisionDocumentProvider,
    ProviderEndpoint,
)
from sector_pulse.ports.research_assets import DEFAULT_MAX_ASSET_BYTES
from sector_pulse.ports.research_models import (
    EmbeddingProvider,
    NliProvider,
    OcrProvider,
    RerankerProvider,
    VisionDocumentProvider,
)

from backend.tests.dedicated_resources import dedicated_resource_name

#: 每类 Provider 的每调用超时与重试上限的缺省值。真实 Provider 慢，缺省给得比离线夹具宽。
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_RETRIES = 2

POSTGRES_VARIABLE = "SECTOR_PULSE_DATABASE_URL"
BUCKET_VARIABLE = "SECTOR_PULSE_RAG_MINIO_BUCKET"
COLLECTION_VARIABLE = "SECTOR_PULSE_RAG_MILVUS_COLLECTION"


def require_module(module: str) -> None:
    """缺 SDK 是前提缺失（skip），不是实现坏了（fail）。"""
    if importlib.util.find_spec(module) is None:
        pytest.skip(f"the {module} SDK is not installed; install the 'rag' extra")


def endpoint_for(kind: str) -> ProviderEndpoint:
    """按 `<KIND>` 的前缀装配一个端点；缺配置就跳过，并点名缺的是哪个键。"""
    prefix = PROVIDER_ENV_PREFIXES[kind]
    provider = os.environ.get(f"{prefix}_PROVIDER")
    model = os.environ.get(f"{prefix}_MODEL")
    base_url = os.environ.get("SECTOR_PULSE_LLM_BASE_URL")
    if not provider or not model or not base_url:
        pytest.skip(
            f"a real {kind} provider needs {prefix}_PROVIDER, {prefix}_MODEL and "
            "SECTOR_PULSE_LLM_BASE_URL"
        )
    api_key = os.environ.get("SECTOR_PULSE_LLM_API_KEY")
    return ProviderEndpoint(
        base_url=base_url,
        api_key=SecretStr(api_key) if api_key else None,
        model=model,
        provider=provider,
        # 逐次超时按该 Provider 自己的配置走：Embedding 是批量高并发，NLI 是单次调用，
        # 共用一个数字会掩盖成本异常。
        timeout_seconds=float(
            os.environ.get(f"{prefix}_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
        ),
        max_retries=int(os.environ.get(f"{prefix}_MAX_RETRIES", str(DEFAULT_MAX_RETRIES))),
    )


@dataclass(frozen=True)
class LiveProviders:
    embedding: EmbeddingProvider
    reranker: RerankerProvider
    nli: NliProvider
    ocr: OcrProvider | None
    vision: VisionDocumentProvider | None


def live_providers() -> LiveProviders:
    """四类必配 Provider 加两类可选 Provider。

    OCR 与 Vision 保持可选，与 `MANDATORY_PROVIDERS` 一致：它们只在页面需要时才被调用，
    没有它们的部署照样能跑；只是那种部署读不了扫描页，这一点由解析流水线记进 warning。
    """

    def optional(kind: str) -> ProviderEndpoint | None:
        prefix = PROVIDER_ENV_PREFIXES[kind]
        if not os.environ.get(f"{prefix}_PROVIDER") or not os.environ.get(f"{prefix}_MODEL"):
            return None
        return endpoint_for(kind)

    ocr_endpoint = optional("ocr")
    vision_endpoint = optional("vision")
    return LiveProviders(
        embedding=OpenAICompatibleEmbeddingProvider(endpoint_for("embedding")),
        reranker=OpenAICompatibleRerankerProvider(endpoint_for("reranker")),
        nli=OpenAICompatibleNliProvider(endpoint_for("nli")),
        ocr=OpenAICompatibleOcrProvider(ocr_endpoint) if ocr_endpoint else None,
        vision=(
            OpenAICompatibleVisionDocumentProvider(vision_endpoint) if vision_endpoint else None
        ),
    )


def require_live_rag_settings() -> RagSettings:
    """RAG 真的开着，而且四类必配 Provider 与维度都在。"""
    settings = load_rag_settings()
    if not settings.enabled:
        pytest.skip("SECTOR_PULSE_RAG_ENABLED is not true")
    if settings.embedding_dimension is None:
        pytest.skip("SECTOR_PULSE_RAG_EMBEDDING_DIMENSION is unset")
    return settings


def dedicated_names() -> tuple[str, str, str]:
    """三个专用资源名，逐个判定：缺配置是 skip，名字不对是拒绝（fail）。"""
    return (
        dedicated_resource_name(
            kind="PostgreSQL test database", variable=POSTGRES_VARIABLE, suffixes=("_test",)
        ),
        dedicated_resource_name(
            kind="MinIO test bucket", variable=BUCKET_VARIABLE, suffixes=("-test",)
        ),
        dedicated_resource_name(
            kind="Milvus test collection",
            variable=COLLECTION_VARIABLE,
            suffixes=("_test", "-test"),
        ),
    )


def build_live_library(
    settings: RagSettings, *, database: Any, providers: LiveProviders | None = None
) -> ResearchLibraryServices:
    """按生产那一套装配资料库：PostgreSQL 权威、MinIO 归档原件、Milvus 派生索引。

    调用前必须已经通过 `dedicated_names()` 的判定：这里的 bucket 与 collection 是**被写入**
    的，而拒绝必须发生在连接之前，所以判定不属于这个函数。
    """
    from sector_pulse.infrastructure.research_library.assets.minio import (
        MinioResearchAssetStore,
    )
    from sector_pulse.infrastructure.research_library.vector.milvus import MilvusVectorIndex
    from sector_pulse.storage.postgres.research_library.repository import (
        PostgresResearchLibraryRepository,
    )

    chosen = providers if providers is not None else live_providers()
    repository = PostgresResearchLibraryRepository(database)
    assets = MinioResearchAssetStore(
        endpoint=settings.minio_endpoint or "",
        access_key=(
            settings.minio_access_key.get_secret_value() if settings.minio_access_key else ""
        ),
        secret_key=(
            settings.minio_secret_key.get_secret_value() if settings.minio_secret_key else ""
        ),
        bucket=settings.minio_bucket or "",
        secure=settings.minio_secure,
        # 扫描器用生产那一份构造：`none` 是显式的 NOT_SCANNED，而不是"假定干净"。
        scanner=build_scanner(settings),
    )
    vector_index = MilvusVectorIndex(
        uri=settings.milvus_uri or "",
        token=(
            settings.milvus_token.get_secret_value() if settings.milvus_token is not None else None
        ),
        collection=settings.milvus_collection,
        dimension=settings.embedding_dimension or 0,
    )
    # 解析流水线只装一次：摄取与治理查询用的是同一份，两处各建一份会让"这一页读不读得出字"
    # 取决于问的是哪一条路径。
    parse_pipeline = build_parse_pipeline(ocr=chosen.ocr)
    outbox = IndexOutboxWorker(repository=repository, vector_index=vector_index)
    ingestion = ResearchIngestionCoordinator(
        repository=repository,
        assets=assets,
        parse_pipeline=parse_pipeline,
        chunker=StructuralChunker(),
        embedding=chosen.embedding,
        vector_index=vector_index,
        outbox=outbox,
    )

    def clock() -> datetime:
        """生产装配用的是墙上时钟；保留期与租约按真实时间走。"""
        return datetime.now(UTC)

    generation = CorpusGeneration(repository)
    retrieval = ResearchRetrievalService(
        repository=repository,
        vector_index=vector_index,
        embedding_provider=chosen.embedding,
        reranker=chosen.reranker,
        settings=settings,
        corpus_generation=generation,
        clock=clock,
    )
    return ResearchLibraryServices(
        repository=repository,
        assets=assets,
        vector_index=vector_index,
        settings=settings,
        parse_pipeline=parse_pipeline,
        ingestion=ingestion,
        outbox=outbox,
        embedding=chosen.embedding,
        retrieval=retrieval,
        corpus_generation=generation,
        clock=clock,
        metrics=MetricsRegistry(),
        max_upload_bytes=DEFAULT_MAX_ASSET_BYTES,
    )


__all__ = [
    "BUCKET_VARIABLE",
    "COLLECTION_VARIABLE",
    "LiveProviders",
    "POSTGRES_VARIABLE",
    "build_live_library",
    "dedicated_names",
    "endpoint_for",
    "live_providers",
    "require_live_rag_settings",
    "require_module",
]
