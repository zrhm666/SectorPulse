from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text

from sector_pulse.domain.review_analytics import ReviewMetrics, ReviewSummary
from sector_pulse.storage.postgres import PostgresDatabase


class PostgresReviewAnalyticsQueries:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    async def for_run(self, run_id: UUID) -> ReviewMetrics:
        async with self._database.engine.connect() as connection:
            counts = {}
            queries = {
                "patches": "SELECT COUNT(*) FROM draft_patches WHERE run_id = :run_id",
                "governance": "SELECT COUNT(*) FROM governance_checks WHERE draft_id IN (SELECT draft_id FROM draft_patches WHERE run_id = :run_id)",
                "approvals": "SELECT COUNT(*) FROM draft_approvals WHERE run_id = :run_id AND status = 'APPROVED_FOR_COPY'",
                "exports": "SELECT COUNT(*) FROM draft_exports WHERE run_id = :run_id",
                "cost": "SELECT COALESCE(SUM(estimated_cost_cny), 0) FROM agent_invocations WHERE run_id = :run_id",
            }
            for key, statement in queries.items():
                counts[key] = (await connection.execute(text(statement), {"run_id": str(run_id)})).scalar_one()
            events = await connection.execute(
                text("SELECT event_type, created_at FROM audit_events WHERE run_id = :run_id ORDER BY created_at"),
                {"run_id": str(run_id)},
            )
            audit_times = events.fetchall()
        duration = 0.0
        if audit_times:
            started = datetime.fromisoformat(audit_times[0][1])
            terminal = next((item for item in audit_times if item[0] in {"APPROVED", "REVOKED"}), None)
            if terminal:
                duration = max(0.0, (datetime.fromisoformat(terminal[1]) - started).total_seconds())
        return ReviewMetrics(
            run_id=str(run_id), review_duration_seconds=duration, patch_count=counts["patches"],
            revision_rounds=counts["patches"], governance_failures=counts["governance"],
            approval_count=counts["approvals"], export_count=counts["exports"],
            llm_cost_cny=float(counts["cost"]),
        )

    async def summary(self, from_at: datetime, to_at: datetime) -> ReviewSummary:
        from_at, to_at = from_at.astimezone(UTC), to_at.astimezone(UTC)
        async with self._database.engine.connect() as connection:
            values = []
            for statement in (
                "SELECT COUNT(DISTINCT run_id) FROM audit_events WHERE created_at >= :from_at AND created_at < :to_at",
                "SELECT COUNT(*) FROM audit_events WHERE event_type = 'APPROVED' AND created_at >= :from_at AND created_at < :to_at",
                "SELECT COUNT(*) FROM draft_patches WHERE created_at >= :from_at AND created_at < :to_at",
                "SELECT COUNT(*) FROM governance_checks WHERE status = 'FAIL' AND created_at >= :from_at AND created_at < :to_at",
                "SELECT COUNT(*) FROM draft_exports WHERE created_at >= :from_at AND created_at < :to_at",
            ):
                values.append((await connection.execute(text(statement), {"from_at": from_at.isoformat(), "to_at": to_at.isoformat()})).scalar_one())
        runs, approvals, patches, failures, exports = values
        return ReviewSummary(
            from_at=from_at, to_at=to_at, runs=runs, approval_rate=approvals / runs if runs else 0,
            patch_count=patches, governance_failures=failures, export_count=exports,
            review_duration_seconds=0,
        )
