from sector_pulse.application.progress import NoopProgressSink


def test_noop_sink_does_not_raise() -> None:
    NoopProgressSink().emit("phase1b.start", {"run_id": "1"})
