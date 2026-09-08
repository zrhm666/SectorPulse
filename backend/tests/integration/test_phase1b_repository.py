from uuid import uuid4

import pytest
from sector_pulse.domain.writing.article import ArticleDraft, DraftStatus
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.writing.phase1b_repository import (
    ImmutableDraftVersionError,
    SQLitePhase1BRepository,
)


def make_draft(version: int) -> ArticleDraft:
    return ArticleDraft(
        draft_id=uuid4(),
        run_id=uuid4(),
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


def test_draft_versions_are_append_only(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "phase1b.db")
    repository = SQLitePhase1BRepository(database)
    first = make_draft(1)
    second = first.model_copy(update={"version": 2})
    repository.save_draft(first)
    repository.save_draft(second)
    assert [item.version for item in repository.list_drafts(first.draft_id)] == [1, 2]
    with pytest.raises(ImmutableDraftVersionError):
        repository.save_draft(first.model_copy(update={"titles": ("不同",)}))
