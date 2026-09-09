import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sector_pulse.domain.review.editing import DraftPatch
from sector_pulse.domain.writing.article import ArticleDraft, DraftStatus
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.writing.phase1b_repository import SQLitePhase1BRepository


class DraftVersionConflict(ValueError):
    pass


class SQLiteDraftEditRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database
        self._drafts = SQLitePhase1BRepository(database)

    def save_draft(self, draft: ArticleDraft) -> None:
        self._drafts.save_draft(draft)

    def get_version(self, draft_id: UUID, version: int) -> ArticleDraft:
        for draft in self._drafts.list_drafts(draft_id):
            if draft.version == version:
                return draft
        raise KeyError(f"draft version not found: {draft_id}/{version}")

    def latest_version(self, draft_id: UUID) -> ArticleDraft:
        versions = self._drafts.list_drafts(draft_id)
        if not versions:
            raise KeyError(f"draft not found: {draft_id}")
        return versions[-1]

    def latest_for_run(self, run_id: UUID) -> ArticleDraft:
        versions = self._drafts.get_drafts(run_id)
        if not versions:
            raise KeyError(f"draft not found: {run_id}")
        return versions[-1]

    def apply_patch(
        self,
        draft_id: UUID,
        base_version: int,
        operations: tuple[DraftPatch, ...],
        *,
        actor: str,
    ) -> ArticleDraft:
        with self._database.transaction() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT version, payload_json FROM article_drafts "
                "WHERE draft_id = ? ORDER BY version DESC LIMIT 1",
                (str(draft_id),),
            ).fetchone()
            if row is None or row[0] != base_version:
                raise DraftVersionConflict("draft base version is stale")
            base = ArticleDraft.model_validate_json(row[1])
            values: dict[str, Any] = base.model_dump()
            for operation in operations:
                current = self._read_path(values, operation.path)
                current_hash = hashlib.sha256(
                    json.dumps(current, ensure_ascii=False, sort_keys=True).encode("utf-8")
                    if not isinstance(current, str)
                    else current.encode("utf-8")
                ).hexdigest()
                if current_hash != operation.old_value_hash:
                    raise DraftVersionConflict(f"patch old value does not match: {operation.path}")
                self._write_path(values, operation.path, operation.value)
            values["status"] = DraftStatus.UNREVIEWED
            values["character_count"] = (
                len(values["introduction"])
                + len(values["conclusion"])
                + sum(len(section["body"]) for section in values["sections"])
            )
            for section in values["sections"]:
                section["character_count"] = len(section["body"])
            result = ArticleDraft.model_validate({**values, "version": base.version + 1})
            self._drafts.save_draft_in_transaction(connection, result)
            now = datetime.now(UTC).isoformat()
            for index, operation in enumerate(operations):
                payload = operation.model_dump(mode="json")
                connection.execute(
                    """INSERT INTO draft_patches
                    (patch_id, draft_id, run_id, base_version, new_version, operation_index,
                     operation_json, input_hash, output_hash, actor, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(operation.patch_id),
                        str(result.draft_id),
                        str(result.run_id),
                        base.version,
                        result.version,
                        index,
                        json.dumps(payload, ensure_ascii=False, sort_keys=True),
                        operation.old_value_hash,
                        hashlib.sha256(
                            json.dumps(operation.value, ensure_ascii=False, sort_keys=True).encode()
                        ).hexdigest(),
                        actor,
                        now,
                    ),
                )
        return result

    @staticmethod
    def _read_path(values: dict[str, Any], path: str) -> Any:
        parts = path.split("/")
        if len(parts) == 1:
            return values[parts[0]]
        if parts[0] == "titles" and len(parts) == 2:
            return values["titles"][int(parts[1])]
        if parts[0] == "sections" and len(parts) == 3:
            section = next(item for item in values["sections"] if item["section_id"] == parts[1])
            return section[parts[2]]
        raise ValueError(f"unsupported edit path: {path}")

    @staticmethod
    def _write_path(values: dict[str, Any], path: str, value: Any) -> None:
        parts = path.split("/")
        if len(parts) == 1:
            values[parts[0]] = value
            return
        if parts[0] == "titles" and len(parts) == 2:
            titles = list(values["titles"])
            titles[int(parts[1])] = value
            values["titles"] = titles
            return
        if parts[0] == "sections" and len(parts) == 3:
            sections = list(values["sections"])
            for index, section in enumerate(sections):
                if section["section_id"] == parts[1]:
                    sections[index] = {**section, parts[2]: value}
                    values["sections"] = sections
                    return
        raise ValueError(f"unsupported edit path: {path}")
