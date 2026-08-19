CREATE TABLE IF NOT EXISTS shadow_runs (
  shadow_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  trading_date TEXT NOT NULL,
  mode TEXT NOT NULL,
  status TEXT NOT NULL,
  provider_status_json TEXT NOT NULL,
  cutoff_at TEXT,
  metrics_json TEXT NOT NULL,
  failure_reason TEXT,
  created_at TEXT NOT NULL,
  finished_at TEXT,
  UNIQUE(run_id, shadow_id)
);

CREATE TABLE IF NOT EXISTS recovery_drills (
  drill_id TEXT PRIMARY KEY,
  shadow_id TEXT NOT NULL,
  fault_type TEXT NOT NULL,
  recovered INTEGER NOT NULL CHECK (recovered IN (0, 1)),
  recovery_seconds REAL NOT NULL,
  notes TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS compliance_records (
  record_id TEXT PRIMARY KEY,
  shadow_id TEXT NOT NULL,
  rules_version TEXT NOT NULL,
  decision TEXT NOT NULL,
  reviewer TEXT NOT NULL,
  notes TEXT NOT NULL,
  created_at TEXT NOT NULL
);
