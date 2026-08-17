CREATE TABLE IF NOT EXISTS phase1b_runs (
  run_id TEXT PRIMARY KEY,
  requested_at TEXT NOT NULL,
  provider TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN (
    'RUNNING', 'READY_FOR_HUMAN_REVIEW', 'REVISE_REQUIRED',
    'UNREVIEWED', 'BUDGET_EXCEEDED', 'ATTRIBUTION_BLOCKED',
    'DRAFT_GENERATION_FAILED', 'FAILED', 'CANCELLED'
  )),
  elapsed_ms INTEGER,
  total_cost_cny TEXT,
  input_json_hash TEXT,
  draft_id TEXT,
  error_message TEXT,
  finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_phase1b_runs_requested_at
  ON phase1b_runs(requested_at DESC);
