# ruff: noqa: E501
import hashlib
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

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

    def save_contexts(self, contexts: Sequence[AttributionContext]) -> None:
        with self._database.start().begin() as connection:
            for item in contexts:
                self._upsert(connection, "attribution_contexts",
                                   "run_id, sector_id, sector_kind", str(item.run_id),
                                   item.sector_id, item.sector_kind.value, item.model_dump_json())

    def save_gate_results(self, results: Sequence[AttributionGateResult]) -> None:
        with self._database.start().begin() as connection:
            for item in results:
                payload = item.model_dump_json()
                connection.execute(
                    text("INSERT INTO attribution_gate_results (run_id, sector_id, payload_json, payload_hash) "
                         "VALUES (:run_id, :sector_id, :payload, :hash) "
                         "ON CONFLICT (run_id, sector_id) DO UPDATE SET payload_json = EXCLUDED.payload_json, "
                         "payload_hash = EXCLUDED.payload_hash"),
                    {"run_id": str(item.run_id), "sector_id": item.sector_id,
                     "payload": payload, "hash": _hash(payload)},
                )

    def save_cards(self, cards: Sequence[SectorAnalysisCard]) -> None:
        with self._database.start().begin() as connection:
            for item in cards:
                payload = item.model_dump_json()
                connection.execute(
                    text("INSERT INTO sector_analysis_cards (run_id, sector_id, sector_kind, payload_json, payload_hash) "
                         "VALUES (:run_id, :sector_id, :sector_kind, :payload, :hash) "
                         "ON CONFLICT (run_id, sector_id, sector_kind) DO UPDATE SET payload_json = EXCLUDED.payload_json, "
                         "payload_hash = EXCLUDED.payload_hash"),
                    {"run_id": str(item.run_id), "sector_id": item.sector_id,
                     "sector_kind": item.sector_kind.value, "payload": payload, "hash": _hash(payload)},
                )
                for claim in item.claims:
                    claim_payload = claim.model_dump_json()
                    connection.execute(
                        text("INSERT INTO claims (run_id, claim_id, payload_json, payload_hash) "
                             "VALUES (:run_id, :claim_id, :payload, :hash) "
                             "ON CONFLICT (run_id, claim_id) DO UPDATE SET payload_json = EXCLUDED.payload_json, "
                             "payload_hash = EXCLUDED.payload_hash"),
                        {"run_id": str(item.run_id), "claim_id": claim.claim_id,
                         "payload": claim_payload, "hash": _hash(claim_payload)},
                    )

    def save_outline(self, outline: ArticleOutline) -> None:
        payload = outline.model_dump_json()
        with self._database.start().begin() as connection:
            connection.execute(
                text("INSERT INTO article_outlines (outline_id, run_id, payload_json, payload_hash) "
                     "VALUES (:outline_id, :run_id, :payload, :hash) "
                     "ON CONFLICT (outline_id) DO UPDATE SET payload_json = EXCLUDED.payload_json, "
                     "payload_hash = EXCLUDED.payload_hash"),
                {"outline_id": str(outline.outline_id), "run_id": str(outline.run_id),
                 "payload": payload, "hash": _hash(payload)},
            )

    def save_draft(self, draft: ArticleDraft) -> None:
        payload = draft.model_dump_json()
        with self._database.start().begin() as connection:
            existing = connection.execute(
                text("SELECT payload_json, payload_hash FROM article_drafts WHERE draft_id = :draft_id AND version = :version"),
                {"draft_id": str(draft.draft_id), "version": draft.version},
            )
            row = existing.first()
            if row is not None and row[1] != _hash(payload):
                previous = ArticleDraft.model_validate_json(row[0])
                if previous.model_copy(update={"status": draft.status}) != draft:
                    raise ImmutableDraftVersionError("draft version is immutable")
                connection.execute(
                    text("UPDATE article_drafts SET status = :status, payload_json = :payload, payload_hash = :hash "
                         "WHERE draft_id = :draft_id AND version = :version"),
                    {"status": draft.status.value, "payload": payload, "hash": _hash(payload),
                     "draft_id": str(draft.draft_id), "version": draft.version},
                )
                return
            connection.execute(
                text("INSERT INTO article_drafts (draft_id, run_id, version, status, payload_json, payload_hash) "
                     "VALUES (:draft_id, :run_id, :version, :status, :payload, :hash) ON CONFLICT DO NOTHING"),
                {"draft_id": str(draft.draft_id), "run_id": str(draft.run_id), "version": draft.version,
                 "status": draft.status.value, "payload": payload, "hash": _hash(payload)},
            )

    def save_review(self, report: ReviewReport) -> None:
        payload = report.model_dump_json()
        with self._database.start().begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO review_reports "
                    "(review_id, draft_id, draft_version, payload_json, payload_hash) "
                    "VALUES (:review_id, :draft_id, :draft_version, :payload, :hash) "
                    "ON CONFLICT (review_id) DO UPDATE SET "
                    "draft_id = EXCLUDED.draft_id, "
                    "draft_version = EXCLUDED.draft_version, "
                    "payload_json = EXCLUDED.payload_json, "
                    "payload_hash = EXCLUDED.payload_hash"
                ),
                {
                    "review_id": report.review_id,
                    "draft_id": report.draft_id,
                    "draft_version": report.draft_version,
                    "payload": payload,
                    "hash": _hash(payload),
                },
            )
            for issue in report.issues:
                issue_payload = issue.model_dump_json()
                connection.execute(
                    text(
                        "INSERT INTO review_issues "
                        "(review_id, issue_id, payload_json, payload_hash) "
                        "VALUES (:review_id, :issue_id, :payload, :hash) "
                        "ON CONFLICT (review_id, issue_id) DO UPDATE SET "
                        "payload_json = EXCLUDED.payload_json, "
                        "payload_hash = EXCLUDED.payload_hash"
                    ),
                    {
                        "review_id": report.review_id,
                        "issue_id": issue.issue_id,
                        "payload": issue_payload,
                        "hash": _hash(issue_payload),
                    },
                )

    def list_drafts(self, draft_id: UUID) -> tuple[ArticleDraft, ...]:
        return tuple(ArticleDraft.model_validate_json(p) for p in self._payloads(
            "SELECT payload_json FROM article_drafts WHERE draft_id = :id ORDER BY version", {"id": str(draft_id)}
        ))

    def get_contexts(self, run_id: UUID) -> tuple[AttributionContext, ...]:
        return tuple(AttributionContext.model_validate_json(p) for p in self._payloads(
            "SELECT payload_json FROM attribution_contexts WHERE run_id = :id ORDER BY sector_id", {"id": str(run_id)}
        ))

    def get_gates(self, run_id: UUID) -> tuple[AttributionGateResult, ...]:
        return tuple(AttributionGateResult.model_validate_json(p) for p in self._payloads(
            "SELECT payload_json FROM attribution_gate_results WHERE run_id = :id ORDER BY sector_id", {"id": str(run_id)}
        ))

    def get_cards(self, run_id: UUID) -> tuple[SectorAnalysisCard, ...]:
        return tuple(SectorAnalysisCard.model_validate_json(p) for p in self._payloads(
            "SELECT payload_json FROM sector_analysis_cards WHERE run_id = :id ORDER BY sector_id", {"id": str(run_id)}
        ))

    def get_outline(self, run_id: UUID) -> ArticleOutline | None:
        values = self._payloads("SELECT payload_json FROM article_outlines WHERE run_id = :id", {"id": str(run_id)})
        return ArticleOutline.model_validate_json(values[0]) if values else None

    def get_drafts(self, run_id: UUID) -> tuple[ArticleDraft, ...]:
        return tuple(ArticleDraft.model_validate_json(p) for p in self._payloads(
            "SELECT payload_json FROM article_drafts WHERE run_id = :id ORDER BY version", {"id": str(run_id)}
        ))

    def get_review(self, run_id: UUID) -> ReviewReport | None:
        values = self._payloads(
            "SELECT rr.payload_json FROM review_reports rr JOIN article_drafts ad ON ad.draft_id = rr.draft_id "
            "AND ad.version = rr.draft_version WHERE ad.run_id = :id ORDER BY rr.draft_version DESC LIMIT 1",
            {"id": str(run_id)},
        )
        return ReviewReport.model_validate_json(values[0]) if values else None

    def _payloads(self, statement: str, params: dict[str, object]) -> list[str]:
        with self._database.start().connect() as connection:
            result = connection.execute(text(statement), params)
            return [row[0] for row in result.fetchall()]

    @staticmethod
    def _upsert(connection: Connection, table: str, keys: str, run_id: str, sector_id: str,
                       sector_kind: str, payload: str) -> None:
        connection.execute(
            text(f"INSERT INTO {table} ({keys}, payload_json, payload_hash) VALUES "
                 "(:run_id, :sector_id, :sector_kind, :payload, :hash) "
                 f"ON CONFLICT ({keys}) DO UPDATE SET payload_json = EXCLUDED.payload_json, "
                 "payload_hash = EXCLUDED.payload_hash"),
            {"run_id": run_id, "sector_id": sector_id, "sector_kind": sector_kind,
             "payload": payload, "hash": _hash(payload)},
        )
