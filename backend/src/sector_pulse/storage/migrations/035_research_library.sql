-- 035: 内部研究资料库的权威表。
--
-- 规格 9/10：PostgreSQL 是唯一权威状态源。Milvus 只是可重建的派生索引，因此这里没有
-- 任何向量列；MinIO 只保存二进制，因此这里只保存对象键与校验和。
--
-- 本文件同时被 SQLite 应用（迁移编号必须连续），所以只使用双方言都接受的写法：
-- 时间戳为 TEXT，布尔为 INTEGER，JSON 载荷为 TEXT。PostgreSQL 专属的 JSONB 转换与
-- 附加索引放在 migrations/postgres/035_research_library.sql。
--
-- 本迁移在 Task 3 通过后即冻结：后续任务只能新增迁移，不能修改这里的语句。

CREATE TABLE IF NOT EXISTS research_documents (
    document_id TEXT PRIMARY KEY,
    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
    document_type TEXT NOT NULL
        CHECK (document_type IN ('report', 'historical_article', 'announcement', 'other')),
    author TEXT,
    institution TEXT,
    source_weight NUMERIC(4, 3) NOT NULL DEFAULT 0.500
        CHECK (source_weight >= 0 AND source_weight <= 1),
    -- 不加外键：当前版本与版本表互相引用，先建者必然悬空。完整性由
    -- activate_version 在同一事务里维护，并在 PostgreSQL 补充分支加唯一部分索引兜底。
    current_version_id TEXT,
    -- 第一版只有全局可见；取值受限使未来加范围时必须改迁移而不是改数据含义。
    visibility_scope TEXT NOT NULL DEFAULT 'GLOBAL' CHECK (visibility_scope IN ('GLOBAL')),
    owner_id TEXT,
    access_tags_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    deleted_at TEXT,
    purge_after TEXT,
    CHECK (purge_after IS NULL OR deleted_at IS NOT NULL),
    CHECK (purge_after IS NULL OR purge_after > deleted_at)
);

