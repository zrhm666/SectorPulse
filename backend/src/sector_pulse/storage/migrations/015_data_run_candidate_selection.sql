CREATE TABLE IF NOT EXISTS data_run_candidate_selections (
    run_id TEXT NOT NULL REFERENCES real_data_runs(run_id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK (version >= 1),
    selected_sector_ids_json TEXT NOT NULL,
    method TEXT NOT NULL CHECK (method IN ('DEFAULT', 'MANUAL')),
    confirmed_at TEXT NOT NULL,
    data_version TEXT NOT NULL,
    edit_count INTEGER NOT NULL DEFAULT 0 CHECK (edit_count >= 0),
    PRIMARY KEY (run_id, version)
);

CREATE INDEX IF NOT EXISTS idx_data_run_candidate_selections_latest
    ON data_run_candidate_selections(run_id, version DESC);
