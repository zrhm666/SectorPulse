# ruff: noqa: E501
from datetime import UTC, datetime
from uuid import UUID

from sector_pulse.domain.review.review_analytics import ReviewMetrics, ReviewSummary
from sector_pulse.storage.sqlite.database import SQLiteDatabase


class ReviewAnalyticsQueries:
    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database
        self._database.initialize()

    def for_run(self, run_id: UUID) -> ReviewMetrics:
        with self._database.connection() as connection:
            patches = connection.execute("SELECT COUNT(*) FROM draft_patches WHERE run_id = ?", (str(run_id),)).fetchone()[0]
            governance = connection.execute("SELECT COUNT(*) FROM governance_checks WHERE draft_id IN (SELECT draft_id FROM draft_patches WHERE run_id = ?)", (str(run_id),)).fetchone()[0]
            approvals = connection.execute("SELECT COUNT(*) FROM draft_approvals WHERE run_id = ? AND status = 'APPROVED_FOR_COPY'", (str(run_id),)).fetchone()[0]
            exports = connection.execute("SELECT COUNT(*) FROM draft_exports WHERE run_id = ?", (str(run_id),)).fetchone()[0]
            audit_times = connection.execute(
                """SELECT event_type, created_at FROM audit_events
                   WHERE run_id = ? ORDER BY created_at""",
                (str(run_id),),
            ).fetchall()
            llm_cost = connection.execute(
                "SELECT COALESCE(SUM(estimated_cost_cny), 0) FROM agent_invocations WHERE run_id = ?",
                (str(run_id),),
            ).fetchone()[0]
        duration = 0.0
        if audit_times:
            started = datetime.fromisoformat(audit_times[0][1])
            terminal = next(
                (item for item in audit_times if item[0] in {"APPROVED", "REVOKED"}),
                None,
            )
            if terminal is not None:
                duration = max(0.0, (datetime.fromisoformat(terminal[1]) - started).total_seconds())
        return ReviewMetrics(
            run_id=str(run_id), review_duration_seconds=duration, patch_count=patches,
            revision_rounds=patches, governance_failures=governance,
            approval_count=approvals, export_count=exports, llm_cost_cny=float(llm_cost),
        )

    def summary(self, from_at: datetime, to_at: datetime) -> ReviewSummary:
        from_at = from_at.astimezone(UTC)
        to_at = to_at.astimezone(UTC)
        with self._database.connection() as connection:
            runs = connection.execute("SELECT COUNT(DISTINCT run_id) FROM audit_events WHERE created_at >= ? AND created_at < ?", (from_at.isoformat(), to_at.isoformat())).fetchone()[0]
            approvals = connection.execute("SELECT COUNT(*) FROM audit_events WHERE event_type = 'APPROVED' AND created_at >= ? AND created_at < ?", (from_at.isoformat(), to_at.isoformat())).fetchone()[0]
            patches = connection.execute("SELECT COUNT(*) FROM draft_patches WHERE created_at >= ? AND created_at < ?", (from_at.isoformat(), to_at.isoformat())).fetchone()[0]
            failures = connection.execute("SELECT COUNT(*) FROM governance_checks WHERE status = 'FAIL' AND created_at >= ? AND created_at < ?", (from_at.isoformat(), to_at.isoformat())).fetchone()[0]
            exports = connection.execute("SELECT COUNT(*) FROM draft_exports WHERE created_at >= ? AND created_at < ?", (from_at.isoformat(), to_at.isoformat())).fetchone()[0]
        return ReviewSummary(from_at=from_at, to_at=to_at, runs=runs, approval_rate=(approvals / runs if runs else 0), patch_count=patches, governance_failures=failures, export_count=exports, review_duration_seconds=0)
