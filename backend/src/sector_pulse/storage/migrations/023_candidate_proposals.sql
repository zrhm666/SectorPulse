CREATE TABLE IF NOT EXISTS candidate_proposals (
    proposal_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    candidate_batch_id TEXT NOT NULL REFERENCES candidate_batches(batch_id) ON DELETE RESTRICT,
    input_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, input_fingerprint)
);

CREATE TABLE IF NOT EXISTS candidate_proposal_items (
    proposal_id TEXT NOT NULL REFERENCES candidate_proposals(proposal_id) ON DELETE CASCADE,
    provider_sector_id TEXT NOT NULL,
    sector_kind TEXT NOT NULL CHECK (sector_kind IN ('INDUSTRY', 'CONCEPT')),
    sector_name TEXT NOT NULL,
    rank INTEGER NOT NULL CHECK (rank >= 1),
    score TEXT NOT NULL,
    explanation TEXT NOT NULL,
    PRIMARY KEY (proposal_id, provider_sector_id, sector_kind),
    UNIQUE (proposal_id, rank)
);

CREATE INDEX IF NOT EXISTS idx_candidate_proposals_run_created
    ON candidate_proposals(run_id, created_at);
