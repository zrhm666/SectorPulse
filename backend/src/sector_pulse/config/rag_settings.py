"""内部研究资料库 RAG 的运行时配置。

RAG 默认关闭；只有显式打开时，向量库、对象存储、模型 Provider 和权威
PostgreSQL 才成为必需项。所有错误信息都直接写出 `SECTOR_PULSE_RAG_*` 配置键，
运维可以照着改环境变量，不必阅读本模块。
"""

import os
from decimal import Decimal, InvalidOperation
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

VectorProvider = Literal["milvus"]
AssetProvider = Literal["minio"]
AssetScanner = Literal["none", "fixture"]
ChoiceT = TypeVar("ChoiceT", bound=str)

VECTOR_PROVIDERS: tuple[VectorProvider, ...] = ("milvus",)
ASSET_PROVIDERS: tuple[AssetProvider, ...] = ("minio",)
# `none` 明确表示“不扫描”，由上传质量门禁暴露 NOT_SCANNED，而不是假装文件干净。
ASSET_SCANNERS: tuple[AssetScanner, ...] = ("none", "fixture")

PROVIDER_ENV_PREFIXES: dict[str, str] = {
    "embedding": "SECTOR_PULSE_RAG_EMBEDDING",
    "reranker": "SECTOR_PULSE_RAG_RERANKER",
    "nli": "SECTOR_PULSE_RAG_NLI",
    "ocr": "SECTOR_PULSE_RAG_OCR",
    "vision": "SECTOR_PULSE_RAG_VISION",
    "claim_extractor": "SECTOR_PULSE_RAG_CLAIM_EXTRACTOR",
}

# OCR 与视觉解析只在页面需要时才调用，允许保持未配置。
MANDATORY_PROVIDERS = ("embedding", "reranker", "nli", "claim_extractor")

REQUIRED_ENDPOINT_KEYS = (
    "SECTOR_PULSE_RAG_MILVUS_URI",
    "SECTOR_PULSE_RAG_MINIO_ENDPOINT",
    "SECTOR_PULSE_RAG_MINIO_ACCESS_KEY",
    "SECTOR_PULSE_RAG_MINIO_SECRET_KEY",
    "SECTOR_PULSE_RAG_MINIO_BUCKET",
)


class ProviderLimits(BaseModel):
    """单个 Provider 的超时、重试、并发、批大小与预算。

    每类 Provider 独立配置，不共享一份全局上限：Embedding 是批量高并发，
    NLI 是单次调用且金额更高，混用同一个数字会掩盖成本异常。
    """

    model_config = ConfigDict(frozen=True)

    provider: str | None = Field(default=None, min_length=1)
    model: str | None = Field(default=None, min_length=1)
    timeout_seconds: float = Field(default=30.0, gt=0, le=600)
    max_retries: int = Field(default=2, ge=0, le=10)
    max_concurrency: int = Field(default=4, ge=1, le=32)
    batch_size: int = Field(default=32, ge=1, le=512)
    max_calls_per_run: int = Field(default=200, ge=1, le=100_000)
    reserve_cny_per_call: Decimal = Field(default=Decimal("0.0100"), ge=0)
    daily_budget_cny: Decimal = Field(default=Decimal("10.00"), gt=0)


class RagSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool = False

    vector_provider: Literal["milvus"] = "milvus"
    milvus_uri: str | None = Field(default=None, min_length=1)
    milvus_token: SecretStr | None = None
    milvus_collection: str = Field(default="internal_research_chunks_v1", min_length=1)
    milvus_alias: str | None = Field(default=None, min_length=1)

    asset_provider: Literal["minio"] = "minio"
    minio_endpoint: str | None = Field(default=None, min_length=1)
    minio_access_key: SecretStr | None = None
    minio_secret_key: SecretStr | None = None
    minio_bucket: str | None = Field(default=None, min_length=1)
    minio_secure: bool = True
    asset_scanner: Literal["none", "fixture"] = "none"

    embedding: ProviderLimits = Field(default_factory=ProviderLimits)
    #: 向量维度。Milvus 建集合时就要这个数，而它不能从 `EmbeddingProvider` 上读——
    #: 端口故意没有 `dimension` 属性，因为维度是每一批 embedding 自带的（同一部署换模型
    #: 是允许的），而集合的维度不是。既然唯一知道它的地方是配置，它就写在配置里。
    embedding_dimension: int | None = Field(default=None, ge=1, le=8192)
    reranker: ProviderLimits = Field(default_factory=ProviderLimits)
    nli: ProviderLimits = Field(default_factory=ProviderLimits)
    ocr: ProviderLimits = Field(default_factory=ProviderLimits)
    vision: ProviderLimits = Field(default_factory=ProviderLimits)
    claim_extractor: ProviderLimits = Field(default_factory=ProviderLimits)

    retention_days: int = Field(default=30, ge=1, le=3650)
    dense_top_k: int = Field(default=40, ge=1, le=1000)
    bm25_top_k: int = Field(default=40, ge=1, le=1000)
    fusion_top_k: int = Field(default=50, ge=1, le=2000)
    rerank_top_k: int = Field(default=12, ge=1, le=200)
    max_parent_expansion_chunks: int = Field(default=3, ge=1, le=20)
    #: 规格 11.3 "来源多样性控制"：单一文档最多贡献几条候选。省下来的名额给下一名，
    #: 不是让结果变短——否则一份文档只要开头足够像问题，就能占满整个 Top-N。
    max_candidates_per_document: int = Field(default=4, ge=1, le=100)
    #: 规格 11.3 "相同文档和章节的高度重叠 chunk 合并或限额"：同一版本、同一章节内，
    #: 较短一段的内容有多大比例被较长一段覆盖时判为重复。用覆盖率而不是 Jaccard，
    #: 是因为要抓的是"一句话被切两次"，那是包含关系，不是相似关系。
    duplicate_overlap_ratio: float = Field(default=0.8, gt=0, le=1)
    #: 规格 15.2 "返回有界的候选证据摘要"：交给 A2 的每段候选正文上限。
    max_candidate_text_chars: int = Field(default=800, ge=1, le=20_000)
    #: 规格 15.2 "返回受长度限制的原文片段"：查看原文时返回的原文上限。
    max_inspected_chars: int = Field(default=1500, ge=1, le=100_000)

    min_nli_confidence: float = Field(default=0.7, gt=0, le=1)
    min_claim_confidence: float = Field(default=0.5, ge=0, le=1)
    min_ocr_confidence: float = Field(default=0.6, ge=0, le=1)
    min_vision_confidence: float = Field(default=0.6, ge=0, le=1)

    @model_validator(mode="after")
    def _require_complete_runtime(self) -> "RagSettings":
        if not self.enabled:
            return self
        for name in REQUIRED_ENDPOINT_KEYS:
            if self._endpoint_value(name) is None:
                raise ValueError(f"{name} must be configured when RAG is enabled")
        for key in MANDATORY_PROVIDERS:
            limits = getattr(self, key)
            prefix = PROVIDER_ENV_PREFIXES[key]
            if limits.provider is None:
                raise ValueError(f"{prefix}_PROVIDER must be configured when RAG is enabled")
            if limits.model is None:
                raise ValueError(f"{prefix}_MODEL must be configured when RAG is enabled")
        if self.embedding_dimension is None:
            # 缺了它，集合建不出来；而这种失败会发生在第一次检索或第一次索引时，
            # 那时运维正在看的是一份上传失败的报告，不是一份配置报告。
            raise ValueError(
                "SECTOR_PULSE_RAG_EMBEDDING_DIMENSION must be configured when RAG is enabled"
            )
        return self

    def _endpoint_value(self, name: str) -> object | None:
        # CLAIM: Milvus collection 与 Milvus alias 都有规格默认值，永远非空，
        # 因此不参与“启用时必需”检查，否则只是永远为真的死分支。
        return {
            "SECTOR_PULSE_RAG_MILVUS_URI": self.milvus_uri,
            "SECTOR_PULSE_RAG_MINIO_ENDPOINT": self.minio_endpoint,
            "SECTOR_PULSE_RAG_MINIO_ACCESS_KEY": self.minio_access_key,
            "SECTOR_PULSE_RAG_MINIO_SECRET_KEY": self.minio_secret_key,
            "SECTOR_PULSE_RAG_MINIO_BUCKET": self.minio_bucket,
        }[name]

    @model_validator(mode="after")
    def _keep_retrieval_windows_ordered(self) -> "RagSettings":
        if self.fusion_top_k > self.dense_top_k + self.bm25_top_k:
            raise ValueError(
                "SECTOR_PULSE_RAG_FUSION_TOP_K cannot exceed "
                "SECTOR_PULSE_RAG_DENSE_TOP_K + SECTOR_PULSE_RAG_BM25_TOP_K"
            )
        if self.rerank_top_k > self.fusion_top_k:
            raise ValueError(
                "SECTOR_PULSE_RAG_RERANK_TOP_K must not exceed SECTOR_PULSE_RAG_FUSION_TOP_K"
            )
        return self


