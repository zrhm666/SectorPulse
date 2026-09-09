import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from hashlib import sha256

import pytest
from sector_pulse.domain.review.editing import DraftPatch
from sector_pulse.domain.review.release_audit import DraftApproval
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.review.draft_edit_repository import (
    DraftVersionConflict,
    SQLiteDraftEditRepository,
)
from sector_pulse.storage.sqlite.review.release_audit_repository import SQLiteReleaseAuditRepository
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from backend.tests.unit.storage.sqlite.test_draft_edit_repository import make_draft


@pytest.fixture(params=["sqlite", "postgres"])
def repositories(request, tmp_path):
    if request.param == "sqlite":
        database = SQLiteDatabase(tmp_path / "transactions.db")
        yield SQLiteDraftEditRepository(database), SQLiteReleaseAuditRepository(database)
    else:
        url = os.environ.get("SECTOR_PULSE_TEST_DATABASE_URL")
        if not url:
            pytest.skip("requires dedicated SECTOR_PULSE_TEST_DATABASE_URL")
        if "test" not in (make_url(url).database or "").lower():
            pytest.fail("test database name must contain 'test'; business database refused")
        from sector_pulse.storage.postgres.database import PostgresDatabase
        from sector_pulse.storage.postgres.review.draft_edit_repository import (
            PostgresDraftEditRepository,
        )
        from sector_pulse.storage.postgres.review.release_audit_repository import (
            PostgresReleaseAuditRepository,
        )

        database = PostgresDatabase(url)
        database.initialize()
        try:
            yield PostgresDraftEditRepository(database), PostgresReleaseAuditRepository(database)
        finally:
            database.close()


def test_concurrent_edits_have_only_one_winner(repositories):
    repository, _ = repositories
    draft = make_draft()
    repository.save_draft(draft)

    def edit(value):
        operation = DraftPatch(
            path="introduction",
            value=value,
            old_value_hash=sha256(draft.introduction.encode()).hexdigest(),
        )
        try:
            return repository.apply_patch(draft.draft_id, 1, (operation,), actor="test").version
        except DraftVersionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, ["甲", "乙"]))
    assert results.count(2) == 1
    assert results.count("conflict") == 1
    assert repository.latest_version(draft.draft_id).version == 2


def test_edit_does_not_inherit_previous_approval(repositories):
    repository, audit = repositories
    draft = make_draft()
    repository.save_draft(draft)
    approval = DraftApproval(
        run_id=draft.run_id,
        draft_id=draft.draft_id,
        version=1,
        governance_hash="test",
        actor="test",
        approved_at=datetime.now(UTC),
    )
    audit.approve(approval)
    operation = DraftPatch(
        path="introduction",
        value="新导语",
        old_value_hash=sha256(draft.introduction.encode()).hexdigest(),
    )
    saved = repository.apply_patch(draft.draft_id, 1, (operation,), actor="test")
    assert saved.status.value == "UNREVIEWED"
    assert audit.approval(draft.draft_id, 1) is not None
    assert audit.approval(draft.draft_id, 2) is None


def test_failed_audit_rolls_back_version_in_both_databases(repositories):
    import sqlite3

    repository, _ = repositories
    draft = make_draft()
    repository.save_draft(draft)
    first = DraftPatch(path="introduction", value="新导语",
                       old_value_hash=sha256(draft.introduction.encode()).hexdigest())
    second = DraftPatch(patch_id=first.patch_id, path="conclusion", value="新结论",
                        old_value_hash=sha256(draft.conclusion.encode()).hexdigest())
    with pytest.raises((sqlite3.IntegrityError, IntegrityError)):
        repository.apply_patch(draft.draft_id, 1, (first, second), actor="test")
    assert repository.latest_version(draft.draft_id).version == 1
