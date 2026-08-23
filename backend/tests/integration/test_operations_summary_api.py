from fastapi.testclient import TestClient
from sector_pulse.web.app import create_app


def test_operations_summary_is_redacted_and_describes_empty_runtime(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SECTOR_PULSE_LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("SECTOR_PULSE_LLM_MODEL", "safe-model")
    monkeypatch.setenv("SECTOR_PULSE_LLM_API_KEY", "must-never-appear")
    client = TestClient(create_app(database_path=tmp_path / "operations.db"))

    response = client.get("/api/operations/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["database"]["backend"] == "sqlite"
    assert payload["llm"]["provider"] == "openai-compatible"
    assert payload["llm"]["model"] == "safe-model"
    assert payload["runs"]["total"] == 0
    assert "must-never-appear" not in response.text
    assert "api_key" not in payload["llm"]


def test_explicit_database_path_overrides_configured_postgres_url(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(
        "SECTOR_PULSE_DATABASE_URL",
        "postgresql+asyncpg://sectorpulse:secret@127.0.0.1:5432/sectorpulse",
    )
    client = TestClient(create_app(database_path=tmp_path / "isolated.db"))

    response = client.get("/api/operations/summary")

    assert response.status_code == 200
    assert response.json()["database"] == {"backend": "sqlite", "name": "isolated.db"}
