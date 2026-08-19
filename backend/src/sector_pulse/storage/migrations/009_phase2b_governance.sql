CREATE TABLE IF NOT EXISTS draft_patches (
  patch_id TEXT PRIMARY KEY,
  draft_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  base_version INTEGER NOT NULL,
  new_version INTEGER NOT NULL,
  operation_index INTEGER NOT NULL,
  operation_json TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  output_hash TEXT NOT NULL,
  actor TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(draft_id, new_version, operation_index)
);

CREATE TABLE IF NOT EXISTS evidence_decisions (
  decision_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  draft_id TEXT NOT NULL,
  draft_version INTEGER NOT NULL,
  source_id TEXT NOT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('KEEP', 'DOWNGRADE', 'REJECT')),
  reason TEXT NOT NULL,
  affected_section_ids_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rewrite_requests (
  rewrite_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  draft_id TEXT NOT NULL,
  base_version INTEGER NOT NULL,
  section_id TEXT NOT NULL,
  status TEXT NOT NULL,
  error_code TEXT,
  result_version INTEGER,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS governance_checks (
  check_id TEXT PRIMARY KEY,
  draft_id TEXT NOT NULL,
  draft_version INTEGER NOT NULL,
  check_type TEXT NOT NULL,
  status TEXT NOT NULL,
  issues_json TEXT NOT NULL,
  rules_version TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS preference_candidates (
  candidate_id TEXT PRIMARY KEY,
  source_patch_id TEXT NOT NULL,
  content_json TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS preference_versions (
  version INTEGER PRIMARY KEY,
  content_json TEXT NOT NULL,
  adopted_at TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);
