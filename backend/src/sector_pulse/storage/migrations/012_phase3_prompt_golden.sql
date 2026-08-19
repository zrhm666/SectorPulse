CREATE TABLE IF NOT EXISTS prompt_golden_cases (
  case_id TEXT PRIMARY KEY,
  prompt_id TEXT NOT NULL,
  prompt_version INTEGER NOT NULL,
  input_hash TEXT NOT NULL,
  expected_schema TEXT NOT NULL,
  result TEXT NOT NULL,
  notes TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(prompt_id, prompt_version, input_hash)
);
