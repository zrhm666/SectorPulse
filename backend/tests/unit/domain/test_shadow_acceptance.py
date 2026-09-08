from datetime import UTC, date, datetime
from uuid import uuid4

from sector_pulse.domain.evaluation.shadow_acceptance import ShadowRun, ShadowRunStatus


def test_shadow_run_keeps_trading_date_and_status() -> None:
    item = ShadowRun(
        run_id=uuid4(), trading_date=date(2026, 8, 20), mode="intraday",
        status=ShadowRunStatus.STARTED, created_at=datetime.now(UTC),
    )
    assert item.trading_date.isoformat() == "2026-08-20"
    assert item.status is ShadowRunStatus.STARTED
