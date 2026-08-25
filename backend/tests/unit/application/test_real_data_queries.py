from datetime import UTC, datetime

from sector_pulse.application.real_data_queries import RealDataRunQueries
from sector_pulse.domain.quality import QualityStatus
from sector_pulse.domain.real_data_run import (
    RealDataQualitySummary,
    RealDataRun,
    RealDataRunRequest,
    RealDataRunStatus,
)


def test_serializes_frontend_data_run_contract() -> None:
    requested_at = datetime(2026, 8, 23, 1, tzinfo=UTC)
    run = RealDataRun(
        provider="fixture",
        request=RealDataRunRequest(mode="post_close", requested_at=requested_at),
        status=RealDataRunStatus.DEGRADED,
        quality=RealDataQualitySummary(
            market_quality={"concept": QualityStatus.NORMAL},
            news_quality={"news": QualityStatus.DEGRADED},
            downgrade_reasons=("NEWS_SOURCE_PARTIAL",),
        ),
    )

    result = RealDataRunQueries._serialize(run)

    assert result["mode"] == "post_close"
    assert result["provider"] == "fixture"
    assert result["requested_at"] == requested_at.isoformat().replace("+00:00", "Z")
    assert result["request"]["lookback_hours"] == 24
    assert result["quality"] == {"concept": "NORMAL", "news": "DEGRADED"}
    assert result["quality_summary"]["cutoff_violation_count"] == 0
    assert result["downgrade_reasons"] == ["NEWS_SOURCE_PARTIAL"]
