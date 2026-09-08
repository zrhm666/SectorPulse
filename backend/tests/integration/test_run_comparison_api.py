import hashlib
import sqlite3
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sector_pulse.application.comparison.run_comparison_queries import RunComparisonQueries
from sector_pulse.domain.real_data_run import RealDataRun, RealDataRunRequest, RealDataRunStatus
from sector_pulse.storage.runtime_bundle import build_sqlite_storage
from sector_pulse.storage.sqlite import SQLiteDatabase
from sector_pulse.web.app import create_app
from sector_pulse.web.errors import register_error_handlers
from sector_pulse.web.routers.run_comparisons import build_run_comparisons_router

from backend.tests.comparison_fixtures import seed_news, seed_pair


def comparison_client(storage):
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(build_run_comparisons_router(RunComparisonQueries(storage)))
    return TestClient(app)


@pytest.fixture
def api(tmp_path):
    path = tmp_path / "comparison-api.sqlite"
    storage = build_sqlite_storage(SQLiteDatabase(path))
    base, other = seed_pair(storage)
    seed_news(storage, base.run_id, other.run_id)
    return comparison_client(storage), storage, base, other, path


def fingerprint(path):
    with sqlite3.connect(path) as connection:
        dump = "\n".join(connection.iterdump())
    return hashlib.sha256(dump.encode()).hexdigest()


def test_all_four_gets_leave_business_tables_unchanged(api) -> None:
    client, _, base, other, path = api
    before = fingerprint(path)
    params = {"base_run_id": str(base.run_id), "compare_run_id": str(other.run_id)}
    for suffix in ("", "/news", "/evidence"):
        response = client.get(f"/api/run-comparisons{suffix}", params=params)
        assert response.status_code == 200, response.text
    listing = client.get("/api/run-comparisons/runs")
    assert listing.status_code == 200
    assert listing.json()["total"] == 2
    body = client.get("/api/run-comparisons", params=params).json()
    assert body["kinds"][0]["rows"][1]["pct_change"]["delta"] == "0.10"
    assert fingerprint(path) == before


@pytest.mark.parametrize("suffix", ["", "/news", "/evidence"])
@pytest.mark.parametrize(
    "case,status",
    [
        ("same", 422),
        ("missing", 404),
        ("active", 409),
        ("provider", 409),
        ("mode", 409),
        ("bad_uuid", 422),
    ],
)
def test_all_comparison_endpoints_validate_pairs(api, suffix, case, status) -> None:
    client, storage, base, other, _ = api
    compare_id = str(other.run_id)
    if case == "same":
        compare_id = str(base.run_id)
    elif case == "missing":
        compare_id = str(uuid4())
    elif case == "bad_uuid":
        compare_id = "invalid"
    elif case == "active":
        storage.real_data_runs.update_status(other.run_id, RealDataRunStatus.FETCHING_NEWS)
    else:
        incompatible = RealDataRun(
            provider="live" if case == "provider" else "fixture",
            request=RealDataRunRequest(mode="intraday" if case == "mode" else "post_close"),
            status=RealDataRunStatus.FAILED,
        )
        storage.real_data_runs.insert(incompatible)
        compare_id = str(incompatible.run_id)
    response = client.get(
        f"/api/run-comparisons{suffix}",
        params={"base_run_id": str(base.run_id), "compare_run_id": compare_id},
    )
    assert response.status_code == status, response.text
    assert "error" in response.json()


@pytest.mark.parametrize(
    "suffix,extra",
    [
        ("/news", {"offset": -1}),
        ("/news", {"membership": "NEW"}),
        ("/news", {"limit": 101}),
        ("/evidence", {"kind": "INDUSTRY"}),
        ("/evidence", {"sector_id": "001"}),
        ("/evidence", {"limit": 0}),
        ("/runs", {"provider": "wrong"}),
        ("/runs", {"offset": -1}),
    ],
)
def test_invalid_filters_are_not_silently_ignored(api, suffix, extra) -> None:
    client, _, base, other, _ = api
    response = client.get(
        f"/api/run-comparisons{suffix}",
        params={"base_run_id": str(base.run_id), "compare_run_id": str(other.run_id), **extra},
    )
    assert response.status_code == 422


def test_terminal_runs_without_snapshots_are_unavailable_not_a_server_error(api) -> None:
    client, storage, base, _, _ = api
    empty = RealDataRun(
        provider="fixture",
        request=RealDataRunRequest(mode="post_close"),
        status=RealDataRunStatus.FAILED,
    )
    storage.real_data_runs.insert(empty)
    response = client.get(
        "/api/run-comparisons",
        params={"base_run_id": str(base.run_id), "compare_run_id": str(empty.run_id)},
    )
    assert response.status_code == 200
    assert response.json()["candidates"]["unavailable_kinds"] == 2
    assert all(group["status"] == "UNAVAILABLE" for group in response.json()["kinds"])


def test_real_app_registers_comparison_before_spa_fallback(api, tmp_path, monkeypatch) -> None:
    _, _, base, other, path = api
    monkeypatch.setattr("sector_pulse.web.app.load_environment", lambda: None)
    monkeypatch.setenv("SECTOR_PULSE_LLM_PROVIDER", "fixture")
    monkeypatch.setenv("SECTOR_PULSE_SCHEDULER_ENABLED", "false")
    client = TestClient(create_app(database_path=path, static_dir=tmp_path))
    response = client.get(
        "/api/run-comparisons",
        params={"base_run_id": str(base.run_id), "compare_run_id": str(other.run_id)},
    )
    assert response.status_code == 200
    assert response.json()["candidates"]["both"] == 2
