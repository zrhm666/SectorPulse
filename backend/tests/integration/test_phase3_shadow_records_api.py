# ruff: noqa: E501
from uuid import uuid4

from fastapi.testclient import TestClient
from sector_pulse.web.app import create_app


def test_shadow_recovery_and_compliance_records(tmp_path) -> None:
    client = TestClient(create_app(database_path=tmp_path / "shadow-records.db"))
    shadow_id = client.post("/api/shadow-runs", json={"run_id": str(uuid4()), "trading_date": "2026-08-20"}).json()["shadow_id"]
    recovery = client.post(f"/api/shadow-runs/{shadow_id}/recovery-drills", json={"fault_type": "provider_timeout", "recovered": True, "recovery_seconds": 4.2})
    compliance = client.post(f"/api/shadow-runs/{shadow_id}/compliance", json={"rules_version": "phase3-v1", "decision": "PASS", "reviewer": "local-user"})
    assert recovery.status_code == 201
    assert compliance.status_code == 201
