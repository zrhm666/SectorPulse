from uuid import uuid4

from fastapi.testclient import TestClient

from sector_pulse.domain.article import ArticleDraft, ArticleSection, ArticleSource, DraftStatus
from sector_pulse.storage.phase1b_repository import SQLitePhase1BRepository
from sector_pulse.storage.sqlite import SQLiteDatabase
from sector_pulse.web.app import create_app


def _client_with_draft(tmp_path):
    database_path = tmp_path / "phase4.db"
    database = SQLiteDatabase(database_path)
    draft = ArticleDraft(
        draft_id=uuid4(), run_id=uuid4(), version=1, status=DraftStatus.INCOMPLETE,
        titles=("标题",), introduction="导语",
        sections=(ArticleSection(section_id="section-1", sector_id="sector-1", heading="板块", body="正文", claims=(), source_ids=("source-1",), character_count=2),),
        conclusion="结论", risk_notice="风险",
        sources=(ArticleSource(source_id="source-1", title="来源", citation_url="https://example.test/source"),),
        character_count=8,
    )
    SQLitePhase1BRepository(database).save_draft(draft)
    return TestClient(create_app(database_path=database_path)), draft


def test_records_and_lists_evidence_decisions(tmp_path) -> None:
    client, draft = _client_with_draft(tmp_path)
    path = f"/api/runs/{draft.run_id}/drafts/{draft.draft_id}/evidence-decisions"

    created = client.post(path, json={"source_id": "source-1", "decision": "KEEP", "reason": "来源可信"})

    assert created.status_code == 201
    assert created.json()["draft_version"] == 1
    assert created.json()["affected_section_ids"] == ["section-1"]
    assert client.get(path).json()[0]["reason"] == "来源可信"


def test_returns_latest_draft_with_append_only_audit_event(tmp_path) -> None:
    client, draft = _client_with_draft(tmp_path)

    returned = client.post(
        f"/api/runs/{draft.run_id}/drafts/{draft.draft_id}/return",
        headers={"X-Actor": "reviewer"},
        json={"reason": "需要补充证据"},
    )

    assert returned.status_code == 201
    assert returned.json() == {"draft_id": str(draft.draft_id), "version": 1, "status": "RETURNED", "actor": "reviewer"}
    audit = client.get(f"/api/runs/{draft.run_id}/drafts/{draft.draft_id}/audit").json()
    assert audit[-1]["event_type"] == "RETURNED"
    assert audit[-1]["payload"] == {"reason": "需要补充证据"}
