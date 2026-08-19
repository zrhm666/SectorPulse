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

    assert versions == [(1,), (2,), (3,), (4,), (5,), (6,), (7,)]


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
