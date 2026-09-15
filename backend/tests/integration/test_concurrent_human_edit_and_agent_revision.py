"""Why human edits and agent revisions need a shared guard.

The agent commits a draft artifact through the orchestration snapshot revision;
the human commits through the draft-edits version, into a different table. This
records that the two raw repositories are independent by construction and that
each one alone will happily accept its own write -- which is exactly why
`HumanDraftEditService` drives the human write through the snapshot revision
instead of letting the router call the repository directly.

See test_human_edit_joins_orchestration_cas.py for the enforced behaviour.
"""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from sector_pulse.domain.orchestration.models import (
    ArtifactRef,
    RunSnapshot,
    TaskRecord,
    TaskStatus,
)
from sector_pulse.domain.review.editing import DraftPatch
from sector_pulse.domain.writing.article import ArticleDraft, DraftStatus
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.orchestration.repository import SQLiteOrchestrationRepository
from sector_pulse.storage.sqlite.review.draft_edit_repository import SQLiteDraftEditRepository

pytest.importorskip("aidynamic_agent")

OBSERVED_AT = datetime(2026, 9, 15, 9, tzinfo=UTC)


def _draft(run_id, draft_id, version: int, introduction: str) -> ArticleDraft:
    return ArticleDraft(
        draft_id=draft_id,
        run_id=run_id,
        version=version,
        status=DraftStatus.INCOMPLETE,
        titles=("标题",),
        introduction=introduction,
        sections=(),
        conclusion="总结",
        risk_notice="风险提示",
        sources=(),
        character_count=len(introduction),
    )


def test_the_two_raw_repositories_do_not_share_a_cas_guard(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "concurrent-draft.db")
    database.initialize()
    run_id = uuid4()
    draft_id = uuid4()
    artifact_id = uuid4()
    task_id = uuid4()

    repository = SQLiteOrchestrationRepository(database)
    repository.save(
        RunSnapshot(
            run_id=run_id,
            requested_at=OBSERVED_AT,
            deadline=OBSERVED_AT + timedelta(minutes=30),
            tasks=(
                TaskRecord(
                    task_id=task_id,
                    role="A3",
                    scope=f"revision:{draft_id}:1",
                    status=TaskStatus.WAITING,
                ),
            ),
        ),
        -1,
        "run.created",
    )
    snapshot_version = repository.load(run_id).revision

    # The agent revises v1 into v2 and admits it through the snapshot revision.
    agent_revision = ArtifactRef(
        artifact_id=artifact_id, task_id=task_id, attempt=1, kind="article_draft", reference="v2"
    )
    repository.save(
        repository.load(run_id).model_copy(
            update={"revision": snapshot_version + 1, "artifacts": (agent_revision,)}
        ),
        snapshot_version,
        "artifact.admitted",
    )

    # The human edits from v1 at the same time and wins its own CAS.
    edits = SQLiteDraftEditRepository(database)
    base = _draft(run_id, draft_id, 1, "原始导语")
    edits.save_draft(base)
    human = edits.apply_patch(
        draft_id,
        1,
        (
            DraftPatch(
                path="introduction",
                old_value_hash=sha256(base.introduction.encode()).hexdigest(),
                value="人工导语",
            ),
        ),
        actor="editor",
    )

    # Both writes landed: nothing made the second one lose.
    assert human.version == 2
    state = repository.load(run_id)
    assert state is not None
    assert [item.artifact_id for item in state.artifacts] == [artifact_id]
    assert state.revision == snapshot_version + 1

    # ...and the two stores now disagree about what the current draft is, which
    # is precisely the state a single CAS must make impossible.
    assert edits.latest_version(draft_id).introduction == "人工导语"
    assert edits.get_version(draft_id, 2).introduction != "原始导语"