class _Environment:
    """读取环境变量，把空字符串视为未配置。"""

    @staticmethod
    def raw(name: str) -> str | None:
        value = os.environ.get(name)
        return value if value else None

    def text(self, name: str) -> str | None:
        return self.raw(name)

    def boolean(self, name: str, default: bool) -> bool:
        raw = self.raw(name)
        if raw is None:
            return default
        if raw.lower() not in {"true", "false"}:
            raise ValueError(f"{name} must be true or false")
        return raw.lower() == "true"

    def integer(self, name: str, default: int) -> int:
        raw = self.raw(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError as exc:
            raise ValueError(f"{name} must be an integer") from exc

    def optional_integer(self, name: str) -> int | None:
        """整数，但"没配"是一个合法的取值（维度只有在 RAG 打开时才是必需的）。"""
        raw = self.raw(name)
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError as exc:
            raise ValueError(f"{name} must be an integer") from exc

    def number(self, name: str, default: float) -> float:
        raw = self.raw(name)
        if raw is None:
            return default
        try:
            return float(raw)
        except ValueError as exc:
            raise ValueError(f"{name} must be a number") from exc

    def money(self, name: str, default: Decimal) -> Decimal:
        raw = self.raw(name)
        if raw is None:
            return default
        try:
            return Decimal(raw)
        except InvalidOperation as exc:
            raise ValueError(f"{name} must be a decimal amount") from exc

    def choice(self, name: str, allowed: tuple[ChoiceT, ...], default: ChoiceT) -> ChoiceT:
        raw = self.raw(name)
        if raw is None:
            return default
        if raw not in allowed:
            raise ValueError(f"{name} must be one of {', '.join(allowed)}")
        return raw

    def secret(self, name: str) -> SecretStr | None:
        raw = self.raw(name)
        return SecretStr(raw) if raw is not None else None


def _provider_limits(environment: _Environment, key: str) -> ProviderLimits:
    prefix = PROVIDER_ENV_PREFIXES[key]
    return ProviderLimits(
        provider=environment.text(f"{prefix}_PROVIDER"),
        model=environment.text(f"{prefix}_MODEL"),
        timeout_seconds=environment.number(f"{prefix}_TIMEOUT_SECONDS", 30.0),
        max_retries=environment.integer(f"{prefix}_MAX_RETRIES", 2),
        max_concurrency=environment.integer(f"{prefix}_MAX_CONCURRENCY", 4),
        batch_size=environment.integer(f"{prefix}_BATCH_SIZE", 32),
        max_calls_per_run=environment.integer(f"{prefix}_MAX_CALLS_PER_RUN", 200),
        reserve_cny_per_call=environment.money(
            f"{prefix}_RESERVE_CNY_PER_CALL", Decimal("0.0100")
        ),
        daily_budget_cny=environment.money(f"{prefix}_DAILY_BUDGET_CNY", Decimal("10.00")),
    )


def load_rag_settings(environment: _Environment | None = None) -> RagSettings:
    env = environment if environment is not None else _Environment()
    return RagSettings(
        enabled=env.boolean("SECTOR_PULSE_RAG_ENABLED", False),
        vector_provider=env.choice("SECTOR_PULSE_RAG_VECTOR_PROVIDER", VECTOR_PROVIDERS, "milvus"),
        milvus_uri=env.text("SECTOR_PULSE_RAG_MILVUS_URI"),
        milvus_token=env.secret("SECTOR_PULSE_RAG_MILVUS_TOKEN"),
        milvus_collection=env.text("SECTOR_PULSE_RAG_MILVUS_COLLECTION")
        or "internal_research_chunks_v1",
        milvus_alias=env.text("SECTOR_PULSE_RAG_MILVUS_ALIAS"),
        asset_provider=env.choice("SECTOR_PULSE_RAG_ASSET_PROVIDER", ASSET_PROVIDERS, "minio"),
        minio_endpoint=env.text("SECTOR_PULSE_RAG_MINIO_ENDPOINT"),
        minio_access_key=env.secret("SECTOR_PULSE_RAG_MINIO_ACCESS_KEY"),
        minio_secret_key=env.secret("SECTOR_PULSE_RAG_MINIO_SECRET_KEY"),
        minio_bucket=env.text("SECTOR_PULSE_RAG_MINIO_BUCKET"),
        minio_secure=env.boolean("SECTOR_PULSE_RAG_MINIO_SECURE", True),
        asset_scanner=env.choice("SECTOR_PULSE_RAG_ASSET_SCANNER", ASSET_SCANNERS, "none"),
        embedding=_provider_limits(env, "embedding"),
        embedding_dimension=env.optional_integer("SECTOR_PULSE_RAG_EMBEDDING_DIMENSION"),
        reranker=_provider_limits(env, "reranker"),
        nli=_provider_limits(env, "nli"),
        ocr=_provider_limits(env, "ocr"),
        vision=_provider_limits(env, "vision"),
        claim_extractor=_provider_limits(env, "claim_extractor"),
        retention_days=env.integer("SECTOR_PULSE_RAG_RETENTION_DAYS", 30),
        dense_top_k=env.integer("SECTOR_PULSE_RAG_DENSE_TOP_K", 40),
        bm25_top_k=env.integer("SECTOR_PULSE_RAG_BM25_TOP_K", 40),
        fusion_top_k=env.integer("SECTOR_PULSE_RAG_FUSION_TOP_K", 50),
        rerank_top_k=env.integer("SECTOR_PULSE_RAG_RERANK_TOP_K", 12),
        max_parent_expansion_chunks=env.integer("SECTOR_PULSE_RAG_MAX_PARENT_EXPANSION", 3),
        max_candidates_per_document=env.integer(
            "SECTOR_PULSE_RAG_MAX_CANDIDATES_PER_DOCUMENT", 4
        ),
        duplicate_overlap_ratio=env.number("SECTOR_PULSE_RAG_DUPLICATE_OVERLAP_RATIO", 0.8),
        max_candidate_text_chars=env.integer(
            "SECTOR_PULSE_RAG_MAX_CANDIDATE_TEXT_CHARS", 800
        ),
        max_inspected_chars=env.integer("SECTOR_PULSE_RAG_MAX_INSPECTED_CHARS", 1500),
        min_nli_confidence=env.number("SECTOR_PULSE_RAG_MIN_NLI_CONFIDENCE", 0.7),
        min_claim_confidence=env.number("SECTOR_PULSE_RAG_MIN_CLAIM_CONFIDENCE", 0.5),
        min_ocr_confidence=env.number("SECTOR_PULSE_RAG_MIN_OCR_CONFIDENCE", 0.6),
        min_vision_confidence=env.number("SECTOR_PULSE_RAG_MIN_VISION_CONFIDENCE", 0.6),
    )
