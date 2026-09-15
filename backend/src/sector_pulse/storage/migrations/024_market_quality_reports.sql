CREATE TABLE IF NOT EXISTS market_quality_reports (
    report_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    source_artifact_id TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    quality_status TEXT NOT NULL CHECK (quality_status IN ('NORMAL', 'DEGRADED', 'BLOCKED')),
    sector_count INTEGER NOT NULL CHECK (sector_count >= 0),
    issues_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, input_fingerprint)
);
