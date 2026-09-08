from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sector_pulse.application.operations.operations_summary import (
    OperationalRun,
    build_operations_snapshot,
)


def test_build_snapshot_unifies_content_and_data_runs() -> None:
    now = datetime(2026, 8, 27, 12, tzinfo=UTC)
    records = [
        OperationalRun(
            run_id="content-1",
            kind="content",
            mode="内容生成",
            status="READY_FOR_HUMAN_REVIEW",
            provider="live",
            requested_at=now,
            finished_at=now,
            elapsed_ms=1200,
            total_cost_cny=Decimal("0.4"),
            candidate_count=3,
        ),
        OperationalRun(
            run_id="data-1",
            kind="data",
            mode="盘后复盘",
            status="FETCHING_NEWS",
            provider="live",
            requested_at=now,
            finished_at=None,
            elapsed_ms=None,
            total_cost_cny=None,
            candidate_count=12,
        ),
        OperationalRun(
            run_id="data-2",
            kind="data",
            mode="盘中分析",
            status="FAILED",
            provider="live",
            requested_at=now,
            finished_at=now,
            elapsed_ms=900,
            total_cost_cny=None,
            candidate_count=0,
        ),
    ]

    snapshot = build_operations_snapshot(records, now=now)

    assert snapshot.summary.total == 3
    assert snapshot.summary.completed_today == 1
    assert snapshot.summary.active == 1
    assert snapshot.summary.attention == 2
    assert [item.run_id for item in snapshot.recent_runs] == [
        "content-1",
        "data-1",
        "data-2",
    ]


def test_empty_snapshot_explains_absent_trend() -> None:
    snapshot = build_operations_snapshot(
        [], now=datetime(2026, 8, 27, tzinfo=UTC)
    )

    assert snapshot.trend.available is False
    assert snapshot.trend.reason == "当前还没有可用于趋势统计的运行记录"
    assert snapshot.trend.points == ()


def test_snapshot_groups_real_history_without_filling_fake_days() -> None:
    now = datetime(2026, 8, 27, 12, tzinfo=UTC)
    records = [
        OperationalRun(
            run_id="success",
            kind="data",
            mode="盘后复盘",
            status="READY_FOR_ATTRIBUTION",
            provider="live",
            requested_at=now - timedelta(days=2),
            finished_at=now - timedelta(days=2),
            elapsed_ms=600,
            total_cost_cny=None,
            candidate_count=8,
        ),
        OperationalRun(
            run_id="failed",
            kind="content",
            mode="内容生成",
            status="DRAFT_GENERATION_FAILED",
            provider="live",
            requested_at=now,
            finished_at=now,
            elapsed_ms=800,
            total_cost_cny=Decimal("0.2"),
            candidate_count=2,
        ),
    ]

    snapshot = build_operations_snapshot(records, now=now)

    assert [point.date.isoformat() for point in snapshot.trend.points] == [
        "2026-08-25",
        "2026-08-27",
    ]
    assert [
        (point.total, point.completed, point.failed)
        for point in snapshot.trend.points
    ] == [(1, 1, 0), (1, 0, 1)]


def test_snapshot_excludes_records_outside_the_requested_window() -> None:
    now = datetime(2026, 8, 27, 12, tzinfo=UTC)
    old_record = OperationalRun(
        run_id="old",
        kind="content",
        mode="内容生成",
        status="READY_FOR_HUMAN_REVIEW",
        provider="fixture",
        requested_at=now - timedelta(days=31),
        finished_at=now - timedelta(days=31),
        elapsed_ms=100,
        total_cost_cny=Decimal("0"),
        candidate_count=1,
    )

    snapshot = build_operations_snapshot([old_record], now=now, days=30)

    assert snapshot.summary.total == 1
    assert snapshot.trend.available is False
    assert snapshot.trend.reason == "最近 30 天没有可用于趋势统计的运行记录"
    assert snapshot.recent_runs[0].run_id == "old"
