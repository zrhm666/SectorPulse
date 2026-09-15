ALTER TABLE editorial_draft_artifacts
    ADD COLUMN base_draft_artifact_id TEXT;

ALTER TABLE editorial_draft_artifacts
    ADD COLUMN review_artifact_id TEXT;

ALTER TABLE editorial_draft_artifacts
    ADD COLUMN revision_round INTEGER NOT NULL DEFAULT 0
        CHECK (revision_round >= 0 AND revision_round <= 2);

CREATE INDEX IF NOT EXISTS idx_editorial_draft_revision_parent
    ON editorial_draft_artifacts(base_draft_artifact_id, review_artifact_id);
