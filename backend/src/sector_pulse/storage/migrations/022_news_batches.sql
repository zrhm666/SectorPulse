ALTER TABLE news_source_runs ADD COLUMN result_count INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS news_batches (
    batch_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    candidate_batch_id TEXT NOT NULL REFERENCES candidate_batches(batch_id) ON DELETE RESTRICT,
    input_fingerprint TEXT NOT NULL,
    collection_reason TEXT NOT NULL CHECK (
        collection_reason IN ('INITIAL_CANDIDATES', 'SOURCE_GAP', 'COVERAGE_GAP')
    ),
    start_at TEXT NOT NULL,
    cutoff_at TEXT NOT NULL,
    quality_status TEXT NOT NULL,
    document_count INTEGER NOT NULL CHECK (document_count >= 0),
    event_count INTEGER NOT NULL CHECK (event_count >= 0),
    link_count INTEGER NOT NULL CHECK (link_count >= 0),
    source_metrics_json TEXT NOT NULL,
    quality_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, input_fingerprint)
);

CREATE TABLE IF NOT EXISTS news_batch_documents (
    batch_id TEXT NOT NULL REFERENCES news_batches(batch_id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES news_documents(document_id) ON DELETE RESTRICT,
    PRIMARY KEY (batch_id, document_id)
);

CREATE TABLE IF NOT EXISTS news_batch_events (
    batch_id TEXT NOT NULL REFERENCES news_batches(batch_id) ON DELETE CASCADE,
    event_id TEXT NOT NULL REFERENCES news_events(event_id) ON DELETE RESTRICT,
    PRIMARY KEY (batch_id, event_id)
);

CREATE INDEX IF NOT EXISTS idx_news_batches_run_created
    ON news_batches(run_id, created_at);
