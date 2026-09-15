CREATE TABLE IF NOT EXISTS editorial_draft_artifacts (
    artifact_id TEXT PRIMARY KEY,
    draft_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    task_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt >= 1),
    version INTEGER NOT NULL CHECK (version >= 1),
    outline_id TEXT NOT NULL REFERENCES editorial_outline_artifacts(outline_id)
        ON DELETE RESTRICT,
    input_fingerprint TEXT NOT NULL,
    draft_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (draft_id, version),
    UNIQUE (run_id, task_id, attempt, input_fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_editorial_draft_run_version
    ON editorial_draft_artifacts(run_id, draft_id, version);
