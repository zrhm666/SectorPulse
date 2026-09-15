CREATE TABLE IF NOT EXISTS research_search_batches (
    batch_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    task_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt >= 1),
    sector_id TEXT NOT NULL,
    sector_kind TEXT NOT NULL CHECK (sector_kind IN ('INDUSTRY', 'CONCEPT')),
    query_text TEXT NOT NULL,
    start_at TEXT NOT NULL,
    cutoff_at TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('SUCCESS', 'EMPTY', 'FAILED')),
    error_code TEXT,
    document_count INTEGER NOT NULL CHECK (document_count >= 0),
    event_count INTEGER NOT NULL CHECK (event_count >= 0),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, task_id, attempt, input_fingerprint)
);

CREATE TABLE IF NOT EXISTS research_search_documents (
    batch_id TEXT NOT NULL REFERENCES research_search_batches(batch_id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES news_documents(document_id) ON DELETE RESTRICT,
    PRIMARY KEY (batch_id, document_id)
);

CREATE TABLE IF NOT EXISTS research_search_events (
    batch_id TEXT NOT NULL REFERENCES research_search_batches(batch_id) ON DELETE CASCADE,
    event_id TEXT NOT NULL REFERENCES news_events(event_id) ON DELETE RESTRICT,
    PRIMARY KEY (batch_id, event_id)
);

CREATE INDEX IF NOT EXISTS idx_research_search_scope
    ON research_search_batches(run_id, sector_kind, sector_id, created_at);
