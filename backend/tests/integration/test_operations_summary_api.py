from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sector_pulse.domain.real_data_run import RealDataRun, RealDataRunRequest
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.phase1b_runs_repository import (
    Phase1BRunRow,
    SQLitePhase1BRunsRepository,
)
from sector_pulse.storage.sqlite.real_data_run_repository import SQLiteRealDataRunRepository
from sector_pulse.web.app import create_app


def test_unstarted_scheduler_is_not_reported_as_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("SECTOR_PULSE_SCHEDULER_ENABLED", "true")
    client = TestClient(create_app(database_path=tmp_path / "not-started.db"))
    response = client.get("/api/operations/summary")
    assert response.status_code == 200
    assert response.json()["readiness"]["scheduler"]["status"] == "warning"


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
    assert payload["summary"] == {
        "total": 0,
        "completed_today": 0,
        "active": 0,
        "attention": 0,
    }
    assert payload["trend"] == {
        "available": False,
        "reason": "当前还没有可用于趋势统计的运行记录",
        "points": [],
    }
    assert set(payload["readiness"]) == {
        "database",
        "live_data",
        "llm",
        "scheduler",
    }
    assert payload["readiness"]["database"]["status"] == "ready"
    assert datetime.fromisoformat(payload["generated_at"])
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


def test_operations_summary_adds_real_unified_metrics_without_changing_legacy_runs(
    tmp_path,
) -> None:
    database_path = tmp_path / "operations-with-history.db"
    database = SQLiteDatabase(database_path)
    database.initialize()
    requested_at = datetime.now(UTC)
    content_id = uuid4()
    SQLitePhase1BRunsRepository(database).insert(
        Phase1BRunRow(
            run_id=content_id,
            requested_at=requested_at,
            provider="fixture",
            status="READY_FOR_HUMAN_REVIEW",
            elapsed_ms=1200,
            total_cost_cny="0.15",
            finished_at=requested_at + timedelta(seconds=2),
        )
    )
    data_run = RealDataRun(
        request=RealDataRunRequest(
            mode="post_close", requested_at=requested_at + timedelta(minutes=1)
        ),
        provider="live",
    )
    SQLiteRealDataRunRepository(database).insert(data_run)
    client = TestClient(create_app(database_path=database_path))

    response = client.get("/api/operations/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"] == {
        "total": 2,
        "completed_today": 1,
        "active": 1,
        "attention": 1,
    }
    assert payload["runs"]["total"] == 1
    assert payload["trend"]["available"] is True
    assert [item["kind"] for item in payload["recent_runs"]] == [
        "data",
        "content",
    ]
    assert payload["recent_runs"][0]["detail_path"] == (
        f"/data-runs/{data_run.run_id}"
    )
    assert payload["recent_runs"][1]["detail_path"] == f"/runs/{content_id}"
