CREATE TABLE IF NOT EXISTS evidence_inspection_reports (
    report_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    task_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt >= 1),
    sector_id TEXT NOT NULL,
    sector_kind TEXT NOT NULL CHECK (sector_kind IN ('INDUSTRY', 'CONCEPT')),
    selection_version INTEGER NOT NULL CHECK (selection_version >= 1),
    input_fingerprint TEXT NOT NULL,
    artifact_ids_json TEXT NOT NULL,
    context_json TEXT NOT NULL,
    gate_json TEXT NOT NULL,
    document_views_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, task_id, attempt, input_fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_evidence_inspection_scope
    ON evidence_inspection_reports(run_id, sector_kind, sector_id, created_at);
