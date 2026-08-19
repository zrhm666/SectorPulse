ALTER TABLE task_runs ADD COLUMN data_run_id TEXT;
CREATE INDEX IF NOT EXISTS idx_task_runs_data_run_id ON task_runs(data_run_id);
