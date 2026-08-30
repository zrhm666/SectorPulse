CREATE TABLE phase1b_runs_017 (
  run_id TEXT PRIMARY KEY,
  requested_at TEXT NOT NULL,
  provider TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN (
    'RUNNING', 'READY_FOR_HUMAN_REVIEW', 'REVISE_REQUIRED',
    'UNREVIEWED', 'BUDGET_EXCEEDED', 'ATTRIBUTION_BLOCKED',
    'DRAFT_GENERATION_FAILED', 'FAILED', 'CANCELLED', 'INTERRUPTED'
  )),
  elapsed_ms INTEGER,
  total_cost_cny TEXT,
  input_json_hash TEXT,
  draft_id TEXT,
  error_message TEXT,
  finished_at TEXT,
  input_json TEXT
);

INSERT INTO phase1b_runs_017 (
  run_id, requested_at, provider, status, elapsed_ms, total_cost_cny,
  input_json_hash, draft_id, error_message, finished_at, input_json
)
SELECT
  run_id, requested_at, provider, status, elapsed_ms, total_cost_cny,
  input_json_hash, draft_id, error_message, finished_at, input_json
FROM phase1b_runs;

DROP TABLE phase1b_runs;
ALTER TABLE phase1b_runs_017 RENAME TO phase1b_runs;
CREATE INDEX idx_phase1b_runs_requested_at ON phase1b_runs(requested_at DESC);
