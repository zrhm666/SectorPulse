from uuid import UUID

from sector_pulse.domain.writing.editorial import (
    DraftRulesArtifact,
    EditorialDraftArtifact,
    EditorialOutlineArtifact,
    IndependentReviewArtifact,
)
from sector_pulse.storage.sqlite.database import SQLiteDatabase


class SQLiteEditorialOutlineRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def get(self, outline_id: UUID) -> EditorialOutlineArtifact | None:
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM editorial_outline_artifacts WHERE outline_id = ?",
                (str(outline_id),),
            ).fetchone()
        return EditorialOutlineArtifact.model_validate_json(row[0]) if row else None


class SQLiteEditorialDraftRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def get(self, artifact_id: UUID) -> EditorialDraftArtifact | None:
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM editorial_draft_artifacts WHERE artifact_id = ?",
                (str(artifact_id),),
            ).fetchone()
        return EditorialDraftArtifact.model_validate_json(row[0]) if row else None

    def get_version(self, draft_id: UUID, version: int) -> EditorialDraftArtifact | None:
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM editorial_draft_artifacts "
                "WHERE draft_id = ? AND version = ?",
                (str(draft_id), version),
            ).fetchone()
        return EditorialDraftArtifact.model_validate_json(row[0]) if row else None

    def latest_version(self, draft_id: UUID) -> EditorialDraftArtifact | None:
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM editorial_draft_artifacts "
                "WHERE draft_id = ? ORDER BY version DESC LIMIT 1",
                (str(draft_id),),
            ).fetchone()
        return EditorialDraftArtifact.model_validate_json(row[0]) if row else None


class SQLiteDraftRulesRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def get(self, artifact_id: UUID) -> DraftRulesArtifact | None:
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM draft_rules_artifacts WHERE artifact_id = ?",
                (str(artifact_id),),
            ).fetchone()
        return DraftRulesArtifact.model_validate_json(row[0]) if row else None


class SQLiteIndependentReviewRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def get(self, artifact_id: UUID) -> IndependentReviewArtifact | None:
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM independent_review_artifacts "
                "WHERE artifact_id = ?",
                (str(artifact_id),),
            ).fetchone()
        return IndependentReviewArtifact.model_validate_json(row[0]) if row else None
