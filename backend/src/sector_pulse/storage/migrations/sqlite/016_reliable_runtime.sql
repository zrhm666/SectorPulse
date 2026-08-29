CREATE TABLE task_runs_016 (
  run_id TEXT PRIMARY KEY,
  schedule_id TEXT REFERENCES schedules(schedule_id),
  trading_date TEXT,
  planned_slot TEXT,
  provider TEXT NOT NULL,
  input_fingerprint TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN (
    'QUEUED', 'RUNNING', 'RETRY_WAITING', 'DEGRADED',
    'READY_FOR_HUMAN_REVIEW', 'FAILED', 'CANCELLED', 'INTERRUPTED'
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
  data_run_id TEXT,
  retry_of_run_id TEXT REFERENCES task_runs(run_id),
  cancel_requested_at TEXT,
  interrupted_reason TEXT,
  heartbeat_at TEXT,
  UNIQUE(schedule_id, trading_date, planned_slot, input_fingerprint)
);

INSERT INTO task_runs_016 (
  run_id, schedule_id, trading_date, planned_slot, provider, input_fingerprint,
  status, run_cutoff_at, error_code, error_message, downgrade_reasons_json,
  worker_id, lease_until, requested_at, started_at, finished_at, data_run_id,
  retry_of_run_id, cancel_requested_at, interrupted_reason, heartbeat_at
)
SELECT
  run_id, schedule_id, trading_date, planned_slot, provider, input_fingerprint,
  status, run_cutoff_at, error_code, error_message, downgrade_reasons_json,
  worker_id, lease_until, requested_at, started_at, finished_at, data_run_id,
  retry_of_run_id, cancel_requested_at, interrupted_reason, heartbeat_at
FROM task_runs;

DROP TABLE task_runs;
ALTER TABLE task_runs_016 RENAME TO task_runs;

CREATE INDEX IF NOT EXISTS idx_task_runs_status_lease
  ON task_runs(status, lease_until);
CREATE INDEX IF NOT EXISTS idx_task_runs_requested_at
  ON task_runs(requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_task_runs_data_run_id
  ON task_runs(data_run_id);
CREATE INDEX IF NOT EXISTS idx_task_runs_retry_of
  ON task_runs(retry_of_run_id);
CREATE INDEX IF NOT EXISTS idx_task_runs_status_heartbeat
  ON task_runs(status, heartbeat_at);
