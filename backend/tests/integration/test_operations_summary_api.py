from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sector_pulse.domain.runs.real_data_run import RealDataRun, RealDataRunRequest
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.runs.phase1b_runs_repository import (
    Phase1BRunRow,
    SQLitePhase1BRunsRepository,
)
from sector_pulse.storage.sqlite.runs.real_data_run_repository import SQLiteRealDataRunRepository
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


def test_operations_summary_reports_the_agent_engine_and_leaves_unknown_cost_unknown(
    tmp_path,
) -> None:
    """A multi-agent run must be visible to operations without inventing a cost.

    The orchestration snapshot records no wall-clock duration and no settled
    price while a call is still unpriced, so the projection has to say "unknown"
    rather than default to zero.
    """
    from sector_pulse.domain.orchestration.models import (
        BudgetLedger,
        BudgetReservation,
        RunSnapshot,
        TaskRecord,
        TaskStatus,
    )
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    database_path = tmp_path / "operations-with-agent-run.db"
    database = SQLiteDatabase(database_path)
    database.initialize()
    requested_at = datetime.now(UTC)
    run_id = uuid4()
    SQLiteOrchestrationRepository(database).save(
        RunSnapshot(
            run_id=run_id,
            requested_at=requested_at,
            deadline=requested_at + timedelta(minutes=10),
            tasks=(
                TaskRecord(
                    task_id=uuid4(),
                    role="A0",
                    scope="分析半导体板块",
                    status=TaskStatus.WAITING_USER_REVIEW,
                ),
            ),
            ledger=BudgetLedger(
                reservations=(BudgetReservation(call_id="m1", reserved_tokens=10),),
            ),
        ),
        -1,
        "run.created",
    )
    client = TestClient(create_app(database_path=database_path))

    response = client.get("/api/operations/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["total"] == 1
    assert payload["summary"]["attention"] == 1
    runs = payload["recent_runs"]
    assert len(runs) == 1
    assert runs[0]["run_id"] == str(run_id)
    assert runs[0]["execution_engine"] == "multi_agent"
    assert runs[0]["mode"] == "多 Agent 分析"
    assert runs[0]["status"] == "WAITING_USER_REVIEW"
    assert runs[0]["total_cost_cny"] is None
    assert runs[0]["elapsed_ms"] is None
    assert runs[0]["detail_path"] == f"/runs/{run_id}"
