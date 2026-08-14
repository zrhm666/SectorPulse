ALTER TABLE news_documents ADD COLUMN citation_url TEXT;
ALTER TABLE news_documents ADD COLUMN publisher TEXT;
ALTER TABLE news_documents ADD COLUMN summary TEXT;
ALTER TABLE news_documents ADD COLUMN source_observed_at TEXT;
ALTER TABLE news_documents ADD COLUMN use_grade TEXT NOT NULL DEFAULT 'BACKGROUND';
ALTER TABLE news_documents ADD COLUMN quality_flags_json TEXT NOT NULL DEFAULT '[]';

CREATE TABLE IF NOT EXISTS news_source_runs (
    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    source_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    call_count INTEGER NOT NULL,
    retry_count INTEGER NOT NULL,
    status TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    error_code TEXT,
    PRIMARY KEY (run_id, source_id)
);

CREATE TABLE IF NOT EXISTS news_queries (
    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    query_id TEXT NOT NULL,
    query_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    value_hash TEXT NOT NULL,
    sector_ids_json TEXT NOT NULL,
    priority INTEGER NOT NULL,
    start_at TEXT NOT NULL,
    cutoff_at TEXT NOT NULL,
    status TEXT NOT NULL,
    result_count INTEGER NOT NULL,
    error_code TEXT,
    PRIMARY KEY (run_id, query_id)
);

CREATE TABLE IF NOT EXISTS sector_event_links (
    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    event_id TEXT NOT NULL REFERENCES news_events(event_id) ON DELETE CASCADE,
    sector_id TEXT NOT NULL,
    sector_kind TEXT NOT NULL CHECK (sector_kind IN ('INDUSTRY', 'CONCEPT')),
    relation_type TEXT NOT NULL,
    matched_entities_json TEXT NOT NULL,
    mapping_confidence TEXT NOT NULL,
    mapping_reason TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    PRIMARY KEY (run_id, event_id, sector_id, sector_kind)
);
