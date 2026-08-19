from sector_pulse.storage.sqlite import SQLiteDatabase


def test_phase2a_migration_creates_task_tables(tmp_path):
    db = SQLiteDatabase(tmp_path / "phase2a.db")

    db.initialize()

    with db.connection() as connection:
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert {
        "schedules",
        "task_runs",
        "run_stage_attempts",
        "run_checkpoints",
        "task_events",
    } <= names
