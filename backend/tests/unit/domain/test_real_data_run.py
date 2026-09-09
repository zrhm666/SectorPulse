from uuid import uuid4

from sector_pulse.domain.runs.real_data_run import (
    RealDataRun,
    RealDataRunRequest,
    RealDataRunStatus,
)


def test_intraday_defaults_to_six_hour_lookback() -> None:
    request = RealDataRunRequest(mode="intraday")
    assert request.lookback_hours == 6


def test_post_close_defaults_to_twenty_four_hours() -> None:
    request = RealDataRunRequest(mode="post_close")
    assert request.lookback_hours == 24


def test_terminal_statuses_are_explicit() -> None:
    assert RealDataRunStatus.READY_FOR_ATTRIBUTION.is_terminal
    assert not RealDataRunStatus.FETCHING_NEWS.is_terminal


def test_retry_run_keeps_source_run_id() -> None:
    source_run_id = uuid4()
    run = RealDataRun(
        request=RealDataRunRequest(mode="intraday"),
        retry_of_run_id=source_run_id,
    )
    assert run.retry_of_run_id == source_run_id
