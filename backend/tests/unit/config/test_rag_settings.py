"""RAG configuration contract.

RAG is disabled by default and must stay inert for existing SQLite runs. Enabling
it turns on a mandatory PostgreSQL/vector/asset/provider set, so every missing
piece has to fail at settings construction instead of at the first retrieval.
"""

import pytest
from sector_pulse.config.settings import ApplicationSettings

POSTGRES_URL = "postgresql+psycopg://sectorpulse:local-only@127.0.0.1:5432/sectorpulse_rag_test"

REQUIRED_ENV = {
    "SECTOR_PULSE_RAG_ENABLED": "true",
    "SECTOR_PULSE_DATABASE_URL": POSTGRES_URL,
    "SECTOR_PULSE_RAG_MILVUS_URI": "http://127.0.0.1:19530",
    "SECTOR_PULSE_RAG_MILVUS_COLLECTION": "internal_research_chunks_v1_test",
    "SECTOR_PULSE_RAG_MINIO_ENDPOINT": "127.0.0.1:9000",
    "SECTOR_PULSE_RAG_MINIO_ACCESS_KEY": "rag-test-access",
    "SECTOR_PULSE_RAG_MINIO_SECRET_KEY": "rag-test-secret",
    "SECTOR_PULSE_RAG_MINIO_BUCKET": "sectorpulse-rag-test",
    "SECTOR_PULSE_RAG_EMBEDDING_PROVIDER": "openai-compatible",
    "SECTOR_PULSE_RAG_EMBEDDING_MODEL": "text-embedding-fixture",
    "SECTOR_PULSE_RAG_EMBEDDING_DIMENSION": "1024",
    "SECTOR_PULSE_RAG_RERANKER_PROVIDER": "http-rerank",
    "SECTOR_PULSE_RAG_RERANKER_MODEL": "rerank-fixture",
    "SECTOR_PULSE_RAG_NLI_PROVIDER": "http-nli",
    "SECTOR_PULSE_RAG_NLI_MODEL": "nli-fixture",
    "SECTOR_PULSE_RAG_CLAIM_EXTRACTOR_PROVIDER": "openai-compatible",
    "SECTOR_PULSE_RAG_CLAIM_EXTRACTOR_MODEL": "claim-fixture",
}


