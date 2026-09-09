import json
import os
import subprocess
import sys

from sector_pulse.storage.sqlite.database import SQLiteDatabase

from backend.tests.integration.test_phase1b_pipeline import contexts
from backend.tests.unit.application.writing.test_revision_agent import inputs

pytest_plugins = ["backend.tests.integration.test_draft_repair_transactions"]


def test_cli_preview_then_confirmed_apply(repositories):
    edits, _ = repositories
    repo = edits._drafts
    database = edits._database
    path = database._path if isinstance(database, SQLiteDatabase) else None
    env = dict(os.environ)
    if path is None:
        env["SECTOR_PULSE_DATABASE_URL"] = os.environ["SECTOR_PULSE_TEST_DATABASE_URL"]
    draft, _, _, _ = inputs()
    draft = draft.model_copy(
        update={
            "sections": (
                draft.sections[0].model_copy(
                    update={
                        "heading": "板块一：观察",
                        "body": "该板块表现分化。（已复核）",
                    }
                ),
            )
        }
    )
    repo.save_draft(draft)
    repo.save_contexts(
        (
            contexts()[0].model_copy(
                update={
                    "run_id": draft.run_id,
                    "sector_id": "1",
                    "sector_name": "文化传媒",
                }
            ),
        )
    )
    before = path.read_bytes() if path else None
    command = [
        sys.executable,
        "scripts/repair_draft_identity.py",
        *(["--sqlite", str(path)] if path else []),
        "--run-id",
        str(draft.run_id),
        "--draft-id",
        str(draft.draft_id),
        "--expected-version",
        "1",
        "--confirmed-system-markers",
    ]
    result = subprocess.run(command, capture_output=True, encoding="utf-8", check=False, env=env)
    assert result.returncode == 0, result.stderr
    preview = json.loads(result.stdout)
    assert preview["mode"] == "dry-run"
    assert preview["proposed_version"] == 2
    assert preview["changes"][0]["after"] == "文化传媒：观察"
    if path:
        assert path.read_bytes() == before
    assert len(repo.list_drafts(draft.draft_id)) == 1
    wrong = subprocess.run(
        command + ["--apply", "--expected-preview-hash", "wrong", "--actor", "tester"],
        capture_output=True,
        encoding="utf-8",
        check=False,
        env=env,
    )
    assert wrong.returncode != 0
    assert len(repo.list_drafts(draft.draft_id)) == 1
    applied = subprocess.run(
        command
        + ["--apply", "--expected-preview-hash", preview["preview_hash"], "--actor", "tester"],
        capture_output=True,
        encoding="utf-8",
        check=False,
        env=env,
    )
    assert applied.returncode == 0, applied.stderr
    assert json.loads(applied.stdout)["mode"] == "applied"
    assert len(repo.list_drafts(draft.draft_id)) == 2
    assert repo.list_drafts(draft.draft_id)[-1].status.value == "UNREVIEWED"
