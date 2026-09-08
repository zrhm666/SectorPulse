from hashlib import sha256
from uuid import uuid4

from fastapi.testclient import TestClient
from sector_pulse.domain.writing.article import ArticleDraft, DraftStatus
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.writing.phase1b_repository import SQLitePhase1BRepository
from sector_pulse.web.app import create_app


def test_patch_and_governance_are_versioned(tmp_path):
    database_path = tmp_path / "phase2b.db"
    database = SQLiteDatabase(database_path)
    repository = SQLitePhase1BRepository(database)
    draft = ArticleDraft(
        draft_id=uuid4(),
        run_id=uuid4(),
        version=1,
        status=DraftStatus.INCOMPLETE,
        titles=("标题",),
        introduction="导语",
        sections=(),
        conclusion="总结",
        risk_notice="风险",
        sources=(),
        character_count=8,
    )
    repository.save_draft(draft)
    client = TestClient(create_app(database_path=database_path))

    response = client.post(
        f"/api/runs/{draft.run_id}/drafts/{draft.draft_id}/patches",
        json={
            "base_version": 1,
            "operations": [
                {
                    "path": "introduction",
                    "old_value_hash": sha256("导语".encode()).hexdigest(),
                    "value": "新的导语",
                }
            ],
        },
    )

    assert response.status_code == 201
    assert response.json()["version"] == 2
    governance = client.get(f"/api/runs/{draft.run_id}/governance")
    assert governance.status_code == 200

    approval = client.post(
        f"/api/runs/{draft.run_id}/drafts/{draft.draft_id}/approve",
        headers={"X-Actor": "reviewer"},
    )
    assert approval.status_code == 422


def test_patch_rejects_wrong_run_before_creating_a_version(tmp_path):
    database_path = tmp_path / "wrong-run.db"
    database = SQLiteDatabase(database_path)
    repository = SQLitePhase1BRepository(database)
    draft = ArticleDraft(
        draft_id=uuid4(),
        run_id=uuid4(),
        version=1,
        status=DraftStatus.INCOMPLETE,
        titles=("标题",),
        introduction="导语",
        sections=(),
        conclusion="总结",
        risk_notice="风险",
        sources=(),
        character_count=8,
    )
    repository.save_draft(draft)
    client = TestClient(create_app(database_path=database_path))

    response = client.post(
        f"/api/runs/{uuid4()}/drafts/{draft.draft_id}/patches",
        json={
            "base_version": 1,
            "operations": [
                {
                    "path": "introduction",
                    "old_value_hash": sha256("导语".encode()).hexdigest(),
                    "value": "不应保存",
                }
            ],
        },
    )

    assert response.status_code == 404
    assert len(repository.list_drafts(draft.draft_id)) == 1
