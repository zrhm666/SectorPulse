ALTER TABLE task_runs ADD COLUMN retry_of_run_id TEXT REFERENCES task_runs(run_id);
ALTER TABLE task_runs ADD COLUMN cancel_requested_at TEXT;
ALTER TABLE task_runs ADD COLUMN interrupted_reason TEXT;
ALTER TABLE task_runs ADD COLUMN heartbeat_at TEXT;
ALTER TABLE real_data_runs ADD COLUMN retry_of_run_id TEXT REFERENCES real_data_runs(run_id);
ALTER TABLE schedules ADD COLUMN last_triggered_at TEXT;

CREATE INDEX IF NOT EXISTS idx_real_data_runs_retry_of
  ON real_data_runs(retry_of_run_id);
CREATE INDEX IF NOT EXISTS idx_schedules_due
  ON schedules(enabled, next_run_at);
