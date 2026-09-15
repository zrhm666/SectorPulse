CREATE TABLE IF NOT EXISTS independent_review_artifacts (
    artifact_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    task_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt >= 1),
    draft_artifact_id TEXT NOT NULL REFERENCES editorial_draft_artifacts(artifact_id)
        ON DELETE RESTRICT,
    rules_artifact_id TEXT NOT NULL REFERENCES draft_rules_artifacts(artifact_id)
        ON DELETE RESTRICT,
    draft_id TEXT NOT NULL,
    draft_version INTEGER NOT NULL CHECK (draft_version >= 1),
    decision TEXT NOT NULL CHECK (decision IN ('PASS', 'REVISE', 'BLOCK')),
    input_fingerprint TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, task_id, attempt, draft_artifact_id),
    UNIQUE (run_id, task_id, attempt, input_fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_independent_review_version
    ON independent_review_artifacts(run_id, draft_id, draft_version);
