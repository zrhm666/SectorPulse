import json
import subprocess
import sys

from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.writing.phase1b_repository import SQLitePhase1BRepository

from backend.tests.integration.test_phase1b_pipeline import contexts
from backend.tests.unit.application.writing.test_revision_agent import inputs


def test_cli_preview_does_not_write_sqlite(tmp_path):
    path = tmp_path / "preview.db"
    repo = SQLitePhase1BRepository(SQLiteDatabase(path))
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
    before = path.read_bytes()
    command = [
        sys.executable,
        "scripts/repair_draft_identity.py",
        "--sqlite",
        str(path),
        "--run-id",
        str(draft.run_id),
        "--draft-id",
        str(draft.draft_id),
        "--expected-version",
        "1",
        "--confirmed-system-markers",
    ]
    result = subprocess.run(command, capture_output=True, encoding="utf-8", check=False)
    assert result.returncode == 0, result.stderr
    preview = json.loads(result.stdout)
    assert preview["mode"] == "dry-run"
    assert preview["proposed_version"] == 2
    assert preview["changes"][0]["after"] == "文化传媒：观察"
    assert path.read_bytes() == before
    assert len(repo.list_drafts(draft.draft_id)) == 1
