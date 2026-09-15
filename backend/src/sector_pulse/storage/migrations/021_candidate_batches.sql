CREATE TABLE IF NOT EXISTS candidate_batches (
    batch_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    input_fingerprint TEXT NOT NULL,
    ranking_stage TEXT NOT NULL CHECK (ranking_stage IN ('MARKET', 'NEWS_ENRICHED')),
    candidate_limit INTEGER NOT NULL CHECK (candidate_limit >= 1 AND candidate_limit <= 50),
    created_at TEXT NOT NULL,
    UNIQUE (run_id, input_fingerprint)
);

CREATE TABLE IF NOT EXISTS sector_candidate_versions (
    batch_id TEXT NOT NULL REFERENCES candidate_batches(batch_id) ON DELETE CASCADE,
    provider_sector_id TEXT NOT NULL,
    sector_kind TEXT NOT NULL CHECK (sector_kind IN ('INDUSTRY', 'CONCEPT')),
    sector_name TEXT NOT NULL,
    rank INTEGER NOT NULL CHECK (rank >= 1),
    score TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    PRIMARY KEY (batch_id, provider_sector_id, sector_kind),
    UNIQUE (batch_id, rank)
);

CREATE INDEX IF NOT EXISTS idx_candidate_batches_run_created
    ON candidate_batches(run_id, created_at);