CREATE INDEX IF NOT EXISTS idx_research_documents_type_created
    ON research_documents (document_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_research_documents_purge_after
    ON research_documents (purge_after);

CREATE TABLE IF NOT EXISTS research_document_versions (
    document_version_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL
        REFERENCES research_documents (document_id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL CHECK (version_number >= 1),
    status TEXT NOT NULL CHECK (status IN (
        'PROCESSING', 'ACTIVE', 'SUPERSEDED', 'ARCHIVED', 'FAILED', 'DELETED', 'PURGED'
    )),
    -- 上传幂等键：同一个键配合同一个文件散列只允许产生一个版本。
    upload_key TEXT CHECK (upload_key IS NULL OR length(trim(upload_key)) > 0),
    published_at TEXT,
    effective_from TEXT,
    effective_to TEXT,
    uploaded_at TEXT NOT NULL,
    original_file_hash TEXT NOT NULL CHECK (length(trim(original_file_hash)) > 0),
    parser_version TEXT,
    chunking_policy_version TEXT,
    ocr_provider TEXT,
    ocr_model_version TEXT,
    embedding_provider TEXT,
    embedding_model_version TEXT,
    index_generation TEXT,
    expected_chunk_count INTEGER CHECK (expected_chunk_count IS NULL OR expected_chunk_count >= 0),
    indexed_at TEXT,
    UNIQUE (document_id, version_number),
    CHECK (effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from),
    -- 规格 10：ACTIVE 必须记录它来自哪一代索引，否则可见性无法与索引核对。
    CHECK (
        status <> 'ACTIVE'
        OR (index_generation IS NOT NULL AND indexed_at IS NOT NULL
            AND expected_chunk_count IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_research_versions_upload_key
    ON research_document_versions (upload_key, original_file_hash)
    WHERE upload_key IS NOT NULL;
-- 一个文档任何时刻只能有一个 ACTIVE 版本；由数据库而不是调用方保证。
CREATE UNIQUE INDEX IF NOT EXISTS idx_research_versions_single_active
    ON research_document_versions (document_id) WHERE status = 'ACTIVE';
CREATE INDEX IF NOT EXISTS idx_research_versions_document
    ON research_document_versions (document_id, version_number DESC);
CREATE INDEX IF NOT EXISTS idx_research_versions_status
    ON research_document_versions (status);
CREATE INDEX IF NOT EXISTS idx_research_versions_generation
    ON research_document_versions (index_generation);

CREATE TABLE IF NOT EXISTS research_document_assets (
    asset_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL
        REFERENCES research_documents (document_id) ON DELETE CASCADE,
    document_version_id TEXT
        REFERENCES research_document_versions (document_version_id) ON DELETE CASCADE,
    asset_role TEXT NOT NULL
        CHECK (asset_role IN ('original', 'page_image', 'extracted_table', 'chart_image')),
    object_key TEXT NOT NULL UNIQUE,
    content_type TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    sha256 TEXT NOT NULL CHECK (length(trim(sha256)) > 0),
    page_number INTEGER CHECK (page_number IS NULL OR page_number >= 1),
    -- Task 4：未接入扫描器时如实记录 NOT_SCANNED，而不是默认宣称文件干净。
    scan_status TEXT NOT NULL DEFAULT 'NOT_SCANNED'
        CHECK (scan_status IN ('NOT_SCANNED', 'CLEAN', 'INFECTED', 'FAILED')),
    scan_detail TEXT,
    created_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_research_assets_version
    ON research_document_assets (document_version_id, asset_role);

CREATE TABLE IF NOT EXISTS research_chunks (
    chunk_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL
        REFERENCES research_documents (document_id) ON DELETE CASCADE,
    document_version_id TEXT NOT NULL
        REFERENCES research_document_versions (document_version_id) ON DELETE CASCADE,
    parent_chunk_id TEXT REFERENCES research_chunks (chunk_id) ON DELETE SET NULL,
    chunk_order INTEGER NOT NULL CHECK (chunk_order >= 0),
    chunk_type TEXT NOT NULL
        CHECK (chunk_type IN ('text', 'table', 'code', 'formula', 'chart', 'image_caption')),
    content TEXT NOT NULL CHECK (length(trim(content)) > 0),
    content_hash TEXT NOT NULL,
    -- 规格 12：切片必须保留回原文件的定位信息，因此这里不允许为空。
    source_json TEXT NOT NULL,
    content_origin TEXT NOT NULL
        CHECK (content_origin IN ('native', 'ocr', 'parser_derived', 'vision_derived')),
    confidence NUMERIC(4, 3) NOT NULL DEFAULT 1.000
        CHECK (confidence >= 0 AND confidence <= 1),
    requires_verification INTEGER NOT NULL DEFAULT 0
        CHECK (requires_verification IN (0, 1)),
    embedding_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (embedding_status IN ('pending', 'embedded', 'failed')),
    created_at TEXT NOT NULL,
    UNIQUE (document_version_id, chunk_order)
);

CREATE INDEX IF NOT EXISTS idx_research_chunks_document
    ON research_chunks (document_id);
CREATE INDEX IF NOT EXISTS idx_research_chunks_parent
    ON research_chunks (parent_chunk_id);
CREATE INDEX IF NOT EXISTS idx_research_chunks_embedding
    ON research_chunks (document_version_id, embedding_status);

CREATE TABLE IF NOT EXISTS research_ingestion_jobs (
    job_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL
        REFERENCES research_documents (document_id) ON DELETE CASCADE,
    document_version_id TEXT NOT NULL
        REFERENCES research_document_versions (document_version_id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN (
        'RECEIVED', 'VALIDATING', 'PARSING', 'NORMALIZING', 'CHUNKING', 'EMBEDDING',
        'INDEXING', 'VERIFYING', 'PUBLISHED', 'RETRYABLE_FAILED', 'PERMANENT_FAILED',
        'CANCELLED'
    )),
    attempt_id INTEGER NOT NULL DEFAULT 0 CHECK (attempt_id >= 0),
    worker_id TEXT,
    lease_expires_at TEXT,
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts >= 1 AND max_attempts <= 10),
    failure_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    -- 领域层同样拒绝这两种组合；重复一次是为了让绕过领域层的写入也失败。
    CHECK ((worker_id IS NULL) = (lease_expires_at IS NULL)),
    CHECK (attempt_id <= max_attempts),
    CHECK (status NOT IN ('RETRYABLE_FAILED', 'PERMANENT_FAILED') OR failure_reason IS NOT NULL),
    CHECK (status IN ('RETRYABLE_FAILED', 'PERMANENT_FAILED') OR failure_reason IS NULL)
);

CREATE INDEX IF NOT EXISTS idx_research_jobs_version
    ON research_ingestion_jobs (document_version_id);
CREATE INDEX IF NOT EXISTS idx_research_jobs_lease
    ON research_ingestion_jobs (status, lease_expires_at);

CREATE TABLE IF NOT EXISTS research_index_outbox (
    event_id TEXT PRIMARY KEY,
    document_version_id TEXT NOT NULL
        REFERENCES research_document_versions (document_version_id) ON DELETE CASCADE,
    index_generation TEXT NOT NULL,
    operation TEXT NOT NULL CHECK (operation IN ('publish_generation', 'delete_generation')),
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'CLAIMED', 'DONE', 'FAILED')),
    payload_json TEXT NOT NULL DEFAULT '{}',
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    claimed_by TEXT,
    claimed_at TEXT,
    available_at TEXT NOT NULL,
    last_error TEXT,
    created_at TEXT NOT NULL,
    CHECK ((claimed_by IS NULL) = (claimed_at IS NULL)),
    CHECK (status <> 'CLAIMED' OR claimed_by IS NOT NULL),
    CHECK (status = 'CLAIMED' OR claimed_by IS NULL)
);

CREATE INDEX IF NOT EXISTS idx_research_outbox_available
    ON research_index_outbox (status, available_at);
CREATE INDEX IF NOT EXISTS idx_research_outbox_version
    ON research_index_outbox (document_version_id, index_generation);

CREATE TABLE IF NOT EXISTS research_retrieval_audits (
    retrieval_id TEXT PRIMARY KEY,
    run_id TEXT,
    task_id TEXT,
    attempt_id INTEGER CHECK (attempt_id IS NULL OR attempt_id >= 0),
    role TEXT,
    question TEXT NOT NULL,
    query_fingerprint TEXT NOT NULL,
    filters_json TEXT NOT NULL DEFAULT '{}',
    corpus_generation TEXT NOT NULL,
    provider_versions_json TEXT NOT NULL DEFAULT '{}',
    dense_candidates_json TEXT NOT NULL DEFAULT '[]',
    bm25_candidates_json TEXT NOT NULL DEFAULT '[]',
    fused_candidates_json TEXT NOT NULL DEFAULT '[]',
    reranked_candidates_json TEXT NOT NULL DEFAULT '[]',
    parent_expansions_json TEXT NOT NULL DEFAULT '[]',
    claims_json TEXT NOT NULL DEFAULT '[]',
    conflicts_json TEXT NOT NULL DEFAULT '[]',
    returned_evidence_json TEXT NOT NULL DEFAULT '[]',
    duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    provider_calls INTEGER CHECK (provider_calls IS NULL OR provider_calls >= 0),
    input_tokens INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0),
    cost_cny NUMERIC(12, 6) CHECK (cost_cny IS NULL OR cost_cny >= 0),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_research_audits_run
    ON research_retrieval_audits (run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_research_audits_fingerprint
    ON research_retrieval_audits (query_fingerprint);
CREATE INDEX IF NOT EXISTS idx_research_audits_corpus
    ON research_retrieval_audits (corpus_generation);

CREATE TABLE IF NOT EXISTS research_conflict_decisions (
    decision_id TEXT PRIMARY KEY,
    retrieval_id TEXT NOT NULL
        REFERENCES research_retrieval_audits (retrieval_id) ON DELETE CASCADE,
    status TEXT NOT NULL
        CHECK (status IN ('RESOLVED', 'NOT_CONFLICT', 'UNRESOLVED', 'CHECK_FAILED')),
    claim_ids_json TEXT NOT NULL,
    rule TEXT CHECK (rule IS NULL OR rule IN (
        'STATUS', 'EXPLICIT_VERSION', 'EFFECTIVE_TIME', 'SOURCE_WEIGHT',
        'EVIDENCE_QUALITY', 'RELEVANCE'
    )),
    selected_claim_id TEXT,
    nli_relation TEXT
        CHECK (nli_relation IS NULL OR nli_relation IN (
            'ENTAILMENT', 'CONTRADICTION', 'NEUTRAL', 'UNCERTAIN'
        )),
    nli_confidence NUMERIC(4, 3)
        CHECK (nli_confidence IS NULL OR (nli_confidence >= 0 AND nli_confidence <= 1)),
    nli_provider TEXT,
    nli_model_version TEXT,
    rationale TEXT,
    created_at TEXT NOT NULL,
    -- 规格 14：无法裁决的冲突必须保留双方且不得选出赢家。
    CHECK (status <> 'RESOLVED' OR (rule IS NOT NULL AND selected_claim_id IS NOT NULL)),
    CHECK (status = 'RESOLVED' OR selected_claim_id IS NULL)
);

CREATE INDEX IF NOT EXISTS idx_research_conflicts_retrieval
    ON research_conflict_decisions (retrieval_id);
CREATE INDEX IF NOT EXISTS idx_research_conflicts_status
    ON research_conflict_decisions (status);

CREATE TABLE IF NOT EXISTS internal_research_evidence (
    evidence_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    task_id TEXT,
    -- A2 接纳后交给 A3/A4 的 ArtifactRef；A3/A4 只能凭它读取，不能自行检索。
    artifact_ref TEXT,
    retrieval_id TEXT NOT NULL
        REFERENCES research_retrieval_audits (retrieval_id) ON DELETE CASCADE,
    claim_id TEXT,
    statement TEXT NOT NULL CHECK (length(trim(statement)) > 0),
    stance TEXT NOT NULL DEFAULT 'supporting'
        CHECK (stance IN ('supporting', 'opposing', 'neutral')),
    conflict_status TEXT NOT NULL
        CHECK (conflict_status IN ('RESOLVED', 'NOT_CONFLICT', 'UNRESOLVED', 'CHECK_FAILED')),
    grade TEXT NOT NULL
        CHECK (grade IN ('PRIMARY_SOURCE', 'PARSED_STRUCTURE', 'DERIVED_UNVERIFIED')),
    requires_verification INTEGER NOT NULL DEFAULT 0
        CHECK (requires_verification IN (0, 1)),
    qualifiers_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_internal_evidence_run
    ON internal_research_evidence (run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_internal_evidence_retrieval
    ON internal_research_evidence (retrieval_id);

CREATE TABLE IF NOT EXISTS internal_research_evidence_sources (
    evidence_id TEXT NOT NULL
        REFERENCES internal_research_evidence (evidence_id) ON DELETE CASCADE,
    source_order INTEGER NOT NULL CHECK (source_order >= 0),
    document_id TEXT NOT NULL,
    document_version_id TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    page_start INTEGER CHECK (page_start IS NULL OR page_start >= 1),
    page_end INTEGER CHECK (page_end IS NULL OR page_end >= 1),
    section_path_json TEXT NOT NULL DEFAULT '[]',
    bounding_boxes_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (evidence_id, source_order),
    CHECK (page_end IS NULL OR page_start IS NULL OR page_end >= page_start)
);

CREATE INDEX IF NOT EXISTS idx_internal_evidence_sources_chunk
    ON internal_research_evidence_sources (chunk_id);
CREATE INDEX IF NOT EXISTS idx_internal_evidence_sources_document
    ON internal_research_evidence_sources (document_id, document_version_id);
