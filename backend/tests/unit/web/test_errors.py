from fastapi import FastAPI
from fastapi.testclient import TestClient
from sector_pulse.web.app import create_app

EXPECTED_ROUTES = {
    ("GET", "/api/health"),
    ("GET", "/api/operations/summary"),
    ("POST", "/api/data-runs"),
    ("POST", "/api/schedules/{schedule_id}/trigger"),
    ("GET", "/api/runs/{run_id}"),
}


def test_public_route_manifest(tmp_path) -> None:
    app = create_app(database_path=tmp_path / "manifest.db", static_dir=None)
    actual = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }
    assert actual >= EXPECTED_ROUTES


def test_internal_error_response_is_sanitized(tmp_path) -> None:
    app: FastAPI = create_app(database_path=tmp_path / "errors.db", static_dir=None)

    @app.get("/api/test-only/raise-secret-error")
    def raise_secret_error() -> None:
        raise RuntimeError("secret-token")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/test-only/raise-secret-error")

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "服务暂时不可用",
            "retryable": True,
        }
    }
    assert "secret-token" not in response.text
