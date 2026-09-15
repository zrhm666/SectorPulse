CREATE TABLE IF NOT EXISTS orchestration_snapshots (
    run_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK (revision >= 0),
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orchestration_events (
    run_id TEXT NOT NULL REFERENCES orchestration_snapshots(run_id),
    revision INTEGER NOT NULL,
    event_json TEXT NOT NULL,
    PRIMARY KEY (run_id, revision)
);
