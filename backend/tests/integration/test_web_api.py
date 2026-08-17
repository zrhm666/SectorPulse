# backend/tests/integration/test_web_api.py
import time

from fastapi.testclient import TestClient
from sector_pulse.web.app import create_app

from backend.tests.unit.web.test_run_service import _input_json, _service


def _client(tmp_path):
    return TestClient(create_app(overrides={"service": _service(tmp_path)}))


def test_list_runs_empty(tmp_path) -> None:
    resp = _client(tmp_path).get("/api/runs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_invalid_input_json_returns_422(tmp_path) -> None:
    resp = _client(tmp_path).post("/api/runs", json={"input_json": {}, "provider": "fixture"})
    assert resp.status_code == 422


def test_live_preflight_returns_409_without_persisting_run(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("sector_pulse.web.live_provider.check_live_consent", lambda: False)
    client = _client(tmp_path)
    resp = client.post("/api/runs", json={"input_json": _input_json(), "provider": "live"})
    assert resp.status_code == 409
    assert client.get("/api/runs").json() == []

def test_create_and_get_run(tmp_path) -> None:
    client = _client(tmp_path)
    resp = client.post("/api/runs", json={"input_json": _input_json(), "provider": "fixture"})
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]
    for _ in range(40):
        detail = client.get(f"/api/runs/{run_id}").json()
        if detail["status"] != "RUNNING":
            break
        time.sleep(0.25)
    assert detail["status"] == "READY_FOR_HUMAN_REVIEW"


def test_retry_completed_run_creates_new_run(tmp_path) -> None:
    client = _client(tmp_path)
    first = client.post("/api/runs", json={"input_json": _input_json(), "provider": "fixture"})
    first_id = first.json()["run_id"]
    for _ in range(40):
        detail = client.get(f"/api/runs/{first_id}").json()
        if detail["status"] != "RUNNING":
            break
        time.sleep(0.25)
    retry = client.post(f"/api/runs/{first_id}/retry")
    assert retry.status_code == 200
    assert retry.json()["run_id"] != first_id
    assert len(client.get("/api/runs").json()) >= 2

def test_detail_endpoints_after_run(tmp_path) -> None:
    client = _client(tmp_path)
    resp = client.post("/api/runs", json={"input_json": _input_json(), "provider": "fixture"})
    run_id = resp.json()["run_id"]
    for _ in range(40):
        detail = client.get(f"/api/runs/{run_id}").json()
        if detail["status"] != "RUNNING":
            break
        time.sleep(0.25)
    assert client.get(f"/api/runs/{run_id}/radar").status_code == 200
    draft_resp = client.get(f"/api/runs/{run_id}/draft")
    assert draft_resp.status_code == 200
    assert draft_resp.json()["versions"]
    assert client.get(f"/api/runs/{run_id}/evidence").status_code == 200
    review_resp = client.get(f"/api/runs/{run_id}/review")
    assert review_resp.status_code == 200
    assert review_resp.json()["decision"] == "PASS"
    md = client.get(f"/api/runs/{run_id}/draft.md")
    assert md.status_code == 200
    assert md.text.strip() != ""