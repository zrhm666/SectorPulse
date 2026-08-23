# backend/tests/unit/web/test_app.py
from fastapi.testclient import TestClient
from sector_pulse.web.app import create_app


def test_health_endpoint() -> None:
    client = TestClient(create_app())
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_static_spa_fallback_keeps_unknown_api_routes_as_404(tmp_path) -> None:
    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<main>SectorPulse</main>", encoding="utf-8")
    client = TestClient(create_app(database_path=tmp_path / "app.db", static_dir=static_dir))

    assert client.get("/review").status_code == 200
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {"detail": "not found"}
