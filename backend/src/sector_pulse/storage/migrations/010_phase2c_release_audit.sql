CREATE TABLE IF NOT EXISTS draft_approvals (
  approval_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  draft_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  governance_hash TEXT NOT NULL,
  actor TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('APPROVED_FOR_COPY', 'REVOKED')),
  approved_at TEXT NOT NULL,
  UNIQUE(draft_id, version)
);

CREATE TABLE IF NOT EXISTS audit_events (
  event_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  draft_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  actor TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS draft_exports (
  export_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  draft_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  format TEXT NOT NULL CHECK (format IN ('json', 'md', 'txt')),
  content_hash TEXT NOT NULL,
  actor TEXT NOT NULL,
  created_at TEXT NOT NULL
);
