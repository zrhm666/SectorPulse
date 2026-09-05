ALTER TABLE phase1b_runs ADD COLUMN retry_of_run_id TEXT;
CREATE INDEX idx_phase1b_runs_retry_of ON phase1b_runs(retry_of_run_id);
