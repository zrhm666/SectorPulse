# ruff: noqa: E501
import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from sector_pulse.domain.article import ArticleDraft
from sector_pulse.domain.editing import DraftPatch
from sector_pulse.storage.draft_edit_repository import DraftVersionConflict
from sector_pulse.storage.postgres import PostgresDatabase
from sector_pulse.storage.postgres_phase1b_repository import PostgresPhase1BRepository


class PostgresDraftVersionConflict(DraftVersionConflict):
    pass


class PostgresDraftEditRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database
        self._drafts = PostgresPhase1BRepository(database)

    async def save_draft(self, draft: ArticleDraft) -> None:
        await self._drafts.save_draft(draft)

    async def get_version(self, draft_id: UUID, version: int) -> ArticleDraft:
        for draft in await self._drafts.list_drafts(draft_id):
            if draft.version == version:
                return draft
        raise KeyError(f"draft version not found: {draft_id}/{version}")

    async def latest_version(self, draft_id: UUID) -> ArticleDraft:
        versions = await self._drafts.list_drafts(draft_id)
        if not versions:
            raise KeyError(f"draft not found: {draft_id}")
        return versions[-1]

    async def latest_for_run(self, run_id: UUID) -> ArticleDraft:
        versions = await self._drafts.get_drafts(run_id)
        if not versions:
            raise KeyError(f"draft not found: {run_id}")
        return versions[-1]

    async def apply_patch(self, draft_id: UUID, base_version: int,
                          operations: tuple[DraftPatch, ...], *, actor: str) -> ArticleDraft:
        try:
            base = await self.get_version(draft_id, base_version)
            latest = await self.latest_version(draft_id)
        except KeyError as exc:
            raise PostgresDraftVersionConflict("draft base version is stale") from exc
        if latest.version != base_version:
            raise PostgresDraftVersionConflict("draft base version is stale")
        values: dict[str, Any] = base.model_dump()
        for operation in operations:
            current = self._read_path(values, operation.path)
            encoded = (current if isinstance(current, str) else json.dumps(current, ensure_ascii=False, sort_keys=True)).encode()
            if hashlib.sha256(encoded).hexdigest() != operation.old_value_hash:
                raise PostgresDraftVersionConflict(f"patch old value does not match: {operation.path}")
            self._write_path(values, operation.path, operation.value)
        result = ArticleDraft.model_validate({**values, "version": base.version + 1})
        await self._drafts.save_draft(result)
        async with self._database.engine.begin() as connection:
            for index, operation in enumerate(operations):
                payload = operation.model_dump(mode="json")
                await connection.execute(
                    text("INSERT INTO draft_patches (patch_id, draft_id, run_id, base_version, new_version, operation_index, operation_json, input_hash, output_hash, actor, created_at) "
                         "VALUES (:patch_id, :draft_id, :run_id, :base_version, :new_version, :operation_index, :operation_json, :input_hash, :output_hash, :actor, :created_at)"),
                    {"patch_id": str(operation.patch_id), "draft_id": str(result.draft_id), "run_id": str(result.run_id),
                     "base_version": base.version, "new_version": result.version, "operation_index": index,
                     "operation_json": json.dumps(payload, ensure_ascii=False, sort_keys=True),
                     "input_hash": operation.old_value_hash,
                     "output_hash": hashlib.sha256(json.dumps(operation.value, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                     "actor": actor, "created_at": datetime.now(UTC).isoformat()},
                )
        return result

    @staticmethod
    def _read_path(values: dict[str, Any], path: str) -> Any:
        parts = path.split("/")
        if len(parts) == 1:
            return values[parts[0]]
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
        if parts[0] == "sections" and len(parts) == 3:
            sections = list(values["sections"])
            for index, section in enumerate(sections):
                if section["section_id"] == parts[1]:
                    sections[index] = {**section, parts[2]: value}
                    values["sections"] = sections
                    return
        raise ValueError(f"unsupported edit path: {path}")
