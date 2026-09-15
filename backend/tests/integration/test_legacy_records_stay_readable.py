"""Old runs keep saying only what they actually recorded.

A legacy run has no orchestration snapshot. That is a fact about when it ran,
not a defect and not a failure: the query layer must report the missing task
tree as "not recorded" and leave the draft, its versions, the approval and the
retry lineage exactly as they were persisted.
"""

from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from fastapi.testclient import TestClient
from sector_pulse.domain.review.editing import DraftPatch
from sector_pulse.domain.review.release_audit import DraftApproval
from sector_pulse.domain.writing.article import ArticleDraft, DraftStatus
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.review.draft_edit_repository import SQLiteDraftEditRepository
from sector_pulse.storage.sqlite.review.release_audit_repository import SQLiteReleaseAuditRepository
from sector_pulse.storage.sqlite.runs.phase1b_runs_repository import (
    Phase1BRunRow,
    SQLitePhase1BRunsRepository,
)
from sector_pulse.web.app import create_app

APPROVED_AT = datetime(2026, 8, 20, 10, tzinfo=UTC)


def _legacy_draft(run_id) -> ArticleDraft:
    return ArticleDraft(
        draft_id=uuid4(),
        run_id=run_id,
        version=1,
        status=DraftStatus.INCOMPLETE,
        titles=("历史标题",),
        introduction="历史导语",
        sections=(),
        conclusion="历史总结",
        risk_notice="风险提示",
        sources=(),
        character_count=12,
    )


def test_legacy_run_keeps_its_draft_versions_approval_and_retry_lineage(tmp_path) -> None:
    database_path = tmp_path / "legacy-history.db"
    database = SQLiteDatabase(database_path)
    database.initialize()
    requested_at = datetime(2026, 8, 20, 9, tzinfo=UTC)
    source_run_id = uuid4()
    run_id = uuid4()
    SQLitePhase1BRunsRepository(database).insert(
        Phase1BRunRow(
            run_id=source_run_id,
            requested_at=requested_at,
            provider="fixture",
            status="FAILED",
        )
    )
    SQLitePhase1BRunsRepository(database).insert(
        Phase1BRunRow(
            run_id=run_id,
            requested_at=requested_at,
            provider="fixture",
            status="READY_FOR_HUMAN_REVIEW",
            retry_of_run_id=source_run_id,
        )
    )

    edits = SQLiteDraftEditRepository(database)
    draft = _legacy_draft(run_id)
    edits.save_draft(draft)
    edits.apply_patch(
        draft.draft_id,
        1,
        (
            DraftPatch(
                path="introduction",
                old_value_hash=sha256(draft.introduction.encode()).hexdigest(),
                value="人工修订后的导语",
            ),
        ),
        actor="editor",
    )

    audit = SQLiteReleaseAuditRepository(database)
    audit.approve(
        DraftApproval(
            run_id=run_id,
            draft_id=draft.draft_id,
            version=2,
            governance_hash="governance-hash",
            actor="reviewer",
            approved_at=APPROVED_AT,
        )
    )

    with TestClient(create_app(database_path=database_path, static_dir=None)) as client:
        detail = client.get(f"/api/runs/{run_id}")
        tasks = client.get(f"/api/runs/{run_id}/tasks")

    assert detail.status_code == 200
    body = detail.json()
    assert body["execution_engine"] == "legacy"
    assert body["retry_of_run_id"] == str(source_run_id)
    assert body["status"] == "READY_FOR_HUMAN_REVIEW"

    # The missing task tree is an absence of recording, never evidence of failure.
    assert tasks.status_code == 200
    assert tasks.json() == {
        "recording": "not_recorded",
        "tasks": [],
        "artifacts": [],
        "tool_invocations": [],
        "model_calls": [],
        "budget": {},
    }

    assert edits.latest_version(draft.draft_id).version == 2
    assert edits.latest_version(draft.draft_id).introduction == "人工修订后的导语"
    assert edits.get_version(draft.draft_id, 1).introduction == "历史导语"

    approval = audit.approval(draft.draft_id, 2)
    assert approval is not None
    assert approval.status.value == "APPROVED_FOR_COPY"
    assert approval.actor == "reviewer"
    assert approval.approved_at == APPROVED_AT
    assert audit.approval(draft.draft_id, 1) is None
