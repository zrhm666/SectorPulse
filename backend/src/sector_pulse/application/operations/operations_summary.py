from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal, Protocol

RunKind = Literal["content", "data"]

CONTENT_ACTIVE = frozenset({"RUNNING"})
CONTENT_SUCCESS = frozenset({"READY_FOR_HUMAN_REVIEW"})
CONTENT_ATTENTION = frozenset(
    {
        "READY_FOR_HUMAN_REVIEW",
        "REVISE_REQUIRED",
        "UNREVIEWED",
        "BUDGET_EXCEEDED",
        "ATTRIBUTION_BLOCKED",
        "DRAFT_GENERATION_FAILED",
        "FAILED",
    }
)
CONTENT_FAILED = frozenset(
    {
        "BUDGET_EXCEEDED",
        "ATTRIBUTION_BLOCKED",
        "DRAFT_GENERATION_FAILED",
        "FAILED",
    }
)

DATA_ACTIVE = frozenset(
    {
        "PREFLIGHT",
        "FETCHING_MARKET",
        "RANKING_PRE_CANDIDATES",
        "FETCHING_NEWS",
        "BUILDING_EVIDENCE",
    }
)
DATA_SUCCESS = frozenset({"READY_FOR_ATTRIBUTION", "DEGRADED"})
DATA_ATTENTION = frozenset({"DEGRADED", "BLOCKED", "FAILED", "INTERRUPTED"})
DATA_FAILED = frozenset({"BLOCKED", "FAILED", "INTERRUPTED"})


@dataclass(frozen=True)
class OperationalRun:
    run_id: str
    kind: RunKind
    mode: str
    status: str
    provider: str
    requested_at: datetime
    finished_at: datetime | None
    elapsed_ms: int | None
    total_cost_cny: Decimal | None
    candidate_count: int | None


@dataclass(frozen=True)
class RunClassification:
    active: bool
    completed: bool
    attention: bool
    failed: bool


@dataclass(frozen=True)
class OperationsCoreSummary:
    total: int
    completed_today: int
    active: int
    attention: int


@dataclass(frozen=True)
class OperationsTrendPoint:
    date: date
    total: int
    completed: int
    failed: int


@dataclass(frozen=True)
class OperationsTrend:
    available: bool
    reason: str | None
    points: tuple[OperationsTrendPoint, ...]


@dataclass(frozen=True)
class OperationsSnapshot:
    summary: OperationsCoreSummary
    trend: OperationsTrend
    recent_runs: tuple[OperationalRun, ...]


class OperationsSummaryQueryPort(Protocol):
    def list_records(
        self, *, since: datetime | None = None, limit: int | None = None
    ) -> list[OperationalRun]: ...


def classify_status(status: str, kind: RunKind) -> RunClassification:
    if kind == "content":
        return RunClassification(
            active=status in CONTENT_ACTIVE,
            completed=status in CONTENT_SUCCESS,
            attention=status in CONTENT_ATTENTION,
            failed=status in CONTENT_FAILED,
        )
    return RunClassification(
        active=status in DATA_ACTIVE,
        completed=status in DATA_SUCCESS,
        attention=status in DATA_ATTENTION,
        failed=status in DATA_FAILED,
    )


def build_operations_snapshot(
    records: Sequence[OperationalRun],
    *,
    now: datetime,
    days: int = 30,
    recent_limit: int = 10,
) -> OperationsSnapshot:
    if days < 1:
        raise ValueError("days must be at least 1")
    if recent_limit < 1:
        raise ValueError("recent_limit must be at least 1")

    today = _utc_date(now)
    ordered = sorted(records, key=lambda item: _as_utc(item.requested_at), reverse=True)
    classifications = [(record, classify_status(record.status, record.kind)) for record in records]
    summary = OperationsCoreSummary(
        total=len(records),
        completed_today=sum(
            classification.completed
            and record.finished_at is not None
            and _utc_date(record.finished_at) == today
            for record, classification in classifications
        ),
        active=sum(classification.active for _, classification in classifications),
        attention=sum(classification.attention for _, classification in classifications),
    )

    first_day = today - timedelta(days=days - 1)
    daily: dict[date, list[RunClassification]] = defaultdict(list)
    for record, classification in classifications:
        requested_day = _utc_date(record.requested_at)
        if first_day <= requested_day <= today:
            daily[requested_day].append(classification)

    if daily:
        points = tuple(
            OperationsTrendPoint(
                date=day,
                total=len(items),
                completed=sum(item.completed for item in items),
                failed=sum(item.failed for item in items),
            )
            for day, items in sorted(daily.items())
        )
        trend = OperationsTrend(available=True, reason=None, points=points)
    else:
        reason = (
            "当前还没有可用于趋势统计的运行记录"
            if not records
            else f"最近 {days} 天没有可用于趋势统计的运行记录"
        )
        trend = OperationsTrend(available=False, reason=reason, points=())

    return OperationsSnapshot(
        summary=summary,
        trend=trend,
        recent_runs=tuple(ordered[:recent_limit]),
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _utc_date(value: datetime) -> date:
    return _as_utc(value).date()
