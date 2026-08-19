# ruff: noqa: E501
from uuid import uuid4

from fastapi.testclient import TestClient
from sector_pulse.web.app import create_app


def test_shadow_run_can_be_completed(tmp_path) -> None:
    client = TestClient(create_app(database_path=tmp_path / "shadow-update.db"))
    created = client.post("/api/shadow-runs", json={"run_id": str(uuid4()), "trading_date": "2026-08-20"}).json()
    response = client.patch(f"/api/shadow-runs/{created['shadow_id']}", json={"status": "PASSED", "metrics": {"review_duration_seconds": 12}})
    assert response.status_code == 200
    assert response.json()["status"] == "PASSED"
