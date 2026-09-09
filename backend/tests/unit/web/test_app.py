# backend/tests/unit/web/test_app.py
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sector_pulse.application.data_runs.candidate_selection_service import (
    CandidateSelectionRequired,
)
from sector_pulse.domain.market.candidate_selection import CandidateSelectionMethod
from sector_pulse.web.app import create_app


class WorkbenchQueries:
    def __init__(self) -> None:
        self.market_call: tuple[UUID, str, int, int] | None = None
        self.news_records_call = None
        self.candidates_call = None

    def market(self, run_id, kind, *, offset, limit):
        self.market_call = (run_id, kind.value, offset, limit)
        return {"kind": kind.value, "items": [], "total": 0, "offset": offset, "limit": limit}

    def evidence(self, run_id):
        return {"events": [{"event_id": "event-1"}], "total": 1}

    def quality(self, run_id):
        return {"cutoff_violation_count": 1, "error_code": None}

    def content_run(self, run_id):
        return None

    def candidates(self, run_id, *, query, sort, direction, offset, limit):
        self.candidates_call = (run_id, query, sort, direction, offset, limit)
        return {
            "items": [
                {
                    "sector_id": "industry-1",
                    "sector_kind": "INDUSTRY",
                    "rank": 1,
                    "score": "9.8",
                    "reasons": ["涨幅领先"],
                    "name": "示例行业",
                    "pct_change": "1.2",
                    "turnover_rate": None,
                    "total_market_cap": None,
                    "advancers": 10,
                    "decliners": 5,
                    "leader_name": "示例龙头",
                    "leader_pct_change": "3.1",
                    "field_availability": {"pct_change": True},
                    "news_count": 2,
                }
            ],
            "total": 1,
            "offset": offset,
            "limit": limit,
            "query": query,
            "sort": sort,
            "direction": direction,
            "data_version": "a" * 64,
        }

    def summary(self, run_id):
        return {
            "run_id": str(run_id),
            "status": "READY_FOR_ATTRIBUTION",
            "workflow_stage": "ATTRIBUTION_READY",
            "workflow_stage_index": 5,
            "terminal": True,
            "requested_at": datetime.now(UTC),
            "cutoff_at": datetime.now(UTC),
            "finished_at": None,
            "candidate_count": 1,
        }

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

    def news_record(self, run_id, document_id):
        if document_id == "missing":
            raise KeyError(document_id)
        return {
            "document_id": document_id,
            "source_id": "fixture-news",
            "content_kind": "SUMMARY",
            "content": "已保存摘要",
            "content_available": True,
            "citation_url": "https://example.com/news",
            "title": "示例新闻",
            "publisher": "示例媒体",
            "summary": "已保存摘要",
            "published_at": datetime.now(UTC),
            "source_observed_at": datetime.now(UTC),
            "collected_at": datetime.now(UTC),
            "source_grade": "REPUTABLE_MEDIA",
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


class SelectionActions:
    def __init__(self, run_id: UUID, *, confirmed: bool = False) -> None:
        self.run_id = run_id
        self.confirmed = confirmed
        self.confirm_call = None
        self.selected_sector_ids = ("sector-1", "sector-2", "sector-3")

    def view(self, run_id: UUID):
        return self._value(run_id)

    def confirm(self, run_id: UUID, sector_ids: tuple[str, ...], *, expected_version: int):
        self.confirm_call = (run_id, sector_ids, expected_version)
        self.confirmed = True
        self.selected_sector_ids = sector_ids
        return self._value(run_id, version=expected_version + 1)

    def require_confirmed(self, run_id: UUID):
        if not self.confirmed:
            raise CandidateSelectionRequired("CANDIDATE_SELECTION_REQUIRED")
        return self._value(run_id, version=1)

    def _value(self, run_id: UUID, version: int = 0):
        return SimpleNamespace(
            run_id=run_id,
            confirmed=self.confirmed,
            version=version if self.confirmed else 0,
            selected_sector_ids=self.selected_sector_ids,
            method=CandidateSelectionMethod.MANUAL if self.confirmed else None,
            confirmed_at=datetime.now(UTC) if self.confirmed else None,
            data_version="a" * 64,
            edit_count=1 if self.confirmed else 0,
        )


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
    assert response.json() == {
        "error": {"code": "NOT_FOUND", "message": "not found", "retryable": False}
    }


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
    candidates = client.get(
        f"/api/data-runs/{run_id}/candidates"
        "?query=行业&sort=news_count&direction=desc&offset=1&limit=10"
    )
    assert candidates.json()["items"][0]["name"] == "示例行业"
    assert workbench.candidates_call == (
        run_id,
        "行业",
        "news_count",
        "desc",
        1,
        10,
    )
    summary = client.get(f"/api/data-runs/{run_id}/summary")
    assert summary.json()["workflow_stage"] == "ATTRIBUTION_READY"
    detail = client.get(f"/api/data-runs/{run_id}/news-records/doc-1")
    assert detail.status_code == 200
    assert detail.json()["content_kind"] == "SUMMARY"
    assert client.get(f"/api/data-runs/{run_id}/news-records/missing").status_code == 404


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
    assert client.get(f"/api/data-runs/{run_id}/candidates?sort=unknown").status_code == 422
    assert client.get(f"/api/data-runs/{run_id}/candidates?direction=sideways").status_code == 422
    assert client.get(f"/api/data-runs/{run_id}/candidates?offset=-1").status_code == 422


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


def test_selection_preview_can_be_confirmed_as_a_version(tmp_path) -> None:
    run_id = uuid4()
    selections = SelectionActions(run_id)
    client = TestClient(
        create_app(
            database_path=tmp_path / "app.db",
            static_dir=None,
            overrides={
                "data_run_service": DataRunActions(uuid4()),
                "workbench_queries": WorkbenchQueries(),
                "candidate_selection_service": selections,
            },
        )
    )

    preview = client.get(f"/api/data-runs/{run_id}/selection")
    confirmed = client.put(
        f"/api/data-runs/{run_id}/selection",
        json={"sector_ids": ["sector-3", "sector-1", "sector-2"], "expected_version": 0},
    )

    assert preview.status_code == 200
    assert preview.json()["confirmed"] is False
    assert confirmed.status_code == 200
    assert confirmed.json()["confirmed"] is True
    assert confirmed.json()["version"] == 1
    assert selections.confirm_call == (
        run_id,
        ("sector-3", "sector-1", "sector-2"),
        0,
    )


def test_generate_uses_confirmed_selection_instead_of_transient_candidates(tmp_path) -> None:
    run_id = uuid4()
    generated_id = uuid4()
    writing = WritingActions(generated_id)
    selections = SelectionActions(run_id, confirmed=True)
    client = TestClient(
        create_app(
            database_path=tmp_path / "app.db",
            static_dir=None,
            overrides={
                "data_run_service": DataRunActions(uuid4()),
                "workbench_queries": WorkbenchQueries(),
                "writing_service": writing,
                "candidate_selection_service": selections,
            },
        )
    )

    response = client.post(
        f"/api/data-runs/{run_id}/generate",
        json={"sector_ids": ["sector-3", "sector-1", "sector-2"]},
    )

    assert response.status_code == 200
    assert response.json() == {"run_id": str(generated_id)}
    assert writing.generate_call == (run_id, ("sector-1", "sector-2", "sector-3"))


def test_generate_without_a_confirmed_selection_is_rejected(tmp_path) -> None:
    run_id = uuid4()
    generated_id = uuid4()
    writing = WritingActions(generated_id)
    selections = SelectionActions(run_id)
    client = TestClient(
        create_app(
            database_path=tmp_path / "app.db",
            static_dir=None,
            overrides={
                "data_run_service": DataRunActions(uuid4()),
                "workbench_queries": WorkbenchQueries(),
                "writing_service": writing,
                "candidate_selection_service": selections,
            },
        )
    )

    response = client.post(f"/api/data-runs/{run_id}/generate")

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "CANDIDATE_SELECTION_REQUIRED",
            "message": "CANDIDATE_SELECTION_REQUIRED",
            "retryable": False,
        }
    }
    assert writing.generate_call is None
