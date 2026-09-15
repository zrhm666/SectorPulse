# backend/tests/integration/test_web_api.py
import asyncio
import time
from uuid import UUID

from fastapi.testclient import TestClient
from sector_pulse.web.app import create_app

from backend.tests.unit.web.services.test_run_service import _input_json, _service


def _client(tmp_path):
    return TestClient(create_app(overrides={"service": _service(tmp_path)}))


async def _completed_legacy_run(service) -> UUID:
    """A finished run of the old engine, of the kind already in a real database."""
    run_id = service.create_run(_input_json(), "fixture")
    await service.wait(run_id)
    return run_id


def test_list_runs_empty(tmp_path) -> None:
    resp = _client(tmp_path).get("/api/runs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_fixture_input_endpoint_returns_reproducible_example(tmp_path) -> None:
    resp = _client(tmp_path).get("/api/fixture-input")
    assert resp.status_code == 200
    assert len(resp.json()["contexts"]) == 8
    assert "industry-1" in resp.json()["gates"]


def test_invalid_input_json_returns_422(tmp_path) -> None:
    resp = _client(tmp_path).post("/api/runs", json={"input_json": {}, "provider": "fixture"})
    assert resp.status_code == 422


def test_create_run_rejects_removed_workflow_agent_modes(tmp_path) -> None:
    client = _client(tmp_path)
    nested = client.post(
        "/api/runs",
        json={
            "input_json": {**_input_json(), "attribution_mode": "workflow"},
            "provider": "fixture",
        },
    )
    top_level = client.post(
        "/api/runs",
        json={
            "input_json": _input_json(),
            "provider": "fixture",
            "attribution_mode": "agent",
        },
    )
    assert nested.status_code == 422
    assert nested.json()["error"]["code"] == "LEGACY_EXECUTION_MODE_REMOVED"
    assert "multi_agent" in nested.json()["error"]["message"]
    assert top_level.status_code == 422
    assert top_level.json()["error"]["code"] == "LEGACY_EXECUTION_MODE_REMOVED"


def test_live_preflight_returns_409_without_persisting_run(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "sector_pulse.web.providers.live_provider.check_live_consent", lambda: False
    )
    client = _client(tmp_path)
    resp = client.post("/api/runs", json={"input_json": _input_json(), "provider": "live"})
    assert resp.status_code == 409
    assert client.get("/api/runs").json() == []


def test_removed_data_run_creation_endpoint_directs_callers_to_multi_agent_runs(tmp_path) -> None:
    with TestClient(create_app(database_path=tmp_path / "app.db", static_dir=None)) as client:
        resp = client.post(
            "/api/data-runs",
            json={"mode": "post_close", "provider": "fixture"},
        )

    assert resp.status_code == 410
    assert resp.json()["error"] == {
        "code": "REQUEST_FAILED",
        "message": "data-run creation has moved to /api/runs multi-agent execution",
        "retryable": False,
    }


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


def test_retrying_a_historical_run_reports_the_migration_instead_of_crashing(tmp_path) -> None:
    """The shipped app runs the multi-agent engine, and a legacy row has no snapshot.

    So retry cannot reproduce what the old engine would have done. The reader has
    to be told that instead of getting an opaque 500 from a lost lookup, and the
    UI must not offer a retry the wired engine cannot honor.
    """
    database_path = tmp_path / "test.db"
    historical = asyncio.run(_completed_legacy_run(_service(tmp_path)))
    client = TestClient(create_app(database_path=database_path, static_dir=None))

    detail = client.get(f"/api/runs/{historical}").json()
    assert detail["execution_engine"] == "legacy"
    assert detail["retryable"] is False

    refused = client.post(f"/api/runs/{historical}/retry")
    assert refused.status_code == 409
    assert refused.json()["error"]["retryable"] is False
    assert "旧引擎" in refused.json()["error"]["message"]

    # A refused retry must not disturb the historical run it pointed at.
    assert client.get(f"/api/runs/{historical}").json()["status"] == detail["status"]


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
    # A decision is only meaningful against the version it was made on, so the
    # read path names that version instead of leaving the reader to guess.
    reviewed = review_resp.json()
    versions = {item["version"] for item in draft_resp.json()["versions"]}
    assert reviewed["draft_version"] in versions
    assert reviewed["draft_id"] == client.get(f"/api/runs/{run_id}").json()["draft_id"]
    md = client.get(f"/api/runs/{run_id}/draft.md")
    assert md.status_code == 200
    assert md.text.strip() != ""
