CREATE TABLE IF NOT EXISTS attribution_agent_steps (
    run_id TEXT NOT NULL,
    sector_kind TEXT NOT NULL,
    sector_id TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (run_id, sector_kind, sector_id, step_index, event_type)
);
