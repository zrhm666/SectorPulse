from sector_pulse.storage.sqlite import SQLiteDatabase


def test_phase2b_migration_creates_governance_tables(tmp_path):
    database = SQLiteDatabase(tmp_path / "phase2b.db")
    database.initialize()
    with database.connection() as connection:
        names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert {
        "draft_patches",
        "evidence_decisions",
        "rewrite_requests",
        "governance_checks",
        "preference_candidates",
        "preference_versions",
    } <= names
