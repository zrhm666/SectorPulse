from uuid import uuid4

from fastapi.testclient import TestClient
from sector_pulse.web.app import create_app


def test_shadow_progress_reports_remaining_days(tmp_path) -> None:
    client = TestClient(create_app(database_path=tmp_path / "shadow-progress.db"))
    client.post("/api/shadow-runs", json={"run_id": str(uuid4()), "trading_date": "2026-08-20"})
    response = client.get("/api/shadow-runs/summary")
    assert response.status_code == 200
    assert response.json()["trading_days"] == 1
    assert response.json()["remaining"] == 19
    assert response.json()["complete"] is False
