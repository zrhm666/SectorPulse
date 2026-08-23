# ruff: noqa: E501
import hashlib
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import text

from sector_pulse.domain.article import ArticleDraft, ArticleOutline
from sector_pulse.domain.attribution import (
    AttributionContext,
    AttributionGateResult,
    SectorAnalysisCard,
)
from sector_pulse.domain.review import ReviewReport
from sector_pulse.storage.phase1b_repository import ImmutableDraftVersionError
from sector_pulse.storage.postgres import PostgresDatabase


def _hash(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()


class PostgresPhase1BRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    async def save_contexts(self, contexts: Sequence[AttributionContext]) -> None:
        async with self._database.engine.begin() as connection:
            for item in contexts:
                await self._upsert(connection, "attribution_contexts",
                                   "run_id, sector_id, sector_kind", str(item.run_id),
                                   item.sector_id, item.sector_kind.value, item.model_dump_json())

    async def save_gate_results(self, results: Sequence[AttributionGateResult]) -> None:
        async with self._database.engine.begin() as connection:
            for item in results:
                payload = item.model_dump_json()
                await connection.execute(
                    text("INSERT INTO attribution_gate_results (run_id, sector_id, payload_json, payload_hash) "
                         "VALUES (:run_id, :sector_id, :payload, :hash) "
                         "ON CONFLICT (run_id, sector_id) DO UPDATE SET payload_json = EXCLUDED.payload_json, "
                         "payload_hash = EXCLUDED.payload_hash"),
                    {"run_id": str(item.run_id), "sector_id": item.sector_id,
                     "payload": payload, "hash": _hash(payload)},
                )

    async def save_cards(self, cards: Sequence[SectorAnalysisCard]) -> None:
        async with self._database.engine.begin() as connection:
            for item in cards:
                payload = item.model_dump_json()
                await connection.execute(
                    text("INSERT INTO sector_analysis_cards (run_id, sector_id, sector_kind, payload_json, payload_hash) "
                         "VALUES (:run_id, :sector_id, :sector_kind, :payload, :hash) "
                         "ON CONFLICT (run_id, sector_id, sector_kind) DO UPDATE SET payload_json = EXCLUDED.payload_json, "
                         "payload_hash = EXCLUDED.payload_hash"),
                    {"run_id": str(item.run_id), "sector_id": item.sector_id,
                     "sector_kind": item.sector_kind.value, "payload": payload, "hash": _hash(payload)},
                )
                for claim in item.claims:
                    claim_payload = claim.model_dump_json()
                    await connection.execute(
                        text("INSERT INTO claims (run_id, claim_id, payload_json, payload_hash) "
                             "VALUES (:run_id, :claim_id, :payload, :hash) "
                             "ON CONFLICT (run_id, claim_id) DO UPDATE SET payload_json = EXCLUDED.payload_json, "
                             "payload_hash = EXCLUDED.payload_hash"),
                        {"run_id": str(item.run_id), "claim_id": claim.claim_id,
                         "payload": claim_payload, "hash": _hash(claim_payload)},
                    )

    async def save_outline(self, outline: ArticleOutline) -> None:
        payload = outline.model_dump_json()
        async with self._database.engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO article_outlines (outline_id, run_id, payload_json, payload_hash) "
                     "VALUES (:outline_id, :run_id, :payload, :hash) "
                     "ON CONFLICT (outline_id) DO UPDATE SET payload_json = EXCLUDED.payload_json, "
                     "payload_hash = EXCLUDED.payload_hash"),
                {"outline_id": str(outline.outline_id), "run_id": str(outline.run_id),
                 "payload": payload, "hash": _hash(payload)},
            )

    async def save_draft(self, draft: ArticleDraft) -> None:
        payload = draft.model_dump_json()
        async with self._database.engine.begin() as connection:
            existing = await connection.execute(
                text("SELECT payload_json, payload_hash FROM article_drafts WHERE draft_id = :draft_id AND version = :version"),
                {"draft_id": str(draft.draft_id), "version": draft.version},
            )
            row = existing.first()
            if row is not None and row[1] != _hash(payload):
                previous = ArticleDraft.model_validate_json(row[0])
                if previous.model_copy(update={"status": draft.status}) != draft:
                    raise ImmutableDraftVersionError("draft version is immutable")
                await connection.execute(
                    text("UPDATE article_drafts SET status = :status, payload_json = :payload, payload_hash = :hash "
                         "WHERE draft_id = :draft_id AND version = :version"),
                    {"status": draft.status.value, "payload": payload, "hash": _hash(payload),
                     "draft_id": str(draft.draft_id), "version": draft.version},
                )
                return
            await connection.execute(
                text("INSERT INTO article_drafts (draft_id, run_id, version, status, payload_json, payload_hash) "
                     "VALUES (:draft_id, :run_id, :version, :status, :payload, :hash) ON CONFLICT DO NOTHING"),
                {"draft_id": str(draft.draft_id), "run_id": str(draft.run_id), "version": draft.version,
                 "status": draft.status.value, "payload": payload, "hash": _hash(payload)},
            )

    async def list_drafts(self, draft_id: UUID) -> tuple[ArticleDraft, ...]:
        return tuple(ArticleDraft.model_validate_json(p) for p in await self._payloads(
            "SELECT payload_json FROM article_drafts WHERE draft_id = :id ORDER BY version", {"id": str(draft_id)}
        ))

    async def get_contexts(self, run_id: UUID) -> tuple[AttributionContext, ...]:
        return tuple(AttributionContext.model_validate_json(p) for p in await self._payloads(
            "SELECT payload_json FROM attribution_contexts WHERE run_id = :id ORDER BY sector_id", {"id": str(run_id)}
        ))

    async def get_gates(self, run_id: UUID) -> tuple[AttributionGateResult, ...]:
        return tuple(AttributionGateResult.model_validate_json(p) for p in await self._payloads(
            "SELECT payload_json FROM attribution_gate_results WHERE run_id = :id ORDER BY sector_id", {"id": str(run_id)}
        ))

    async def get_cards(self, run_id: UUID) -> tuple[SectorAnalysisCard, ...]:
        return tuple(SectorAnalysisCard.model_validate_json(p) for p in await self._payloads(
            "SELECT payload_json FROM sector_analysis_cards WHERE run_id = :id ORDER BY sector_id", {"id": str(run_id)}
        ))

    async def get_outline(self, run_id: UUID) -> ArticleOutline | None:
        values = await self._payloads("SELECT payload_json FROM article_outlines WHERE run_id = :id", {"id": str(run_id)})
        return ArticleOutline.model_validate_json(values[0]) if values else None

    async def get_drafts(self, run_id: UUID) -> tuple[ArticleDraft, ...]:
        return tuple(ArticleDraft.model_validate_json(p) for p in await self._payloads(
            "SELECT payload_json FROM article_drafts WHERE run_id = :id ORDER BY version", {"id": str(run_id)}
        ))

    async def get_review(self, run_id: UUID) -> ReviewReport | None:
        values = await self._payloads(
            "SELECT rr.payload_json FROM review_reports rr JOIN article_drafts ad ON ad.draft_id = rr.draft_id "
            "AND ad.version = rr.draft_version WHERE ad.run_id = :id ORDER BY rr.draft_version DESC LIMIT 1",
            {"id": str(run_id)},
        )
        return ReviewReport.model_validate_json(values[0]) if values else None

    async def _payloads(self, statement: str, params: dict[str, object]) -> list[str]:
        async with self._database.engine.connect() as connection:
            result = await connection.execute(text(statement), params)
            return [row[0] for row in result.fetchall()]

    @staticmethod
    async def _upsert(connection, table: str, keys: str, run_id: str, sector_id: str,
                       sector_kind: str, payload: str) -> None:
        await connection.execute(
            text(f"INSERT INTO {table} ({keys}, payload_json, payload_hash) VALUES "
                 "(:run_id, :sector_id, :sector_kind, :payload, :hash) "
                 f"ON CONFLICT ({keys}) DO UPDATE SET payload_json = EXCLUDED.payload_json, "
                 "payload_hash = EXCLUDED.payload_hash"),
            {"run_id": run_id, "sector_id": sector_id, "sector_kind": sector_kind,
             "payload": payload, "hash": _hash(payload)},
        )
