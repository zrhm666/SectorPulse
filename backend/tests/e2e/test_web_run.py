# backend/tests/e2e/test_web_run.py
import time

from fastapi.testclient import TestClient
from sector_pulse.web.app import create_app


def test_fixture_run_end_to_end(tmp_path) -> None:
    from backend.tests.unit.web.test_run_service import _input_json, _service

    client = TestClient(create_app(overrides={"service": _service(tmp_path)}))
    resp = client.post("/api/runs", json={"input_json": _input_json(), "provider": "fixture"})
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]

    for _ in range(60):
        detail = client.get(f"/api/runs/{run_id}").json()
        if detail["status"] != "RUNNING":
            break
        time.sleep(0.25)

    assert detail["status"] == "READY_FOR_HUMAN_REVIEW"
    assert detail["sector_count"] == 8
    assert detail["review_decision"] == "PASS"

    radar = client.get(f"/api/runs/{run_id}/radar").json()
    assert len(radar["cards"]) == 8

    draft = client.get(f"/api/runs/{run_id}/draft").json()
    assert len(draft["versions"]) >= 2

    review = client.get(f"/api/runs/{run_id}/review").json()
    assert review["decision"] == "PASS"

    evidence = client.get(f"/api/runs/{run_id}/evidence").json()
    assert set(i["stage"] for i in evidence["invocations"]) >= {
        "attribution",
        "editorial",
        "writing",
        "review",
    }

    md = client.get(f"/api/runs/{run_id}/draft.md")
    assert md.status_code == 200
    assert md.text.strip() != ""