def enable_rag(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    for name, raw in {**REQUIRED_ENV, **overrides}.items():
        monkeypatch.setenv(name, raw)


def without(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
    for name in names:
        monkeypatch.delenv(name, raising=False)


def test_rag_is_disabled_by_default(yaml_config, monkeypatch):
    without(monkeypatch, "SECTOR_PULSE_RAG_ENABLED")
    settings = ApplicationSettings.from_environment(yaml_config)
    assert settings.rag.enabled is False


def test_disabled_rag_requires_no_endpoint_or_secret(yaml_config, monkeypatch):
    without(
        monkeypatch,
        "SECTOR_PULSE_RAG_ENABLED",
        "SECTOR_PULSE_RAG_MILVUS_URI",
        "SECTOR_PULSE_RAG_MINIO_ENDPOINT",
        "SECTOR_PULSE_RAG_MINIO_SECRET_KEY",
        "SECTOR_PULSE_RAG_EMBEDDING_PROVIDER",
    )
    settings = ApplicationSettings.from_environment(yaml_config)
    assert settings.rag.enabled is False
    assert settings.rag.milvus_uri is None
    assert settings.rag.minio_secret_key is None


def test_enabled_rag_requires_postgres(yaml_config, monkeypatch):
    enable_rag(monkeypatch)
    monkeypatch.setenv("SECTOR_PULSE_DATABASE_PATH", "data/test.db")
    monkeypatch.setenv("SECTOR_PULSE_DATABASE_URL", "")
    with pytest.raises(ValueError, match="RAG requires PostgreSQL"):
        ApplicationSettings.from_environment(yaml_config)


def test_enabled_rag_rejects_sqlite_scheme_database_url(yaml_config, monkeypatch):
    enable_rag(monkeypatch, SECTOR_PULSE_DATABASE_URL="sqlite+pysqlite:///data/test.db")
    with pytest.raises(ValueError, match="RAG requires PostgreSQL"):
        ApplicationSettings.from_environment(yaml_config)


def test_enabled_rag_accepts_bare_postgresql_scheme(yaml_config, monkeypatch):
    """`resolve_database_config` already normalizes bare postgresql:// to psycopg.

    RAG must reuse that resolver instead of matching a literal URL prefix, or the
    documented `postgresql://user:pw@host/db` form would be rejected here while the
    rest of the application accepts it.
    """
    enable_rag(monkeypatch, SECTOR_PULSE_DATABASE_URL="postgresql://u:p@127.0.0.1:5432/db_test")
    settings = ApplicationSettings.from_environment(yaml_config)
    assert settings.rag.enabled is True


def test_enabled_rag_requires_vector_and_asset_endpoints(yaml_config, monkeypatch):
    enable_rag(monkeypatch)
    without(
        monkeypatch,
        "SECTOR_PULSE_RAG_MILVUS_URI",
        "SECTOR_PULSE_RAG_MINIO_ENDPOINT",
        "SECTOR_PULSE_RAG_MINIO_BUCKET",
    )
    with pytest.raises(ValueError, match="SECTOR_PULSE_RAG_MILVUS_URI"):
        ApplicationSettings.from_environment(yaml_config)


def test_enabled_rag_requires_asset_credentials(yaml_config, monkeypatch):
    enable_rag(monkeypatch)
    without(monkeypatch, "SECTOR_PULSE_RAG_MINIO_SECRET_KEY")
    with pytest.raises(ValueError, match="SECTOR_PULSE_RAG_MINIO_SECRET_KEY"):
        ApplicationSettings.from_environment(yaml_config)


@pytest.mark.parametrize(
    "missing",
    [
        "SECTOR_PULSE_RAG_EMBEDDING_MODEL",
        "SECTOR_PULSE_RAG_RERANKER_PROVIDER",
        "SECTOR_PULSE_RAG_NLI_MODEL",
        "SECTOR_PULSE_RAG_CLAIM_EXTRACTOR_PROVIDER",
    ],
)
def test_enabled_rag_requires_mandatory_provider_identity(yaml_config, monkeypatch, missing):
    enable_rag(monkeypatch)
    without(monkeypatch, missing)
    with pytest.raises(ValueError, match=missing):
        ApplicationSettings.from_environment(yaml_config)


def test_enabled_rag_requires_the_embedding_dimension(yaml_config, monkeypatch):
    """Milvus 建集合要先知道维度，而 `EmbeddingProvider` 端口不暴露它。

    端口上确实没有这个属性：维度是每一批 embedding 自带的，因为同一个部署里换模型是
    允许的，而集合的维度不是。因此它是配置项，而不是从端口上读来的东西。
    """
    enable_rag(monkeypatch)
    without(monkeypatch, "SECTOR_PULSE_RAG_EMBEDDING_DIMENSION")
    with pytest.raises(ValueError, match="SECTOR_PULSE_RAG_EMBEDDING_DIMENSION"):
        ApplicationSettings.from_environment(yaml_config)


def test_embedding_dimension_is_optional_while_rag_is_disabled(yaml_config, monkeypatch):
    without(monkeypatch, "SECTOR_PULSE_RAG_ENABLED", "SECTOR_PULSE_RAG_EMBEDDING_DIMENSION")
    settings = ApplicationSettings.from_environment(yaml_config)
    assert settings.rag.embedding_dimension is None


def test_rag_rejects_a_non_integer_embedding_dimension(yaml_config, monkeypatch):
    enable_rag(monkeypatch, SECTOR_PULSE_RAG_EMBEDDING_DIMENSION="big")
    with pytest.raises(ValueError, match="SECTOR_PULSE_RAG_EMBEDDING_DIMENSION"):
        ApplicationSettings.from_environment(yaml_config)


def test_ocr_and_vision_stay_optional_when_enabled(yaml_config, monkeypatch):
    enable_rag(monkeypatch)
    without(
        monkeypatch,
        "SECTOR_PULSE_RAG_OCR_PROVIDER",
        "SECTOR_PULSE_RAG_VISION_PROVIDER",
    )
    settings = ApplicationSettings.from_environment(yaml_config)
    assert settings.rag.ocr.provider is None
    assert settings.rag.vision.provider is None


def test_enabled_rag_reads_complete_configuration(yaml_config, monkeypatch):
    enable_rag(
        monkeypatch,
        SECTOR_PULSE_RAG_MILVUS_ALIAS="internal_research_current",
        SECTOR_PULSE_RAG_MINIO_SECURE="false",
        SECTOR_PULSE_RAG_RETENTION_DAYS="45",
        SECTOR_PULSE_RAG_DENSE_TOP_K="30",
        SECTOR_PULSE_RAG_BM25_TOP_K="35",
        SECTOR_PULSE_RAG_FUSION_TOP_K="44",
        SECTOR_PULSE_RAG_RERANK_TOP_K="9",
        SECTOR_PULSE_RAG_MIN_NLI_CONFIDENCE="0.8",
        SECTOR_PULSE_RAG_ASSET_SCANNER="none",
    )
    settings = ApplicationSettings.from_environment(yaml_config)
    rag = settings.rag

    assert rag.enabled is True
    assert rag.vector_provider == "milvus"
    assert rag.milvus_uri == "http://127.0.0.1:19530"
    assert rag.milvus_collection == "internal_research_chunks_v1_test"
    assert rag.milvus_alias == "internal_research_current"
    assert rag.asset_provider == "minio"
    assert rag.minio_endpoint == "127.0.0.1:9000"
    assert rag.minio_bucket == "sectorpulse-rag-test"
    assert rag.minio_secure is False
    assert rag.asset_scanner == "none"
    assert rag.embedding.provider == "openai-compatible"
    assert rag.embedding.model == "text-embedding-fixture"
    assert rag.embedding_dimension == 1024
    assert rag.reranker.model == "rerank-fixture"
    assert rag.nli.model == "nli-fixture"
    assert rag.claim_extractor.model == "claim-fixture"
    assert rag.retention_days == 45
    assert (rag.dense_top_k, rag.bm25_top_k, rag.fusion_top_k, rag.rerank_top_k) == (30, 35, 44, 9)
    assert rag.min_nli_confidence == pytest.approx(0.8)


def test_retrieval_limits_default_to_spec_section_11_values(yaml_config, monkeypatch):
    enable_rag(monkeypatch)
    rag = ApplicationSettings.from_environment(yaml_config).rag
    assert (rag.dense_top_k, rag.bm25_top_k, rag.fusion_top_k, rag.rerank_top_k) == (40, 40, 50, 12)
    assert rag.retention_days == 30


def test_provider_limits_are_independent(yaml_config, monkeypatch):
    enable_rag(
        monkeypatch,
        SECTOR_PULSE_RAG_EMBEDDING_BATCH_SIZE="64",
        SECTOR_PULSE_RAG_EMBEDDING_MAX_CONCURRENCY="8",
        SECTOR_PULSE_RAG_NLI_TIMEOUT_SECONDS="5.5",
        SECTOR_PULSE_RAG_NLI_MAX_CALLS_PER_RUN="25",
        SECTOR_PULSE_RAG_NLI_DAILY_BUDGET_CNY="2.50",
        SECTOR_PULSE_RAG_NLI_RESERVE_CNY_PER_CALL="0.0100",
        SECTOR_PULSE_RAG_OCR_MAX_RETRIES="0",
    )
    rag = ApplicationSettings.from_environment(yaml_config).rag

    assert rag.embedding.batch_size == 64
    assert rag.embedding.max_concurrency == 8
    assert rag.reranker.max_concurrency == 4
    assert rag.reranker.batch_size == 32
    assert rag.nli.timeout_seconds == pytest.approx(5.5)
    assert rag.nli.max_calls_per_run == 25
    assert str(rag.nli.daily_budget_cny) == "2.50"
    assert str(rag.nli.reserve_cny_per_call) == "0.0100"
    assert rag.ocr.max_retries == 0
    assert rag.vision.provider is None


def test_rag_secrets_are_never_dumped(yaml_config, monkeypatch):
    """Every RAG credential is a SecretStr, including the Milvus token.

    `ApplicationSettings.database_url` stays a plain string for now: it predates
    RAG and is read as a URL by `resolve_database_config` and the operations
    router. Narrowing it is a separate change, not part of the RAG settings task.
    """
    enable_rag(monkeypatch, SECTOR_PULSE_RAG_MILVUS_TOKEN="milvus-test-token")
    settings = ApplicationSettings.from_environment(yaml_config)
    dump = settings.model_dump_json()
    assert "rag-test-secret" not in dump
    assert "rag-test-access" not in dump
    assert "milvus-test-token" not in dump
    assert settings.rag.minio_secret_key is not None
    assert settings.rag.minio_secret_key.get_secret_value() == "rag-test-secret"


def test_rag_rejects_retrieval_window_inversion(yaml_config, monkeypatch):
    enable_rag(monkeypatch, SECTOR_PULSE_RAG_FUSION_TOP_K="5", SECTOR_PULSE_RAG_RERANK_TOP_K="12")
    with pytest.raises(ValueError, match="SECTOR_PULSE_RAG_RERANK_TOP_K"):
        ApplicationSettings.from_environment(yaml_config)


def test_rag_rejects_fusion_window_wider_than_the_recall_lists(yaml_config, monkeypatch):
    enable_rag(
        monkeypatch,
        SECTOR_PULSE_RAG_DENSE_TOP_K="10",
        SECTOR_PULSE_RAG_BM25_TOP_K="10",
        SECTOR_PULSE_RAG_FUSION_TOP_K="50",
        SECTOR_PULSE_RAG_RERANK_TOP_K="9",
    )
    with pytest.raises(ValueError, match="SECTOR_PULSE_RAG_FUSION_TOP_K"):
        ApplicationSettings.from_environment(yaml_config)


def test_rag_rejects_non_boolean_enabled(yaml_config, monkeypatch):
    enable_rag(monkeypatch, SECTOR_PULSE_RAG_ENABLED="yes")
    with pytest.raises(ValueError, match="SECTOR_PULSE_RAG_ENABLED"):
        ApplicationSettings.from_environment(yaml_config)


def test_rag_rejects_unknown_vector_provider(yaml_config, monkeypatch):
    enable_rag(monkeypatch, SECTOR_PULSE_RAG_VECTOR_PROVIDER="pinecone")
    with pytest.raises(ValueError, match="SECTOR_PULSE_RAG_VECTOR_PROVIDER"):
        ApplicationSettings.from_environment(yaml_config)


def test_rag_rejects_unknown_asset_provider(yaml_config, monkeypatch):
    enable_rag(monkeypatch, SECTOR_PULSE_RAG_ASSET_PROVIDER="s3")
    with pytest.raises(ValueError, match="SECTOR_PULSE_RAG_ASSET_PROVIDER"):
        ApplicationSettings.from_environment(yaml_config)


def test_rag_rejects_unknown_asset_scanner(yaml_config, monkeypatch):
    enable_rag(monkeypatch, SECTOR_PULSE_RAG_ASSET_SCANNER="trust-me")
    with pytest.raises(ValueError, match="SECTOR_PULSE_RAG_ASSET_SCANNER"):
        ApplicationSettings.from_environment(yaml_config)
