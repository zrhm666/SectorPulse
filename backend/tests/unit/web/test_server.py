from sector_pulse.web import server


def test_server_uses_loopback_and_built_spa(monkeypatch) -> None:
    captured = {}

    def fake_run(app, **kwargs):
        captured.update(kwargs)
        assert app.title == "SectorPulse Web"

    monkeypatch.setattr(server.uvicorn, "run", fake_run)
    server.main()

    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8000
    assert "%(asctime)s" in captured["log_config"]["formatters"]["default"]["fmt"]
    assert "%(asctime)s" in captured["log_config"]["formatters"]["access"]["fmt"]
