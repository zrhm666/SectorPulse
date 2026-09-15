CREATE TABLE IF NOT EXISTS editorial_outline_artifacts (
    outline_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    task_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt >= 1),
    selection_version INTEGER NOT NULL CHECK (selection_version >= 1),
    input_fingerprint TEXT NOT NULL,
    outline_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, task_id, attempt, input_fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_editorial_outline_run
    ON editorial_outline_artifacts(run_id, created_at);
