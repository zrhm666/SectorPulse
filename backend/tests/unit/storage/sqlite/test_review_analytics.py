# ruff: noqa: E501
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.review.review_analytics import ReviewAnalyticsQueries


def test_summary_empty_range_is_zero(tmp_path) -> None:
    queries = ReviewAnalyticsQueries(SQLiteDatabase(tmp_path / 'analytics.db'))
    start = datetime.now(UTC)
    result = queries.summary(start, start + timedelta(hours=1))
    assert result.runs == 0
    assert result.approval_rate == 0


def test_run_metrics_calculates_duration_and_llm_cost(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / 'analytics.db')
    database.initialize()
    run_id = uuid4()
    draft_id = uuid4()
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO audit_events (event_id, run_id, draft_id, version, event_type, actor, payload_json, created_at) VALUES (?, ?, ?, 1, 'PATCHED', 'u', '{}', ?)",
            (str(uuid4()), str(run_id), str(draft_id), '2026-08-20T10:00:00+00:00'),
        )
        connection.execute(
            "INSERT INTO audit_events (event_id, run_id, draft_id, version, event_type, actor, payload_json, created_at) VALUES (?, ?, ?, 1, 'APPROVED', 'u', '{}', ?)",
            (str(uuid4()), str(run_id), str(draft_id), '2026-08-20T10:02:30+00:00'),
        )
        connection.execute(
            "INSERT INTO agent_invocations (invocation_id, run_id, stage, provider_id, model, prompt_id, prompt_version, input_hash, output_hash, status, prompt_tokens, completion_tokens, total_tokens, estimated_cost_cny, error_code) VALUES (?, ?, 'writing', 'test', 'm', 'p', 1, 'i', 'o', 'SUCCESS', 1, 1, 2, '1.25', NULL)",
            (str(uuid4()), str(run_id)),
        )
    result = ReviewAnalyticsQueries(database).for_run(run_id)
    assert result.review_duration_seconds == 150
    assert result.llm_cost_cny == 1.25
