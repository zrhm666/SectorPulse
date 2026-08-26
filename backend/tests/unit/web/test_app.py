# backend/tests/unit/web/test_app.py
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sector_pulse.web.app import create_app


class WorkbenchQueries:
    def __init__(self) -> None:
        self.market_call: tuple[UUID, str, int, int] | None = None
        self.news_records_call = None

    def market(self, run_id, kind, *, offset, limit):
        self.market_call = (run_id, kind.value, offset, limit)
        return {"kind": kind.value, "items": [], "total": 0, "offset": offset, "limit": limit}

    def evidence(self, run_id):
        return {"events": [{"event_id": "event-1"}], "total": 1}

    def quality(self, run_id):
        return {"cutoff_violation_count": 1, "error_code": None}

    def content_run(self, run_id):
        return None

    def candidates(self, run_id):
        return [{"sector_id": "industry-1", "name": "示例行业"}]


    def acquisition(self, run_id):
        return {"coverage": "COMPLETE", "market_sources": [], "news_sources": []}

    def news_records(self, run_id, *, source_id, status, offset, limit):
        self.news_records_call = (
            run_id,
            source_id,
            status.value if status else None,
            offset,
            limit,
        )
        return {
            "coverage": "COMPLETE",
            "items": [{"document_id": "doc-1"}],
            "total": 1,
            "offset": offset,
            "limit": limit,
        }


class DataRunActions:
    def __init__(self, retry_id: UUID) -> None:
        self.retry_id = retry_id

    def retry(self, run_id: UUID) -> UUID:
        return self.retry_id

    def cancel(self, run_id: UUID) -> bool:
        return False


class WritingActions:
    def __init__(self, generated_id: UUID) -> None:
        self.generated_id = generated_id
        self.generate_call: tuple[UUID, tuple[str, ...] | None] | None = None

    def generate(self, run_id: UUID, sector_ids: tuple[str, ...] | None = None) -> UUID:
        self.generate_call = (run_id, sector_ids)
        return self.generated_id


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


def test_data_run_workbench_endpoints_return_independent_payloads(tmp_path) -> None:
    run_id = uuid4()
    workbench = WorkbenchQueries()
    client = TestClient(
        create_app(
            database_path=tmp_path / "app.db",
            static_dir=None,
            overrides={
                "data_run_service": DataRunActions(uuid4()),
                "workbench_queries": workbench,
            },
        )
    )

    market = client.get(f"/api/data-runs/{run_id}/market?kind=INDUSTRY&offset=2&limit=10")

    assert market.status_code == 200
    assert market.json()["offset"] == 2
    assert workbench.market_call == (run_id, "INDUSTRY", 2, 10)
    assert client.get(f"/api/data-runs/{run_id}/evidence").json()["total"] == 1
    assert client.get(f"/api/data-runs/{run_id}/quality").json()["cutoff_violation_count"] == 1
    assert client.get(f"/api/data-runs/{run_id}/content-run").json() is None
    assert client.get(f"/api/data-runs/{run_id}/acquisition").json()["coverage"] == "COMPLETE"
    records = client.get(
        f"/api/data-runs/{run_id}/news-records"
        "?source_id=eastmoney&status=SUCCESS&offset=20&limit=10"
    )
    assert records.status_code == 200
    assert records.json()["total"] == 1
    assert workbench.news_records_call == (run_id, "eastmoney", "SUCCESS", 20, 10)
    assert client.get(f"/api/data-runs/{run_id}/candidates").json()[0]["name"] == "示例行业"


def test_market_query_parameters_are_validated(tmp_path) -> None:
    run_id = uuid4()
    client = TestClient(
        create_app(
            database_path=tmp_path / "app.db",
            static_dir=None,
            overrides={
                "data_run_service": DataRunActions(uuid4()),
                "workbench_queries": WorkbenchQueries(),
            },
        )
    )

    assert client.get(f"/api/data-runs/{run_id}/market?kind=OTHER").status_code == 422
    assert client.get(f"/api/data-runs/{run_id}/market?kind=INDUSTRY&limit=101").status_code == 422
    assert client.get(f"/api/data-runs/{run_id}/market?kind=INDUSTRY&offset=-1").status_code == 422
    assert client.get(f"/api/data-runs/{run_id}/news-records?offset=-1").status_code == 422
    assert client.get(f"/api/data-runs/{run_id}/news-records?limit=0").status_code == 422
    assert client.get(f"/api/data-runs/{run_id}/news-records?limit=101").status_code == 422
    assert client.get(f"/api/data-runs/{run_id}/news-records?status=OTHER").status_code == 422


def test_retry_returns_new_data_run_id(tmp_path) -> None:
    run_id = uuid4()
    retry_id = uuid4()
    client = TestClient(
        create_app(
            database_path=tmp_path / "app.db",
            static_dir=None,
            overrides={
                "data_run_service": DataRunActions(retry_id),
                "workbench_queries": WorkbenchQueries(),
            },
        )
    )

    response = client.post(f"/api/data-runs/{run_id}/retry")

    assert response.status_code == 200
    assert response.json() == {"run_id": str(retry_id)}


def test_generate_forwards_manually_selected_candidates(tmp_path) -> None:
    run_id = uuid4()
    generated_id = uuid4()
    writing = WritingActions(generated_id)
    client = TestClient(
        create_app(
            database_path=tmp_path / "app.db",
            static_dir=None,
            overrides={
                "data_run_service": DataRunActions(uuid4()),
                "workbench_queries": WorkbenchQueries(),
                "writing_service": writing,
            },
        )
    )

    response = client.post(
        f"/api/data-runs/{run_id}/generate",
        json={"sector_ids": ["sector-3", "sector-1", "sector-2"]},
    )

    assert response.status_code == 200
    assert response.json() == {"run_id": str(generated_id)}
    assert writing.generate_call == (
        run_id, ("sector-3", "sector-1", "sector-2")
    )


def test_generate_without_selection_keeps_automatic_behavior(tmp_path) -> None:
    run_id = uuid4()
    generated_id = uuid4()
    writing = WritingActions(generated_id)
    client = TestClient(
        create_app(
            database_path=tmp_path / "app.db",
            static_dir=None,
            overrides={
                "data_run_service": DataRunActions(uuid4()),
                "workbench_queries": WorkbenchQueries(),
                "writing_service": writing,
            },
        )
    )

    response = client.post(f"/api/data-runs/{run_id}/generate")

    assert response.status_code == 200
    assert response.json() == {"run_id": str(generated_id)}
    assert writing.generate_call == (run_id, None)
