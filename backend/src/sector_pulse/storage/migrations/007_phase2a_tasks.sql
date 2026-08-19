CREATE TABLE IF NOT EXISTS schedules (
  schedule_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  mode TEXT NOT NULL CHECK (mode IN ('intraday', 'post_close', 'manual')),
  timezone TEXT NOT NULL,
  local_time TEXT NOT NULL,
  trading_days TEXT NOT NULL,
  schedule_spec_json TEXT NOT NULL,
  input_template_json TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
  version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
  next_run_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_runs (
  run_id TEXT PRIMARY KEY,
  schedule_id TEXT REFERENCES schedules(schedule_id),
  trading_date TEXT,
  planned_slot TEXT,
  provider TEXT NOT NULL,
  input_fingerprint TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN (
    'QUEUED', 'RUNNING', 'RETRY_WAITING', 'DEGRADED',
    'READY_FOR_HUMAN_REVIEW', 'FAILED', 'CANCELLED'
  )),
  run_cutoff_at TEXT,
  error_code TEXT,
  error_message TEXT,
  downgrade_reasons_json TEXT NOT NULL DEFAULT '[]',
  worker_id TEXT,
  lease_until TEXT,
  requested_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  UNIQUE(schedule_id, trading_date, planned_slot, input_fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_task_runs_status_lease
  ON task_runs(status, lease_until);
CREATE INDEX IF NOT EXISTS idx_task_runs_requested_at
  ON task_runs(requested_at DESC);

CREATE TABLE IF NOT EXISTS run_stage_attempts (
  run_id TEXT NOT NULL REFERENCES task_runs(run_id),
  stage TEXT NOT NULL,
  attempt_no INTEGER NOT NULL CHECK (attempt_no >= 1),
  status TEXT NOT NULL,
  input_fingerprint TEXT NOT NULL,
  output_fingerprint TEXT,
  provider TEXT,
  error_code TEXT,
  error_message TEXT,
  retry_after TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  PRIMARY KEY (run_id, stage, attempt_no)
);

CREATE TABLE IF NOT EXISTS run_checkpoints (
  checkpoint_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES task_runs(run_id),
  stage TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  input_fingerprint TEXT NOT NULL,
  implementation_version TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  payload_sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(run_id, stage, input_fingerprint, implementation_version)
);

CREATE TABLE IF NOT EXISTS task_events (
  event_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES task_runs(run_id),
  source TEXT NOT NULL,
  event_type TEXT NOT NULL,
  old_status TEXT,
  new_status TEXT,
  idempotency_key TEXT,
  summary TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_events_run_created
  ON task_events(run_id, created_at);
