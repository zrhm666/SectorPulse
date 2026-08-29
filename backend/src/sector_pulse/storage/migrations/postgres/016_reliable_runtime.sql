ALTER TABLE task_runs DROP CONSTRAINT IF EXISTS task_runs_status_check;
ALTER TABLE task_runs ADD CONSTRAINT task_runs_status_check CHECK (status IN (
  'QUEUED', 'RUNNING', 'RETRY_WAITING', 'DEGRADED',
  'READY_FOR_HUMAN_REVIEW', 'FAILED', 'CANCELLED', 'INTERRUPTED'
));

CREATE INDEX IF NOT EXISTS idx_task_runs_retry_of
  ON task_runs(retry_of_run_id);
CREATE INDEX IF NOT EXISTS idx_task_runs_status_heartbeat
  ON task_runs(status, heartbeat_at);
