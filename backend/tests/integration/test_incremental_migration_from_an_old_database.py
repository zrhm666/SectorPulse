# backend/tests/integration/test_incremental_migration_from_an_old_database.py
"""An existing deployment has to upgrade in place, without losing or inventing data.

The upgrade path is the one thing a fresh-database test can never cover: every other
test in this suite starts from the current schema, so a migration that breaks on a
populated old file would pass the whole suite and fail in the field.
"""

import shutil
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sector_pulse.storage.migrations import MIGRATIONS_DIR
from sector_pulse.storage.sqlite.database import SQLiteDatabase
from sector_pulse.storage.sqlite.runs.phase1b_runs_repository import SQLitePhase1BRunsRepository
from sector_pulse.web.app import create_app


def _migrations_before(version: int, tmp_path: Path) -> Path:
    """The real migration set as it stood immediately before `version`."""
    target = tmp_path / "old-migrations"
    (target / "sqlite").mkdir(parents=True)
    copied = 0
    for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")):
        if int(path.name[:3]) >= version:
            continue
        shutil.copy(path, target / path.name)
        copied += 1
        dialect = MIGRATIONS_DIR / "sqlite" / path.name
        if dialect.is_file():
            shutil.copy(dialect, target / "sqlite" / path.name)
    # A copy that silently included everything would make the upgrade untested.
    assert 0 < copied < len(list(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")))
    return target


def _insert_run_as_the_old_schema_allowed(database_path: Path, run_id: UUID) -> None:
    """Write a row with exactly the columns migrations 004 and 005 defined.

    No `retry_of_run_id`: that column only arrives in 018, so a row written by the
    old code genuinely has no value for it. `input_json` is included because 017
    rebuilds the whole table from a SELECT that names it — the rebuild is the step
    most likely to lose a row, so the fixture has to have something to lose.
    """
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO phase1b_runs
              (run_id, requested_at, provider, status, elapsed_ms, total_cost_cny, input_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(run_id),
                datetime(2026, 8, 14, 12, tzinfo=UTC).isoformat(),
                "fixture",
                "READY_FOR_HUMAN_REVIEW",
                1200,
                "0.10",
                '{"contexts": []}',
            ),
        )


def test_a_run_written_before_the_table_rebuild_stays_readable(tmp_path: Path) -> None:
    database_path = tmp_path / "old.db"
    run_id = uuid4()
    database = SQLiteDatabase(database_path)
    database.initialize(_migrations_before(17, tmp_path))
    _insert_run_as_the_old_schema_allowed(database_path, run_id)

    # The same file, now pointed at the current migration set.
    database.initialize()

    row = SQLitePhase1BRunsRepository(database).get_run(run_id)
    assert row is not None
    assert row.status == "READY_FOR_HUMAN_REVIEW"
    assert row.total_cost_cny == "0.10"
    # 017 drops the old table and renames the new one; the payload has to survive it.
    assert row.input_json == {"contexts": []}
    # The upgrade adds the column. It must not turn an absent history into a value.
    assert row.retry_of_run_id is None


def _migration_versions(database_path: Path) -> set[int]:
    with sqlite3.connect(database_path) as connection:
        return {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}


def test_an_upgraded_database_serves_its_old_run_and_accepts_a_new_one(tmp_path: Path) -> None:
    """Both halves of the migration promise, on one upgraded file."""
    database_path = tmp_path / "upgraded.db"
    historical = uuid4()
    database = SQLiteDatabase(database_path)
    before = _migrations_before(18, tmp_path)
    database.initialize(before)
    _insert_run_as_the_old_schema_allowed(database_path, historical)

    with TestClient(create_app(database_path=database_path, static_dir=None)) as client:
        # The upgrade really went the whole way, not just far enough to boot.
        expected = {int(path.name[:3]) for path in MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")}
        assert _migration_versions(database_path) == expected

        served = client.get(f"/api/runs/{historical}")
        assert served.status_code == 200
        assert served.json()["execution_engine"] == "legacy"
        assert served.json()["total_cost_cny"] == "0.10"

        created = client.post(
            "/api/runs",
            json={"input_json": {"goal": "升级后新建一次运行"}, "provider": "fixture"},
        )
        assert created.status_code == 200
        assert created.json()["execution_engine"] == "multi_agent"
        new_run = created.json()["run_id"]

        for _ in range(40):
            detail = client.get(f"/api/runs/{new_run}").json()
            if detail["status"] != "RUNNING":
                break
            time.sleep(0.25)
        assert detail["execution_engine"] == "multi_agent"
        assert detail["status"] != "RUNNING"

        # A recorded task tree is the proof the parent agent ran on the upgraded
        # file, rather than the row merely existing.
        tasks = client.get(f"/api/runs/{new_run}/tasks").json()
        assert tasks["recording"] == "recorded"
        assert [task["role"] for task in tasks["tasks"]] == ["A0", "A1"]
        assert detail["status"] == "WAITING_USER_SELECTION"

        # The old row is still there after the new engine wrote its own snapshot.
        assert client.get(f"/api/runs/{historical}").json()["execution_engine"] == "legacy"
