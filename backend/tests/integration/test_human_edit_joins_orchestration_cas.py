"""A human edit and an agent revision must share one optimistic-concurrency guard.

The two writers touch different tables (the agent admits an editorial draft
artifact, the human patches `article_drafts`), so the draft version alone cannot
tell either of them that the other moved. The orchestration snapshot revision is
the one value both transactions can advance, so a human edit states the revision
it was based on and loses cleanly if an agent got there first.
"""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from sector_pulse.domain.orchestration.models import RunSnapshot, TaskRecord, TaskStatus
from sector_pulse.domain.review.editing import DraftPatch
from sector_pulse.domain.writing.article import ArticleDraft, DraftStatus
from sector_pulse.ports.orchestration import RevisionConflict
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository
from sector_pulse.storage.sqlite.review.draft_edit_repository import SQLiteDraftEditRepository

pytest.importorskip("aidynamic_agent")

OBSERVED_AT = datetime(2026, 9, 15, 9, tzinfo=UTC)


def _base_draft(run_id, draft_id) -> ArticleDraft:
    return ArticleDraft(
        draft_id=draft_id,
        run_id=run_id,
        version=1,
        status=DraftStatus.INCOMPLETE,
        titles=("标题",),
        introduction="原始导语",
        sections=(),
        conclusion="总结",
        risk_notice="风险提示",
        sources=(),
        character_count=4,
    )


def _patch(base: ArticleDraft, value: str) -> DraftPatch:
    return DraftPatch(
        path="introduction",
        old_value_hash=sha256(base.introduction.encode()).hexdigest(),
        value=value,
    )


def _seed(tmp_path):
    database = SQLiteDatabase(tmp_path / "human-edit-cas.db")
    database.initialize()
    run_id = uuid4()
    draft_id = uuid4()
    repository = SQLiteOrchestrationRepository(database)
    repository.save(
        RunSnapshot(
            run_id=run_id,
            requested_at=OBSERVED_AT,
            deadline=OBSERVED_AT + timedelta(minutes=30),
            tasks=(
                TaskRecord(
                    task_id=uuid4(),
                    role="A0",
                    scope="分析半导体板块",
                    status=TaskStatus.WAITING_USER_REVIEW,
                ),
            ),
        ),
        -1,
        "run.created",
    )
    edits = SQLiteDraftEditRepository(database)
    base = _base_draft(run_id, draft_id)
    edits.save_draft(base)
    return database, repository, edits, run_id, draft_id, base


def test_human_edit_loses_when_an_agent_revision_already_moved_the_snapshot(tmp_path) -> None:
    from sector_pulse.application.review.human_draft_edit import HumanDraftEditService

    database, repository, edits, run_id, draft_id, base = _seed(tmp_path)
    service = HumanDraftEditService(draft_edits=edits, orchestration=repository)
    stale_revision = repository.load(run_id).revision

    # An agent revision advances the snapshot first.
    current = repository.load(run_id)
    repository.save(
        current.model_copy(update={"revision": current.revision + 1}),
        current.revision,
        "artifact.admitted",
    )

    with pytest.raises(RevisionConflict):
        service.apply(
            run_id,
            draft_id,
            1,
            (_patch(base, "人工导语"),),
            actor="editor",
            base_revision=stale_revision,
        )

    # Neither side half-applied: the draft never reached v2.
    assert edits.latest_version(draft_id).version == 1
    assert edits.latest_version(draft_id).introduction == "原始导语"


def test_human_edit_advances_the_snapshot_so_the_agent_loses_next(tmp_path) -> None:
    from sector_pulse.application.review.human_draft_edit import HumanDraftEditService

    database, repository, edits, run_id, draft_id, base = _seed(tmp_path)
    service = HumanDraftEditService(draft_edits=edits, orchestration=repository)
    revision = repository.load(run_id).revision

    edited = service.apply(
        run_id,
        draft_id,
        1,
        (_patch(base, "人工导语"),),
        actor="editor",
        base_revision=revision,
    )

    assert edited.version == 2
    assert edits.latest_version(draft_id).introduction == "人工导语"
    # The human edit moved the shared guard...
    assert repository.load(run_id).revision == revision + 1
    # ...so the revision the agent was working against is now stale.
    with pytest.raises(RevisionConflict):
        repository.save(
            repository.load(run_id).model_copy(update={"revision": revision + 1}),
            revision,
            "artifact.admitted",
        )


def test_human_edit_on_a_run_without_a_snapshot_still_works(tmp_path) -> None:
    from sector_pulse.application.review.human_draft_edit import HumanDraftEditService

    database = SQLiteDatabase(tmp_path / "legacy-human-edit.db")
    database.initialize()
    edits = SQLiteDraftEditRepository(database)
    repository = SQLiteOrchestrationRepository(database)
    run_id = uuid4()
    draft_id = uuid4()
    base = _base_draft(run_id, draft_id)
    edits.save_draft(base)
    service = HumanDraftEditService(draft_edits=edits, orchestration=repository)

    edited = service.apply(
        run_id,
        draft_id,
        1,
        (_patch(base, "人工导语"),),
        actor="editor",
        base_revision=None,
    )

    assert edited.version == 2


def test_http_patch_with_a_stale_revision_is_refused_and_leaves_the_draft_alone(tmp_path) -> None:
    """The product surface must expose the same guard the service enforces."""
    from fastapi.testclient import TestClient
    from sector_pulse.web.app import create_app

    database, repository, edits, run_id, draft_id, base = _seed(tmp_path)
    client = TestClient(
        create_app(database_path=tmp_path / "human-edit-cas.db", static_dir=None)
    )
    stale_revision = repository.load(run_id).revision

    current = repository.load(run_id)
    repository.save(
        current.model_copy(update={"revision": current.revision + 1}),
        current.revision,
        "artifact.admitted",
    )

    response = client.post(
        f"/api/runs/{run_id}/drafts/{draft_id}/patches",
        json={
            "base_version": 1,
            "base_revision": stale_revision,
            "operations": [
                {
                    "path": "introduction",
                    "old_value_hash": sha256(base.introduction.encode()).hexdigest(),
                    "value": "人工导语",
                }
            ],
        },
    )

    assert response.status_code == 409
    assert edits.latest_version(draft_id).version == 1
