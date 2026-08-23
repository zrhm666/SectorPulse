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
    assert result["requested_at"] == requested_at.isoformat().replace("+00:00", "Z")
    assert result["quality"] == {"concept": "NORMAL", "news": "DEGRADED"}
    assert result["downgrade_reasons"] == ["NEWS_SOURCE_PARTIAL"]
    assert "request" not in result
