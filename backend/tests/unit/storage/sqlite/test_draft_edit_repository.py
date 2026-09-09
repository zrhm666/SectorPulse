from hashlib import sha256
from uuid import uuid4

import pytest
from sector_pulse.domain.review.editing import DraftPatch
from sector_pulse.domain.writing.article import ArticleDraft, DraftStatus
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.review.draft_edit_repository import (
    DraftVersionConflict,
    SQLiteDraftEditRepository,
)


def make_draft() -> ArticleDraft:
    return ArticleDraft(
        draft_id=uuid4(),
        run_id=uuid4(),
        version=1,
        status=DraftStatus.INCOMPLETE,
        titles=("标题",),
        introduction="导语",
        sections=(),
        conclusion="总结",
        risk_notice="风险提示",
        sources=(),
        character_count=8,
    )


def test_patch_creates_new_version_without_mutating_base(tmp_path):
    database = SQLiteDatabase(tmp_path / "edits.db")
    repository = SQLiteDraftEditRepository(database)
    draft = make_draft()
    repository.save_draft(draft)
    operation = DraftPatch(
        path="introduction",
        old_value_hash=sha256(draft.introduction.encode()).hexdigest(),
        value="新的导语",
    )

    result = repository.apply_patch(draft.draft_id, 1, (operation,), actor="tester")

    assert result.version == 2
    assert result.introduction == "新的导语"
    assert repository.get_version(draft.draft_id, 1).introduction == "导语"


def test_patch_can_replace_one_title_without_mutating_base(tmp_path):
    database = SQLiteDatabase(tmp_path / "title-edits.db")
    repository = SQLiteDraftEditRepository(database)
    draft = make_draft()
    repository.save_draft(draft)
    operation = DraftPatch(
        path="titles/0",
        old_value_hash=sha256(draft.titles[0].encode()).hexdigest(),
        value="新标题",
    )

    result = repository.apply_patch(draft.draft_id, 1, (operation,), actor="tester")

    assert result.version == 2
    assert result.titles == ("新标题",)
    assert repository.get_version(draft.draft_id, 1).titles == ("标题",)


def test_stale_base_version_is_conflict(tmp_path):
    database = SQLiteDatabase(tmp_path / "edits.db")
    repository = SQLiteDraftEditRepository(database)
    draft = make_draft()
    repository.save_draft(draft)

    with pytest.raises(DraftVersionConflict):
        repository.apply_patch(draft.draft_id, 0, (), actor="tester")


def test_audit_failure_rolls_back_new_version(tmp_path):
    import sqlite3

    database = SQLiteDatabase(tmp_path / "atomic.db")
    repository = SQLiteDraftEditRepository(database)
    draft = make_draft()
    repository.save_draft(draft)
    first = DraftPatch(
        path="introduction",
        old_value_hash=sha256(draft.introduction.encode()).hexdigest(),
        value="新导语",
    )
    second = DraftPatch(
        patch_id=first.patch_id,
        path="conclusion",
        old_value_hash=sha256(draft.conclusion.encode()).hexdigest(),
        value="新结论",
    )
    with pytest.raises(sqlite3.IntegrityError):
        repository.apply_patch(draft.draft_id, 1, (first, second), actor="tester")
    assert repository.latest_version(draft.draft_id).version == 1
    with database.connection() as connection:
        assert connection.execute("SELECT count(*) FROM draft_patches").fetchone()[0] == 0


def test_content_edit_resets_review_status_and_recalculates_length(tmp_path):
    database = SQLiteDatabase(tmp_path / "status.db")
    repository = SQLiteDraftEditRepository(database)
    from sector_pulse.domain.writing.article import DraftStatus

    draft = make_draft().model_copy(update={"status": DraftStatus.REVISE_REQUIRED})
    repository.save_draft(draft)
    operation = DraftPatch(
        path="introduction",
        old_value_hash=sha256(draft.introduction.encode()).hexdigest(),
        value="新的导语内容",
    )
    result = repository.apply_patch(draft.draft_id, 1, (operation,), actor="tester")
    assert result.status.value == "UNREVIEWED"
    assert result.character_count == len("新的导语内容") + len(draft.conclusion)
