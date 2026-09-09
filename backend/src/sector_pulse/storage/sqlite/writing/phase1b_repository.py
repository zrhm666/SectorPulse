import hashlib
import sqlite3
from collections.abc import Sequence
from uuid import UUID

from sector_pulse.domain.review.review import ReviewReport
from sector_pulse.domain.writing.article import ArticleDraft, ArticleOutline
from sector_pulse.domain.writing.attribution import (
    AttributionContext,
    AttributionGateResult,
    SectorAnalysisCard,
)
from sector_pulse.storage.sqlite.database import SQLiteDatabase


class ImmutableDraftVersionError(ValueError):
    pass


def _payload_hash(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SQLitePhase1BRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database
        self._database.initialize()

    def save_contexts(self, contexts: Sequence[AttributionContext]) -> None:
        with self._database.transaction() as connection:
            for context in contexts:
                payload = context.model_dump_json()
                connection.execute(
                    """INSERT OR REPLACE INTO attribution_contexts
                    (run_id, sector_id, sector_kind, payload_json, payload_hash)
                    VALUES (?, ?, ?, ?, ?)""",
                    (
                        str(context.run_id),
                        context.sector_id,
                        context.sector_kind.value,
                        payload,
                        _payload_hash(payload),
                    ),
                )

    def save_gate_results(self, results: Sequence[AttributionGateResult]) -> None:
        with self._database.transaction() as connection:
            for result in results:
                payload = result.model_dump_json()
                connection.execute(
                    """INSERT OR REPLACE INTO attribution_gate_results
                    (run_id, sector_id, payload_json, payload_hash) VALUES (?, ?, ?, ?)""",
                    (str(result.run_id), result.sector_id, payload, _payload_hash(payload)),
                )

    def save_cards(self, cards: Sequence[SectorAnalysisCard]) -> None:
        with self._database.transaction() as connection:
            for card in cards:
                payload = card.model_dump_json()
                connection.execute(
                    """INSERT OR REPLACE INTO sector_analysis_cards
                    (run_id, sector_id, sector_kind, payload_json, payload_hash)
                    VALUES (?, ?, ?, ?, ?)""",
                    (
                        str(card.run_id),
                        card.sector_id,
                        card.sector_kind.value,
                        payload,
                        _payload_hash(payload),
                    ),
                )
                for claim in card.claims:
                    claim_payload = claim.model_dump_json()
                    connection.execute(
                        """INSERT OR REPLACE INTO claims
                        (run_id, claim_id, payload_json, payload_hash) VALUES (?, ?, ?, ?)""",
                        (
                            str(card.run_id),
                            claim.claim_id,
                            claim_payload,
                            _payload_hash(claim_payload),
                        ),
                    )

    def save_outline(self, outline: ArticleOutline) -> None:
        payload = outline.model_dump_json()
        with self._database.transaction() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO article_outlines
                (outline_id, run_id, payload_json, payload_hash) VALUES (?, ?, ?, ?)""",
                (str(outline.outline_id), str(outline.run_id), payload, _payload_hash(payload)),
            )

    def save_draft(self, draft: ArticleDraft) -> None:
        with self._database.transaction() as connection:
            self.save_draft_in_transaction(connection, draft)

    def save_draft_in_transaction(
        self, connection: sqlite3.Connection, draft: ArticleDraft
    ) -> None:
        """Persist on caller transaction; caller controls commit/rollback."""
        payload = draft.model_dump_json()
        payload_hash = _payload_hash(payload)
        existing = connection.execute(
            "SELECT payload_json, payload_hash FROM article_drafts "
            "WHERE draft_id = ? AND version = ?",
            (str(draft.draft_id), draft.version),
        ).fetchone()
        if existing is not None and existing[1] != payload_hash:
            previous = ArticleDraft.model_validate_json(existing[0])
            same_content = previous.model_copy(update={"status": draft.status}) == draft
            if not same_content:
                raise ImmutableDraftVersionError("draft version is immutable")
            connection.execute(
                "UPDATE article_drafts SET status = ?, payload_json = ?, payload_hash = ? "
                "WHERE draft_id = ? AND version = ?",
                (
                    draft.status.value,
                    payload,
                    payload_hash,
                    str(draft.draft_id),
                    draft.version,
                ),
            )
            return
        connection.execute(
            """INSERT OR IGNORE INTO article_drafts
            (draft_id, run_id, version, status, payload_json, payload_hash)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                str(draft.draft_id),
                str(draft.run_id),
                draft.version,
                draft.status.value,
                payload,
                payload_hash,
            ),
        )
        for section in draft.sections:
            section_payload = section.model_dump_json()
            connection.execute(
                """INSERT OR IGNORE INTO article_sections
                (draft_id, version, section_id, payload_json, payload_hash)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    str(draft.draft_id),
                    draft.version,
                    section.section_id,
                    section_payload,
                    _payload_hash(section_payload),
                ),
            )
        for source in draft.sources:
            source_payload = source.model_dump_json()
            connection.execute(
                """INSERT OR IGNORE INTO article_sources
                (draft_id, version, source_id, payload_json, payload_hash)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    str(draft.draft_id),
                    draft.version,
                    source.source_id,
                    source_payload,
                    _payload_hash(source_payload),
                ),
            )

    def save_review(self, report: ReviewReport) -> None:
        payload = report.model_dump_json()
        with self._database.transaction() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO review_reports
                (review_id, draft_id, draft_version, payload_json, payload_hash)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    report.review_id,
                    report.draft_id,
                    report.draft_version,
                    payload,
                    _payload_hash(payload),
                ),
            )
            for issue in report.issues:
                issue_payload = issue.model_dump_json()
                connection.execute(
                    """INSERT OR REPLACE INTO review_issues
                    (review_id, issue_id, payload_json, payload_hash)
                    VALUES (?, ?, ?, ?)""",
                    (report.review_id, issue.issue_id, issue_payload, _payload_hash(issue_payload)),
                )

    def list_drafts(self, draft_id: UUID) -> tuple[ArticleDraft, ...]:
        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM article_drafts WHERE draft_id = ? ORDER BY version",
                (str(draft_id),),
            ).fetchall()
        return tuple(ArticleDraft.model_validate_json(row[0]) for row in rows)

    # 只读查询：table 与 order_column 仅允许本类内固定字符串（attribution_contexts /
    # attribution_gate_results / sector_analysis_cards + sector_id），不接受外部输入以防注入。
    def _payloads_for(self, table: str, order_column: str, run_id: UUID) -> tuple[str, ...]:
        with self._database.connection() as connection:
            rows = connection.execute(
                f"SELECT payload_json FROM {table} WHERE run_id = ? ORDER BY {order_column}",
                (str(run_id),),
            ).fetchall()
        return tuple(row[0] for row in rows)

    def get_contexts(self, run_id: UUID) -> tuple[AttributionContext, ...]:
        return tuple(
            AttributionContext.model_validate_json(p)
            for p in self._payloads_for("attribution_contexts", "sector_id", run_id)
        )

    def get_gates(self, run_id: UUID) -> tuple[AttributionGateResult, ...]:
        return tuple(
            AttributionGateResult.model_validate_json(p)
            for p in self._payloads_for("attribution_gate_results", "sector_id", run_id)
        )

    def get_cards(self, run_id: UUID) -> tuple[SectorAnalysisCard, ...]:
        return tuple(
            SectorAnalysisCard.model_validate_json(p)
            for p in self._payloads_for("sector_analysis_cards", "sector_id", run_id)
        )

    def get_outline(self, run_id: UUID) -> ArticleOutline | None:
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM article_outlines WHERE run_id = ?",
                (str(run_id),),
            ).fetchone()
        return ArticleOutline.model_validate_json(row[0]) if row else None

    def get_drafts(self, run_id: UUID) -> tuple[ArticleDraft, ...]:
        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM article_drafts WHERE run_id = ? ORDER BY version",
                (str(run_id),),
            ).fetchall()
        return tuple(ArticleDraft.model_validate_json(row[0]) for row in rows)

    def get_review(self, run_id: UUID) -> ReviewReport | None:
        with self._database.connection() as connection:
            row = connection.execute(
                """SELECT rr.payload_json FROM review_reports rr
                   JOIN article_drafts ad ON ad.draft_id = rr.draft_id
                   AND ad.version = rr.draft_version
                   WHERE ad.run_id = ? ORDER BY rr.draft_version DESC LIMIT 1""",
                (str(run_id),),
            ).fetchone()
        return ReviewReport.model_validate_json(row[0]) if row else None
