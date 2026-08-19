from fastapi.testclient import TestClient
from sector_pulse.web.app import create_app

from backend.tests.unit.web.test_run_service import _service


def test_schedule_create_list_and_trigger(tmp_path):
    client = TestClient(
        create_app(
            database_path=tmp_path / "phase2a.db",
            overrides={"service": _service(tmp_path)},
        )
    )

    created = client.post(
        "/api/schedules",
        json={
            "name": "盘后",
            "mode": "post_close",
            "timezone": "Asia/Shanghai",
            "local_time": "16:00",
            "trading_days": "weekdays",
            "enabled": True,
        },
    )

    assert created.status_code == 201
    schedule = created.json()
    assert schedule["name"] == "盘后"
    assert client.get("/api/schedules").json()[0]["schedule_id"] == schedule["schedule_id"]

    triggered = client.post(
        f"/api/schedules/{schedule['schedule_id']}/trigger",
        headers={"Idempotency-Key": "trigger-1"},
    )
    assert triggered.status_code == 202
    assert triggered.json()["run_id"]
    repeated = client.post(
        f"/api/schedules/{schedule['schedule_id']}/trigger",
        headers={"Idempotency-Key": "trigger-1"},
    )
    assert repeated.status_code == 202
    assert repeated.json()["run_id"] == triggered.json()["run_id"]
