CREATE TABLE real_data_runs (
  run_id TEXT PRIMARY KEY,
  mode TEXT NOT NULL CHECK (mode IN ('intraday', 'post_close')),
  status TEXT NOT NULL CHECK (status IN (
    'PREFLIGHT', 'FETCHING_MARKET', 'RANKING_PRE_CANDIDATES',
    'FETCHING_NEWS', 'BUILDING_EVIDENCE', 'READY_FOR_ATTRIBUTION',
    'DEGRADED', 'BLOCKED', 'FAILED', 'CANCELLED', 'INTERRUPTED'
  )),
  requested_at TEXT NOT NULL,
  cutoff_at TEXT,
  request_json TEXT NOT NULL,
  market_quality_json TEXT NOT NULL DEFAULT '{}',
  news_quality_json TEXT NOT NULL DEFAULT '{}',
  downgrade_reasons_json TEXT NOT NULL DEFAULT '[]',
  cutoff_violation_count INTEGER NOT NULL DEFAULT 0,
  duplicate_document_count INTEGER NOT NULL DEFAULT 0,
  error_code TEXT,
  finished_at TEXT
);

CREATE TABLE real_data_candidates (
  run_id TEXT NOT NULL REFERENCES real_data_runs(run_id) ON DELETE CASCADE,
  sector_id TEXT NOT NULL,
  sector_kind TEXT NOT NULL,
  rank INTEGER NOT NULL,
  score TEXT NOT NULL,
  reasons_json TEXT NOT NULL,
  PRIMARY KEY (run_id, sector_id)
);
