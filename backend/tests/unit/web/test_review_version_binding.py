"""Human editing must not inherit an agent's approval.

An A4 PASS is a statement about one immutable draft version. Once a human edit
creates a higher version, that statement is about a draft that is no longer the
current one, so it cannot authorise approval or export of the new version.
"""

from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sector_pulse.domain.writing.article import ArticleDraft, DraftStatus
from sector_pulse.web.schemas.runs import RunDetail


def _draft(run_id, draft_id, version: int) -> ArticleDraft:
    return ArticleDraft(
        draft_id=draft_id,
        run_id=run_id,
        version=version,
        status=DraftStatus.INCOMPLETE,
        titles=("标题",),
        introduction="导语",
        sections=(),
        conclusion="总结",
        risk_notice="风险提示",
        sources=(),
        character_count=8,
    )


class _ReleaseAudit:
    def __init__(self, *, approved_versions: tuple[int, ...] = ()) -> None:
        self.approvals: list[object] = []
        self.exports: list[object] = []
        self._approved_versions = approved_versions

    def approve(self, approval) -> None:
        self.approvals.append(approval)

    def approval(self, draft_id, version):
        if version not in self._approved_versions:
            return None
        return SimpleNamespace(version=version, status=SimpleNamespace(value="APPROVED_FOR_COPY"))

    def record_export(self, export) -> None:
        self.exports.append(export)

    def revoke(self, *args) -> None:
        raise AssertionError("revoke must not run")

    def content_hash(self, payload) -> str:
        return "hash"

    def record_event(self, *args) -> None:
        raise AssertionError("no audit event expected")


def _app(*, current_version: int, reviewed_version: int | None, run_id, draft_id, audit):
    from sector_pulse.web.routers.review import (
        ReviewRouterDependencies,
        build_review_governance_router,
    )

    draft = _draft(run_id, draft_id, current_version)
    report = SimpleNamespace(status="PASS", issues=(), rules_version="rules-v1")
    review = {
        "decision": "PASS" if reviewed_version is not None else None,
        "revision_round": 0,
        "issues": [],
        "draft_id": str(draft_id) if reviewed_version is not None else None,
        "draft_version": reviewed_version,
    }
    detail = RunDetail(
        run_id=run_id,
        execution_engine="multi_agent",
        requested_at="2026-09-15T09:00:00Z",
        provider="fixture",
        status="WAITING_USER_REVIEW",
        elapsed_ms=None,
        total_cost_cny=None,
        draft_id=draft_id,
        input_json_hash=None,
        error_message=None,
        sector_count=1,
        review_decision=None,
        retryable=False,
    )
    dependencies = ReviewRouterDependencies(
        review_analytics=SimpleNamespace(),
        draft_edits=SimpleNamespace(latest_version=lambda requested: draft),
        phase1b=SimpleNamespace(get_drafts=lambda requested: []),
        governance_service=SimpleNamespace(check=lambda requested: report),
        release_audit=audit,
        evidence_repository=SimpleNamespace(),
        evidence_service=SimpleNamespace(),
        orchestration_queries=SimpleNamespace(
            get_run=lambda requested: detail,
            latest_draft=lambda requested: draft,
            get_review=lambda requested: review,
        ),
    )
    app = FastAPI()
    app.include_router(build_review_governance_router(dependencies))
    return TestClient(app)


def test_approving_a_human_edited_version_needs_a_review_of_that_version() -> None:
    run_id = uuid4()
    draft_id = uuid4()
    audit = _ReleaseAudit()
    client = _app(
        current_version=2,
        reviewed_version=1,
        run_id=run_id,
        draft_id=draft_id,
        audit=audit,
    )

    response = client.post(f"/api/runs/{run_id}/drafts/{draft_id}/approve")

    assert response.status_code == 409
    assert "review" in response.json()["detail"].lower()
    assert audit.approvals == []


def test_approving_the_reviewed_version_still_works() -> None:
    run_id = uuid4()
    draft_id = uuid4()
    audit = _ReleaseAudit()
    client = _app(
        current_version=1,
        reviewed_version=1,
        run_id=run_id,
        draft_id=draft_id,
        audit=audit,
    )

    response = client.post(f"/api/runs/{run_id}/drafts/{draft_id}/approve")

    assert response.status_code == 200
    assert response.json()["version"] == 1
    assert len(audit.approvals) == 1


def test_an_older_approved_version_cannot_be_exported_after_a_human_edit() -> None:
    """v1's approval must not leak forward onto v2.

    Export always resolves the current version, so an approval recorded for v1
    has to be invisible once v2 exists — otherwise a human edit would ship text
    that was approved in its previous form only.
    """
    run_id = uuid4()
    draft_id = uuid4()
    audit = _ReleaseAudit(approved_versions=(1,))
    client = _app(
        current_version=2,
        reviewed_version=2,
        run_id=run_id,
        draft_id=draft_id,
        audit=audit,
    )

    response = client.get(f"/api/runs/{run_id}/drafts/{draft_id}/export.json")

    assert response.status_code == 409
    assert audit.exports == []


def test_the_reviewed_and_approved_version_can_be_exported() -> None:
    run_id = uuid4()
    draft_id = uuid4()
    audit = _ReleaseAudit(approved_versions=(2,))
    client = _app(
        current_version=2,
        reviewed_version=2,
        run_id=run_id,
        draft_id=draft_id,
        audit=audit,
    )

    response = client.get(f"/api/runs/{run_id}/drafts/{draft_id}/export.json")

    assert response.status_code == 200
    assert response.json()["version"] == 2
    assert len(audit.exports) == 1
