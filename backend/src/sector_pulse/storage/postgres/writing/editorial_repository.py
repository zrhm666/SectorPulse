from uuid import UUID

from sqlalchemy import text

from sector_pulse.domain.writing.editorial import (
    DraftRulesArtifact,
    EditorialDraftArtifact,
    EditorialOutlineArtifact,
    IndependentReviewArtifact,
)
from sector_pulse.storage.postgres.database import PostgresDatabase


class PostgresEditorialOutlineRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def get(self, outline_id: UUID) -> EditorialOutlineArtifact | None:
        with self._database.start().connect() as connection:
            row = connection.execute(
                text(
                    "SELECT payload_json FROM editorial_outline_artifacts "
                    "WHERE outline_id=:outline_id"
                ),
                {"outline_id": str(outline_id)},
            ).fetchone()
        return EditorialOutlineArtifact.model_validate_json(row[0]) if row else None


class PostgresEditorialDraftRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def get(self, artifact_id: UUID) -> EditorialDraftArtifact | None:
        with self._database.start().connect() as connection:
            row = connection.execute(
                text(
                    "SELECT payload_json FROM editorial_draft_artifacts "
                    "WHERE artifact_id=:artifact_id"
                ),
                {"artifact_id": str(artifact_id)},
            ).fetchone()
        return EditorialDraftArtifact.model_validate_json(row[0]) if row else None

    def get_version(self, draft_id: UUID, version: int) -> EditorialDraftArtifact | None:
        with self._database.start().connect() as connection:
            row = connection.execute(
                text(
                    "SELECT payload_json FROM editorial_draft_artifacts "
                    "WHERE draft_id=:draft_id AND version=:version"
                ),
                {"draft_id": str(draft_id), "version": version},
            ).fetchone()
        return EditorialDraftArtifact.model_validate_json(row[0]) if row else None

    def latest_version(self, draft_id: UUID) -> EditorialDraftArtifact | None:
        with self._database.start().connect() as connection:
            row = connection.execute(
                text(
                    "SELECT payload_json FROM editorial_draft_artifacts "
                    "WHERE draft_id=:draft_id ORDER BY version DESC LIMIT 1"
                ),
                {"draft_id": str(draft_id)},
            ).fetchone()
        return EditorialDraftArtifact.model_validate_json(row[0]) if row else None


class PostgresDraftRulesRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def get(self, artifact_id: UUID) -> DraftRulesArtifact | None:
        with self._database.start().connect() as connection:
            row = connection.execute(
                text(
                    "SELECT payload_json FROM draft_rules_artifacts "
                    "WHERE artifact_id=:artifact_id"
                ),
                {"artifact_id": str(artifact_id)},
            ).fetchone()
        return DraftRulesArtifact.model_validate_json(row[0]) if row else None


class PostgresIndependentReviewRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def get(self, artifact_id: UUID) -> IndependentReviewArtifact | None:
        with self._database.start().connect() as connection:
            row = connection.execute(
                text(
                    "SELECT payload_json FROM independent_review_artifacts "
                    "WHERE artifact_id=:artifact_id"
                ),
                {"artifact_id": str(artifact_id)},
            ).fetchone()
        return IndependentReviewArtifact.model_validate_json(row[0]) if row else None
