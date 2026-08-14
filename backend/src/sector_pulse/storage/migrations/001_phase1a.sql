CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL CHECK (mode IN ('LIVE', 'AS_OF')),
    requested_at TEXT NOT NULL,
    requested_cutoff_at TEXT,
    run_cutoff_at TEXT,
    cutoff_locked_at TEXT
);

CREATE TABLE IF NOT EXISTS sector_snapshots (
    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    sector_kind TEXT NOT NULL CHECK (sector_kind IN ('INDUSTRY', 'CONCEPT')),
    provider_id TEXT NOT NULL,
    classification_version TEXT NOT NULL,
    source_version TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (run_id, sector_kind)
);

CREATE TABLE IF NOT EXISTS news_documents (
    document_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    canonical_url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    published_at TEXT,
    observed_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    source_grade TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS news_events (
    event_id TEXT PRIMARY KEY,
    canonical_title TEXT NOT NULL,
    first_published_at TEXT,
    deduplication_reason TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS news_event_documents (
    event_id TEXT NOT NULL REFERENCES news_events(event_id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES news_documents(document_id) ON DELETE CASCADE,
    PRIMARY KEY (event_id, document_id)
);

CREATE TABLE IF NOT EXISTS sector_candidates (
    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    provider_sector_id TEXT NOT NULL,
    sector_kind TEXT NOT NULL CHECK (sector_kind IN ('INDUSTRY', 'CONCEPT')),
    rank INTEGER NOT NULL,
    score TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    PRIMARY KEY (run_id, provider_sector_id, sector_kind)
);

CREATE TABLE IF NOT EXISTS evidence_packs (
    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    provider_sector_id TEXT NOT NULL,
    sector_kind TEXT NOT NULL CHECK (sector_kind IN ('INDUSTRY', 'CONCEPT')),
    quality_status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    PRIMARY KEY (run_id, provider_sector_id, sector_kind)
);
