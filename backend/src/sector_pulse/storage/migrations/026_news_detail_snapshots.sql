CREATE TABLE IF NOT EXISTS news_detail_snapshots (
    detail_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    task_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt >= 1),
    sector_id TEXT NOT NULL,
    sector_kind TEXT NOT NULL CHECK (sector_kind IN ('INDUSTRY', 'CONCEPT')),
    document_id TEXT NOT NULL REFERENCES news_documents(document_id) ON DELETE RESTRICT,
    document_content_hash TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    availability TEXT NOT NULL CHECK (
        availability IN ('full_text', 'summary_only', 'unavailable')
    ),
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    truncated INTEGER NOT NULL CHECK (truncated IN (0, 1)),
    historical_snapshot_verified INTEGER NOT NULL CHECK (
        historical_snapshot_verified IN (0, 1)
    ),
    error_code TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, task_id, attempt, input_fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_news_detail_scope
    ON news_detail_snapshots(run_id, sector_kind, sector_id, document_id, created_at);
