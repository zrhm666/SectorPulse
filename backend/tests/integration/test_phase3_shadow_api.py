# ruff: noqa: E501
from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from sector_pulse.web.app import create_app


def test_shadow_run_can_be_registered_and_listed(tmp_path) -> None:
    client = TestClient(create_app(database_path=tmp_path / "shadow.db"))
    run_id = uuid4()
    response = client.post("/api/shadow-runs", json={"run_id": str(run_id), "trading_date": "2026-08-20"})
    assert response.status_code == 201
    assert response.json()["run_id"] == str(run_id)
    listed = client.get("/api/shadow-runs")
    assert listed.status_code == 200
    assert listed.json()[0]["trading_date"] == date(2026, 8, 20).isoformat()


def test_shadow_acceptance_accepts_a_run_that_only_exists_in_the_agent_engine(
    tmp_path,
) -> None:
    """Shadow records are keyed by run id, not by a legacy row.

    A new-engine run has no `phase1b_runs`/`real_data_runs` row, so registering
    it must not depend on one — and its progress must count like any other.
    """
    from datetime import UTC, datetime, timedelta

    from sector_pulse.domain.orchestration.models import RunSnapshot, TaskRecord, TaskStatus
    from sector_pulse.storage.sqlite.database import SQLiteDatabase
    from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository

    database_path = tmp_path / "shadow-agent.db"
    database = SQLiteDatabase(database_path)
    database.initialize()
    observed_at = datetime(2026, 8, 20, 9, tzinfo=UTC)
    run_id = uuid4()
    SQLiteOrchestrationRepository(database).save(
        RunSnapshot(
            run_id=run_id,
            requested_at=observed_at,
            deadline=observed_at + timedelta(minutes=10),
            tasks=(
                TaskRecord(
                    task_id=uuid4(),
                    role="A0",
                    scope="分析半导体板块",
                    status=TaskStatus.WAITING_USER_REVIEW,
                ),
            ),
        ),
        -1,
        "run.created",
    )
    client = TestClient(create_app(database_path=database_path))

    created = client.post(
        "/api/shadow-runs", json={"run_id": str(run_id), "trading_date": "2026-08-20"}
    )
    progress = client.get("/api/shadow-runs/summary")

    assert created.status_code == 201
    assert created.json()["run_id"] == str(run_id)
    assert progress.status_code == 200
    assert progress.json() == {
        "trading_days": 1,
        "passed": 0,
        "failed": 0,
        "blocked": 0,
        "remaining": 19,
        "complete": False,
    }
