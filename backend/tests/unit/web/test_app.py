# backend/tests/unit/web/test_app.py
from fastapi.testclient import TestClient
from sector_pulse.web.app import create_app


def test_health_endpoint() -> None:
    client = TestClient(create_app())
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
