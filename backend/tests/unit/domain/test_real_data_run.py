from sector_pulse.domain.real_data_run import RealDataRunRequest, RealDataRunStatus


def test_intraday_defaults_to_six_hour_lookback() -> None:
    request = RealDataRunRequest(mode="intraday")
    assert request.lookback_hours == 6


def test_post_close_defaults_to_twenty_four_hours() -> None:
    request = RealDataRunRequest(mode="post_close")
    assert request.lookback_hours == 24


def test_terminal_statuses_are_explicit() -> None:
    assert RealDataRunStatus.READY_FOR_ATTRIBUTION.is_terminal
    assert not RealDataRunStatus.FETCHING_NEWS.is_terminal
