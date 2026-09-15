CREATE TABLE IF NOT EXISTS orchestration_candidate_selections (
    run_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    proposal_id TEXT NOT NULL,
    selected_sector_ids_json TEXT NOT NULL,
    method TEXT NOT NULL CHECK (method IN ('DEFAULT', 'MANUAL')),
    confirmed_at TEXT NOT NULL,
    data_version TEXT NOT NULL,
    edit_count INTEGER NOT NULL DEFAULT 0 CHECK (edit_count >= 0),
    PRIMARY KEY (run_id, version)
);

CREATE INDEX IF NOT EXISTS idx_orchestration_candidate_selections_latest
    ON orchestration_candidate_selections(run_id, version DESC);
