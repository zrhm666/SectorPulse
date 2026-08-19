from datetime import UTC, datetime, timedelta

from sector_pulse.application.review_analytics import ReviewAnalyticsQueries
from sector_pulse.storage.sqlite import SQLiteDatabase


def test_summary_empty_range_is_zero(tmp_path) -> None:
    queries = ReviewAnalyticsQueries(SQLiteDatabase(tmp_path / 'analytics.db'))
    start = datetime.now(UTC)
    result = queries.summary(start, start + timedelta(hours=1))
    assert result.runs == 0
    assert result.approval_rate == 0
