from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_governance_reads_new_orchestration_draft_when_legacy_table_is_empty():
    from sector_pulse.web.routers.review import (
        ReviewRouterDependencies,
        build_review_governance_router,
    )

    run_id = uuid4()
    draft = SimpleNamespace(run_id=run_id, draft_id=uuid4())
    report = SimpleNamespace(status="PASS", issues=(), rules_version="rules-v1")
    dependencies = ReviewRouterDependencies(
        review_analytics=SimpleNamespace(),
        draft_edits=SimpleNamespace(),
        phase1b=SimpleNamespace(get_drafts=lambda requested: []),
        governance_service=SimpleNamespace(check=lambda requested: report),
        release_audit=SimpleNamespace(),
        evidence_repository=SimpleNamespace(),
        evidence_service=SimpleNamespace(),
        orchestration_queries=SimpleNamespace(latest_draft=lambda requested: draft),
    )
    app = FastAPI()
    app.include_router(build_review_governance_router(dependencies))

    response = TestClient(app).get(f"/api/runs/{run_id}/governance")

    assert response.status_code == 200
    assert response.json() == {
        "status": "PASS",
        "issues": [],
        "rules_version": "rules-v1",
    }
