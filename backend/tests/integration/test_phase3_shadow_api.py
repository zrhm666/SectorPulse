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
