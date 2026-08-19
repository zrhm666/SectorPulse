from hashlib import sha256
from uuid import uuid4

import pytest
from sector_pulse.domain.article import ArticleDraft, DraftStatus
from sector_pulse.domain.editing import DraftPatch
from sector_pulse.storage.draft_edit_repository import (
    DraftVersionConflict,
    SQLiteDraftEditRepository,
)
from sector_pulse.storage.sqlite import SQLiteDatabase


def make_draft() -> ArticleDraft:
    return ArticleDraft(
        draft_id=uuid4(), run_id=uuid4(), version=1, status=DraftStatus.INCOMPLETE,
        titles=("标题",), introduction="导语", sections=(), conclusion="总结",
        risk_notice="风险提示", sources=(), character_count=8,
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


def test_stale_base_version_is_conflict(tmp_path):
    database = SQLiteDatabase(tmp_path / "edits.db")
    repository = SQLiteDraftEditRepository(database)
    draft = make_draft()
    repository.save_draft(draft)

    with pytest.raises(DraftVersionConflict):
        repository.apply_patch(draft.draft_id, 0, (), actor="tester")
