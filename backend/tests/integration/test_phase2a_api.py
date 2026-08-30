from fastapi.testclient import TestClient
from sector_pulse.web.app import create_app

from backend.tests.unit.web.test_run_service import _service


class FakeDataRuns:
    def __init__(self) -> None:
        from uuid import uuid4

        self.run_id = uuid4()
        self.started = 0

    def create(self, request, provider):
        self.started += 1
        return self.run_id

    def retry(self, run_id):
        return run_id

    def cancel(self, run_id):
        return False


def test_schedule_create_list_and_trigger(tmp_path):
    fake_data_runs = FakeDataRuns()
    client = TestClient(
        create_app(
            database_path=tmp_path / "phase2a.db",
            overrides={
                "service": _service(tmp_path),
                "data_run_service": fake_data_runs,
            },
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
    detail = client.get(f"/api/task-runs/{triggered.json()['run_id']}")
    assert detail.status_code == 200
    assert {"run_id", "status", "stages", "events"} <= detail.json().keys()
    assert detail.json()["data_run_id"] == str(fake_data_runs.run_id)
    assert fake_data_runs.started == 1
