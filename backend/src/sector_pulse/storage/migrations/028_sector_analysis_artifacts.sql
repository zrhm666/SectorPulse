CREATE TABLE IF NOT EXISTS sector_analysis_artifacts (
    analysis_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    task_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt >= 1),
    sector_id TEXT NOT NULL,
    sector_kind TEXT NOT NULL CHECK (sector_kind IN ('INDUSTRY', 'CONCEPT')),
    inspection_id TEXT NOT NULL REFERENCES evidence_inspection_reports(report_id)
        ON DELETE RESTRICT,
    input_fingerprint TEXT NOT NULL,
    card_hash TEXT NOT NULL,
    card_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, task_id, attempt, input_fingerprint)
);

CREATE TABLE IF NOT EXISTS sector_analysis_claims (
    analysis_id TEXT NOT NULL REFERENCES sector_analysis_artifacts(analysis_id)
        ON DELETE CASCADE,
    claim_id TEXT NOT NULL,
    claim_kind TEXT NOT NULL CHECK (
        claim_kind IN ('MARKET_FACT', 'NEWS_FACT', 'ATTRIBUTION', 'BACKGROUND')
    ),
    payload_json TEXT NOT NULL,
    PRIMARY KEY (analysis_id, claim_id)
);

CREATE INDEX IF NOT EXISTS idx_sector_analysis_scope
    ON sector_analysis_artifacts(run_id, sector_kind, sector_id, created_at);
