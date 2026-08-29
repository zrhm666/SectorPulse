import shutil
import sqlite3
from pathlib import Path

import pytest
from sector_pulse.storage.sqlite import SQLiteDatabase

EXPECTED_TABLES = {
    "schema_migrations",
    "analysis_runs",
    "sector_snapshots",
    "news_documents",
    "news_events",
    "news_event_documents",
    "sector_candidates",
    "evidence_packs",
    "real_data_runs",
    "real_data_candidates",
}


def test_initialize_creates_phase1a_tables(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "sector-pulse.db")
    database.initialize()

    with database.connection() as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()

    assert {row[0] for row in rows} >= EXPECTED_TABLES


def test_initialize_is_idempotent(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "sector-pulse.db")
    database.initialize()
    database.initialize()

    with database.connection() as connection:
        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()

        assert versions == [(version,) for version in range(1, 17)]


def test_reliable_runtime_migration_adds_lifecycle_columns(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "runtime.db")
    database.initialize()

    with database.connection() as connection:
        task_columns = {row[1] for row in connection.execute("PRAGMA table_info(task_runs)")}
        run_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(real_data_runs)")
        }
        schedule_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(schedules)")
        }

    assert {
        "retry_of_run_id",
        "cancel_requested_at",
        "interrupted_reason",
        "heartbeat_at",
    } <= task_columns
    assert "retry_of_run_id" in run_columns
    assert "last_triggered_at" in schedule_columns


def test_reliable_runtime_migration_preserves_existing_task_and_foreign_keys(
    tmp_path: Path,
) -> None:
    migration_source = Path("backend/src/sector_pulse/storage/migrations")
    legacy_migrations = tmp_path / "legacy-migrations"
    legacy_migrations.mkdir()
    for source in migration_source.glob("[0-9][0-9][0-9]_*.sql"):
        if int(source.name[:3]) <= 15:
            shutil.copy2(source, legacy_migrations / source.name)

    database = SQLiteDatabase(tmp_path / "upgrade.db")
    database.initialize(legacy_migrations)
    with database.transaction() as connection:
        connection.execute(
            """INSERT INTO task_runs
            (run_id, provider, input_fingerprint, status, requested_at)
            VALUES (?, ?, ?, ?, ?)""",
            ("run-before-016", "fixture", "legacy", "RUNNING", "2026-08-30T00:00:00Z"),
        )
        connection.execute(
            """INSERT INTO task_events
            (event_id, run_id, source, event_type, summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "event-before-016",
                "run-before-016",
                "test",
                "STARTED",
                "legacy event",
                "2026-08-30T00:00:00Z",
            ),
        )

    database.initialize()
    with database.transaction() as connection:
        connection.execute(
            "UPDATE task_runs SET status = 'INTERRUPTED' WHERE run_id = 'run-before-016'"
        )
        status = connection.execute(
            "SELECT status FROM task_runs WHERE run_id = 'run-before-016'"
        ).fetchone()
        event = connection.execute(
            "SELECT event_id FROM task_events WHERE run_id = 'run-before-016'"
        ).fetchone()
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()

    assert status == ("INTERRUPTED",)
    assert event == ("event-before-016",)
    assert foreign_key_errors == []


def test_failed_migration_rolls_back_schema_and_version(tmp_path: Path) -> None:
    migration_source = Path("backend/src/sector_pulse/storage/migrations")
    broken_migrations = tmp_path / "broken-migrations"
    broken_migrations.mkdir()
    for source in migration_source.glob("[0-9][0-9][0-9]_*.sql"):
        if int(source.name[:3]) <= 15:
            shutil.copy2(source, broken_migrations / source.name)
    database = SQLiteDatabase(tmp_path / "rollback.db")
    database.initialize(broken_migrations)
    (broken_migrations / "016_broken.sql").write_text(
        "ALTER TABLE schedules ADD COLUMN temporary_marker TEXT;\n"
        "INSERT INTO table_that_does_not_exist(value) VALUES (1);\n",
        encoding="utf-8",
    )

    with pytest.raises(sqlite3.OperationalError):
        database.initialize(broken_migrations)

    with database.connection() as connection:
        schedule_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(schedules)")
        }
        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()

    assert "temporary_marker" not in schedule_columns
    assert versions == [(version,) for version in range(1, 16)]


def test_analysis_run_id_is_unique(tmp_path: Path) -> None:
    database = SQLiteDatabase(tmp_path / "sector-pulse.db")
    database.initialize()
    insert = """
        INSERT INTO analysis_runs (
            run_id, mode, requested_at, run_cutoff_at, cutoff_locked_at
        ) VALUES (?, ?, ?, ?, ?)
    """
    values = (
        "run-1",
        "LIVE",
        "2026-08-14T01:40:00+00:00",
        "2026-08-14T01:40:01+00:00",
        "2026-08-14T01:40:02+00:00",
    )

    with database.transaction() as connection:
        connection.execute(insert, values)

    with pytest.raises(sqlite3.IntegrityError), database.transaction() as connection:
        connection.execute(insert, values)
