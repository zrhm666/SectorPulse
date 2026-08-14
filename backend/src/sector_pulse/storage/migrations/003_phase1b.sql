CREATE TABLE IF NOT EXISTS attribution_contexts (
    run_id TEXT NOT NULL,
    sector_id TEXT NOT NULL,
    sector_kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    PRIMARY KEY (run_id, sector_id, sector_kind)
);

CREATE TABLE IF NOT EXISTS attribution_gate_results (
    run_id TEXT NOT NULL,
    sector_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    PRIMARY KEY (run_id, sector_id)
);

CREATE TABLE IF NOT EXISTS sector_analysis_cards (
    run_id TEXT NOT NULL,
    sector_id TEXT NOT NULL,
    sector_kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    PRIMARY KEY (run_id, sector_id, sector_kind)
);

CREATE TABLE IF NOT EXISTS claims (
    run_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    PRIMARY KEY (run_id, claim_id)
);

CREATE TABLE IF NOT EXISTS article_outlines (
    outline_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS article_drafts (
    draft_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    PRIMARY KEY (draft_id, version)
);

CREATE TABLE IF NOT EXISTS article_sections (
    draft_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    section_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    PRIMARY KEY (draft_id, version, section_id)
);

CREATE TABLE IF NOT EXISTS article_sources (
    draft_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    source_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    PRIMARY KEY (draft_id, version, source_id)
);

CREATE TABLE IF NOT EXISTS review_reports (
    review_id TEXT PRIMARY KEY,
    draft_id TEXT NOT NULL,
    draft_version INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_issues (
    review_id TEXT NOT NULL,
    issue_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    PRIMARY KEY (review_id, issue_id)
);

CREATE TABLE IF NOT EXISTS agent_invocations (
    invocation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    output_hash TEXT,
    status TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    estimated_cost_cny TEXT NOT NULL,
    error_code TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_invocations_run_stage
    ON agent_invocations(run_id, stage);
CREATE INDEX IF NOT EXISTS idx_agent_invocations_provider_model
    ON agent_invocations(provider_id, model);
